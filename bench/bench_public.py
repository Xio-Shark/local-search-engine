"""Public-dataset retrieval benchmark for lse.

Supports BEIR datasets (scifact / nfcorpus / fiqa / arguana) and compares:
  - lse (custom tokenization + structural evidence spans)
  - native Tantivy BM25 (default tokenizer, no lse logic)
  - ripgrep raw term-match count (literal, case-insensitive)

The benchmark downloads a public zip into a cache directory, materializes each
corpus document as a .txt file, and computes nDCG@10 / Recall@10 / MRR@10.

Examples:
  uv run python bench/bench_public.py --dataset scifact
  uv run python bench/bench_public.py --baselines lse,tantivy
  uv run python bench/bench_public.py --dataset nfcorpus --limit-queries 50
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from lse import __version__ as LSE_VERSION
from lse.indexer import IndexEngine
from lse.searcher import SearchEngine

BEIR_URL = "https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets/{dataset}.zip"
BEIR_DATASETS = {"scifact", "nfcorpus", "fiqa", "arguana", "trec-covid", "climate-fever"}

COIR_SIMPLE_DATASETS = {
    "cosqa": "cosqa",
    "apps": "apps",
    "synthetic-text2sql": "synthetic-text2sql",
    "codefeedback-st": "codefeedback-st",
    "codefeedback-mt": "codefeedback-mt",
    "stackoverflow-qa": "stackoverflow-qa",
    "codetrans-contest": "codetrans-contest",
    "codetrans-dl": "codetrans-dl",
}
COIR_CODE_SEARCH_LANGUAGES = {"go", "java", "javascript", "php", "python", "ruby"}
COIR_DATASETS = set(COIR_SIMPLE_DATASETS) | {
    f"codesearchnet-{language}" for language in COIR_CODE_SEARCH_LANGUAGES
}
HF_RESOLVE = "https://huggingface.co/datasets/{repo}/resolve/main/{path}"
DEFAULT_CACHE = Path(os.environ.get("LSE_EVAL_DATA_DIR", str(Path.home() / ".cache" / "lse-eval")))
METRIC_K = 10

@dataclass(frozen=True)
class EvalDoc:
    doc_id: str
    title: str
    text: str


def _download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    with urllib.request.urlopen(url) as response, partial.open("wb") as output:
        shutil.copyfileobj(response, output)
    partial.replace(destination)


def ensure_beir_dataset(dataset: str, cache_dir: Path) -> Path:
    root = cache_dir / "beir" / dataset
    if (root / "corpus.jsonl").exists():
        return root

    archive = cache_dir / "beir" / f"{dataset}.zip"
    if not archive.exists():
        print(f"[download] {dataset} -> {archive}", file=sys.stderr)
        _download(BEIR_URL.format(dataset=dataset), archive)

    with zipfile.ZipFile(archive) as handle:
        handle.extractall(root.parent)

    if not (root / "corpus.jsonl").exists():
        for candidate in root.parent.iterdir():
            if candidate.is_dir() and (candidate / "corpus.jsonl").exists():
                root = candidate
                break
    if not (root / "corpus.jsonl").exists():
        raise FileNotFoundError(f"BEIR corpus not found after extracting {archive}")
    return root


def load_beir_corpus(root: Path) -> list[EvalDoc]:
    docs: list[EvalDoc] = []
    with (root / "corpus.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            docs.append(
                EvalDoc(
                    doc_id=str(row["_id"]),
                    title=str(row.get("title", "") or ""),
                    text=str(row.get("text", "") or ""),
                )
            )
    return docs


def load_beir_queries(root: Path) -> dict[str, str]:
    queries: dict[str, str] = {}
    with (root / "queries.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            queries[str(row["_id"])] = str(row.get("text", "") or "")
    return queries


def load_beir_qrels(root: Path) -> dict[str, dict[str, float]]:
    candidates = [
        root / "qrels" / "test.tsv",
        root / "qrels" / "dev.tsv",
        root / "qrels.tsv",
    ]
    qrels_path = next((path for path in candidates if path.exists()), None)
    if qrels_path is None:
        raise FileNotFoundError(f"qrels file not found under {root}")

    qrels: dict[str, dict[str, float]] = {}
    with qrels_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle, delimiter="\t")
        for row in reader:
            if len(row) < 3:
                continue
            query_id, doc_id, raw_score = row[0], row[1], row[2]
            try:
                score = float(raw_score)
            except ValueError:
                continue
            if score > 0:
                qrels.setdefault(query_id, {})[doc_id] = score
    return qrels


def materialize_docs(docs: Sequence[EvalDoc], parent: Path) -> tuple[Path, dict[str, str]]:
    docs_dir = parent / "docs"
    shutil.rmtree(docs_dir, ignore_errors=True)
    docs_dir.mkdir(parents=True, exist_ok=True)

    name_to_id: dict[str, str] = {}
    for index, doc in enumerate(docs):
        filename = f"doc_{index:06d}.txt"
        content = f"{doc.title}\n{doc.text}".strip() or " "
        (docs_dir / filename).write_text(content, encoding="utf-8")
        name_to_id[filename] = doc.doc_id
    return docs_dir, name_to_id


def ndcg_at_k(ranked: Sequence[str], relevant: dict[str, float], k: int) -> float:
    dcg = 0.0
    for rank, doc_id in enumerate(ranked[:k], start=1):
        gain = relevant.get(doc_id, 0.0)
        if gain > 0:
            dcg += (2.0 ** gain - 1.0) / math.log2(rank + 1)
    ideal_gains = sorted(relevant.values(), reverse=True)[:k]
    idcg = sum((2.0 ** gain - 1.0) / math.log2(rank + 1)
               for rank, gain in enumerate(ideal_gains, start=1))
    return dcg / idcg if idcg > 0 else 0.0


def recall_at_k(ranked: Sequence[str], relevant: dict[str, float], k: int) -> float:
    if not relevant:
        return 0.0
    found = sum(1 for doc_id in ranked[:k] if doc_id in relevant)
    return found / len(relevant)


def reciprocal_rank_at_k(ranked: Sequence[str], relevant: dict[str, float], k: int) -> float:
    for rank, doc_id in enumerate(ranked[:k], start=1):
        if doc_id in relevant:
            return 1.0 / rank
    return 0.0


def evaluate_retriever(
    retriever,
    queries: dict[str, str],
    qrels: dict[str, dict[str, float]],
    top_k: int,
) -> dict[str, float]:
    ndcg_scores: list[float] = []
    recall_scores: list[float] = []
    mrr_scores: list[float] = []
    latencies_ms: list[float] = []

    started = time.perf_counter()
    for query_id, query_text in queries.items():
        relevant = qrels.get(query_id, {})
        if not query_text.strip() or not relevant:
            continue
        query_started = time.perf_counter()
        ranked = list(retriever.retrieve(query_text, top_k))
        latencies_ms.append((time.perf_counter() - query_started) * 1000.0)
        ndcg_scores.append(ndcg_at_k(ranked, relevant, METRIC_K))
        recall_scores.append(recall_at_k(ranked, relevant, METRIC_K))
        mrr_scores.append(reciprocal_rank_at_k(ranked, relevant, METRIC_K))

    total_seconds = time.perf_counter() - started
    return {
        "queries": float(len(ndcg_scores)),
        "ndcg@10": sum(ndcg_scores) / len(ndcg_scores) if ndcg_scores else 0.0,
        "recall@10": sum(recall_scores) / len(recall_scores) if recall_scores else 0.0,
        "mrr@10": sum(mrr_scores) / len(mrr_scores) if mrr_scores else 0.0,
        "total_seconds": total_seconds,
        "p50_ms": sorted(latencies_ms)[len(latencies_ms) // 2] if latencies_ms else 0.0,
    }


class LseRetriever:
    name = "lse"

    def __init__(self, docs_dir: Path, name_to_id: dict[str, str]) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="lse-public-"))
        self._index_dir = self._tmp / "index"
        IndexEngine(self._index_dir).build([docs_dir])
        self._engine = SearchEngine(self._index_dir)
        self._name_to_id = name_to_id

    def retrieve(self, query: str, top_k: int) -> list[str]:
        result = self._engine.search(query, limit=top_k)
        ranked: list[str] = []
        for hit in result.hits:
            doc_id = self._name_to_id.get(Path(hit.path).name)
            if doc_id is not None:
                ranked.append(doc_id)
        return ranked

    def close(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)


class TantivyBm25Retriever:
    name = "tantivy_bm25"

    def __init__(self, docs: Sequence[EvalDoc], name_to_id: dict[str, str]) -> None:
        import tantivy

        self._tmp = Path(tempfile.mkdtemp(prefix="lse-tantivy-"))
        index_dir = self._tmp / "index"
        index_dir.mkdir(parents=True, exist_ok=True)
        builder = tantivy.SchemaBuilder()
        builder.add_text_field("doc_id", stored=True)
        builder.add_text_field("title", stored=False)
        builder.add_text_field("body", stored=False)
        self._index = tantivy.Index(builder.build(), str(index_dir))
        writer = self._index.writer()
        for doc in docs:
            writer.add_document(
                tantivy.Document.from_dict(
                    {"doc_id": doc.doc_id, "title": doc.title, "body": doc.text}
                )
            )
        writer.commit()
        writer.wait_merging_threads()
        self._index.reload()
        self._searcher = self._index.searcher()
        self._name_to_id = name_to_id

    def retrieve(self, query: str, top_k: int) -> list[str]:
        try:
            parsed = self._index.parse_query(query, ["title", "body"])
        except Exception:
            parsed, _ = self._index.parse_query_lenient(query, ["title", "body"])
        hits = self._searcher.search(parsed, top_k)
        ranked: list[str] = []
        for _score, address in hits.hits:
            doc = self._searcher.doc(address)
            doc_id = doc.get_first("doc_id")
            if doc_id is not None:
                ranked.append(str(doc_id))
        return ranked

    def close(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)


class RipgrepCountRetriever:
    name = "ripgrep"

    def __init__(self, docs_dir: Path, name_to_id: dict[str, str]) -> None:
        self._docs_dir = docs_dir
        self._name_to_id = name_to_id
        self._rg = shutil.which("rg")
        if self._rg is None:
            raise RuntimeError("ripgrep executable not found in PATH")

    def retrieve(self, query: str, top_k: int) -> list[str]:
        import re

        terms = list(dict.fromkeys(re.findall(r"[A-Za-z0-9_]+", query.lower())))
        if not terms:
            return []
        command = [self._rg, "--count-matches", "--no-heading", "--no-messages", "-i", "-F"]
        for term in terms:
            command.extend(["-e", term])
        command.append(str(self._docs_dir))
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode not in (0, 1):
            return []
        counts: list[tuple[int, str]] = []
        for line in completed.stdout.splitlines():
            path_text, separator, count_text = line.rpartition(":")
            if not separator or not count_text.isdigit():
                continue
            name = Path(path_text).name
            doc_id = self._name_to_id.get(name)
            if doc_id is not None:
                counts.append((int(count_text), doc_id))
        counts.sort(key=lambda item: (-item[0], item[1]))
        return [doc_id for _count, doc_id in counts[:top_k]]

    def close(self) -> None:
        return None


def build_retriever(name: str, docs, docs_dir: Path, name_to_id: dict[str, str]):
    if name == "lse":
        return LseRetriever(docs_dir, name_to_id)
    if name == "tantivy":
        return TantivyBm25Retriever(docs, name_to_id)
    if name == "ripgrep":
        return RipgrepCountRetriever(docs_dir, name_to_id)
    raise ValueError(f"unknown baseline: {name}")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Public retrieval benchmark for lse")
    parser.add_argument("--dataset", default="scifact", help="BEIR dataset name or CoIR name (e.g. cosqa, codesearchnet-python)")
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--baselines", default="lse,tantivy,ripgrep")
    parser.add_argument("--top-k", type=int, default=100)
    parser.add_argument("--limit-queries", type=int, default=0)
    parser.add_argument("--output-json", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        docs, queries, qrels = load_dataset(args.dataset, args.cache_dir)
    except (FileNotFoundError, RuntimeError, ValueError) as error:
        print(f"dataset error: {error}", file=sys.stderr)
        return 2

    query_ids = [query_id for query_id in queries if qrels.get(query_id)]
    if args.limit_queries > 0:
        query_ids = query_ids[: args.limit_queries]
    selected_queries = {query_id: queries[query_id] for query_id in query_ids}

    print(f"dataset={args.dataset} docs={len(docs)} queries={len(selected_queries)} "
          f"qrels_queries={len(qrels)} top_k={args.top_k}")

    with tempfile.TemporaryDirectory(prefix=f"lse-bench-{args.dataset}-") as tmp:
        workdir = Path(tmp)
        docs_dir, name_to_id = materialize_docs(docs, workdir)
        results: dict[str, dict[str, float]] = {}
        retriever_names = [name.strip() for name in args.baselines.split(",") if name.strip()]
        for name in retriever_names:
            print(f"running baseline={name} ...", file=sys.stderr)
            retriever = build_retriever(name, docs, docs_dir, name_to_id)
            try:
                results[name] = evaluate_retriever(
                    retriever, selected_queries, qrels, args.top_k
                )
            finally:
                retriever.close()

    print("")
    print(f"{'baseline':<16} {'nDCG@10':>10} {'Recall@10':>10} {'MRR@10':>10} {'p50 ms':>10} {'total s':>10}")
    print("-" * 72)
    for name in results:
        metrics = results[name]
        print(f"{name:<16} {metrics['ndcg@10']:>10.4f} {metrics['recall@10']:>10.4f} "
              f"{metrics['mrr@10']:>10.4f} {metrics['p50_ms']:>10.2f} "
              f"{metrics['total_seconds']:>10.2f}")

    payload = {
        "dataset": args.dataset,
        "docs": len(docs),
        "queries": len(selected_queries),
        "top_k": args.top_k,
        "meta": {
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "lse_version": LSE_VERSION,
            "command": " ".join(sys.argv),
        },
        "results": results,
    }
    if args.output_json is not None:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nwrote {args.output_json}")
    return 0




def coir_file_spec(dataset: str) -> tuple[str, str, str, str]:
    if dataset in COIR_SIMPLE_DATASETS:
        repo = f"CoIR-Retrieval/{COIR_SIMPLE_DATASETS[dataset]}"
        return (
            repo,
            "corpus/corpus-00000-of-00001.parquet",
            "queries/queries-00000-of-00001.parquet",
            "data/test-00000-of-00001.parquet",
        )
    if dataset.startswith("codesearchnet-"):
        language = dataset.split("-", 1)[1]
        if language not in COIR_CODE_SEARCH_LANGUAGES:
            raise ValueError(f"unsupported CodeSearchNet language: {language}")
        prefix = f"{language}-"
        return (
            "CoIR-Retrieval/CodeSearchNet",
            f"{prefix}corpus/corpus-00000-of-00001.parquet",
            f"{prefix}queries/queries-00000-of-00001.parquet",
            f"{prefix}qrels/test-00000-of-00001.parquet",
        )
    raise ValueError(f"unknown CoIR dataset: {dataset}")


def ensure_coir_dataset(dataset: str, cache_dir: Path) -> tuple[Path, Path, Path]:
    repo, corpus_rel, queries_rel, qrels_rel = coir_file_spec(dataset)
    root = cache_dir / "coir" / dataset
    root.mkdir(parents=True, exist_ok=True)
    corpus_path = root / "corpus.parquet"
    queries_path = root / "queries.parquet"
    qrels_path = root / "qrels.parquet"

    for target, relative in (
        (corpus_path, corpus_rel),
        (queries_path, queries_rel),
        (qrels_path, qrels_rel),
    ):
        if not target.exists():
            url = HF_RESOLVE.format(repo=repo, path=relative)
            print(f"[download] {url} -> {target}", file=sys.stderr)
            _download(url, target)
    return corpus_path, queries_path, qrels_path


def _read_parquet(path: Path):
    try:
        import pyarrow.parquet as parquet
    except ImportError as error:
        raise RuntimeError(
            "pyarrow is required for CoIR datasets; run with: uv run --extra eval python ..."
        ) from error
    return parquet.read_table(str(path))


def load_coir_dataset(corpus_path: Path, queries_path: Path, qrels_path: Path):
    corpus_rows = _read_parquet(corpus_path).to_pylist()
    query_rows = _read_parquet(queries_path).to_pylist()
    qrels_rows = _read_parquet(qrels_path).to_pylist()

    docs = [
        EvalDoc(
            doc_id=str(row["_id"]),
            title=str(row.get("title") or ""),
            text=str(row.get("text") or ""),
        )
        for row in corpus_rows
    ]
    queries = {
        str(row["_id"]): str(row.get("text") or "")
        for row in query_rows
    }
    qrels: dict[str, dict[str, float]] = {}
    for row in qrels_rows:
        score = float(row["score"])
        if score <= 0:
            continue
        qrels.setdefault(str(row["query-id"]), {})[str(row["corpus-id"])] = score
    return docs, queries, qrels


def load_dataset(dataset: str, cache_dir: Path):
    if dataset in BEIR_DATASETS:
        root = ensure_beir_dataset(dataset, cache_dir)
        return load_beir_corpus(root), load_beir_queries(root), load_beir_qrels(root)
    if dataset in COIR_DATASETS:
        corpus_path, queries_path, qrels_path = ensure_coir_dataset(dataset, cache_dir)
        return load_coir_dataset(corpus_path, queries_path, qrels_path)
    supported = sorted(BEIR_DATASETS | COIR_DATASETS)
    raise ValueError(f"unsupported dataset: {dataset}; choose one of {supported}")
if __name__ == "__main__":
    raise SystemExit(main())
