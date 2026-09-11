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
  uv run python bench/bench_public.py --dataset scifact --qrels-split train
  uv run python bench/bench_public.py --dataset nfcorpus --limit-queries 50
  uv run python bench/bench_public.py --lse-query-mode structured --lse-conjunction or
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import platform
import random
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bench.parallel import (  # noqa: E402
    DATASET_PLACEHOLDER,
    resolve_jobs,
    run_parallel,
    split_datasets,
)
from lse import __version__ as LSE_VERSION  # noqa: E402
from lse.config import DEFAULT_SEARCH_FIELDS  # noqa: E402
from lse.indexer import IndexEngine  # noqa: E402
from lse.options import DEFAULT_AUTO_STRUCTURED_MAX_TERMS, SearchOptions  # noqa: E402
from lse.searcher import SearchEngine  # noqa: E402

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


def _read_beir_qrels_file(path: Path) -> dict[str, dict[str, float]]:
    qrels: dict[str, dict[str, float]] = {}
    with path.open(encoding="utf-8", newline="") as handle:
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


def load_beir_qrels(root: Path, split: str = "test") -> dict[str, dict[str, float]]:
    """读取 BEIR qrels；支持 test / train / all 三个 split 视图。

    SciFact 的 ``qrels/train.tsv``（809 条）可作为 dev split 调参，
    ``qrels/test.tsv``（300 条）只用于最终报告。
    """
    if split == "all":
        merged: dict[str, dict[str, float]] = {}
        for name in ("train", "test"):
            path = root / "qrels" / f"{name}.tsv"
            if path.exists():
                for query_id, labels in _read_beir_qrels_file(path).items():
                    merged.setdefault(query_id, {}).update(labels)
        if not merged:
            raise FileNotFoundError(f"BEIR qrels not found under {root}")
        return merged

    candidates = [root / "qrels" / f"{split}.tsv"]
    if split == "test":
        # 兼容部分 BEIR 数据集只有 qrels/dev.tsv 的情况（旧行为）
        candidates.append(root / "qrels" / "dev.tsv")
    candidates.append(root / "qrels.tsv")
    qrels_path = next((path for path in candidates if path.exists()), None)
    if qrels_path is None:
        raise FileNotFoundError(f"qrels split '{split}' not found under {root}")
    return _read_beir_qrels_file(qrels_path)


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
    collect_per_query: bool = False,
) -> dict[str, Any]:
    ndcg_scores: list[float] = []
    recall_scores: list[float] = []
    mrr_scores: list[float] = []
    latencies_ms: list[float] = []
    per_query: dict[str, dict[str, float]] = {}

    started = time.perf_counter()
    for query_id, query_text in queries.items():
        relevant = qrels.get(query_id, {})
        if not query_text.strip() or not relevant:
            continue
        query_started = time.perf_counter()
        ranked = list(retriever.retrieve(query_text, top_k))
        latencies_ms.append((time.perf_counter() - query_started) * 1000.0)
        ndcg = ndcg_at_k(ranked, relevant, METRIC_K)
        recall = recall_at_k(ranked, relevant, METRIC_K)
        mrr = reciprocal_rank_at_k(ranked, relevant, METRIC_K)
        ndcg_scores.append(ndcg)
        recall_scores.append(recall)
        mrr_scores.append(mrr)
        if collect_per_query:
            per_query[query_id] = {"ndcg@10": ndcg, "recall@10": recall, "mrr@10": mrr}

    total_seconds = time.perf_counter() - started
    result: dict[str, Any] = {
        "queries": float(len(ndcg_scores)),
        "ndcg@10": sum(ndcg_scores) / len(ndcg_scores) if ndcg_scores else 0.0,
        "recall@10": sum(recall_scores) / len(recall_scores) if recall_scores else 0.0,
        "mrr@10": sum(mrr_scores) / len(mrr_scores) if mrr_scores else 0.0,
        "total_seconds": total_seconds,
        "p50_ms": sorted(latencies_ms)[len(latencies_ms) // 2] if latencies_ms else 0.0,
    }
    if collect_per_query:
        result["per_query"] = per_query
    return result


def paired_bootstrap(
    reference: dict[str, Any],
    baseline: dict[str, Any],
    metric: str = "ndcg@10",
    samples: int = 2000,
    seed: int = 42,
) -> dict[str, Any]:
    """对同一批 query 的指标差做 paired bootstrap，返回均值与 95% 置信区间。"""
    ref = reference.get("per_query") or {}
    base = baseline.get("per_query") or {}
    common_ids = sorted(set(ref) & set(base))
    if not common_ids:
        return {"queries": 0.0, "mean_diff": 0.0, "ci_low": 0.0, "ci_high": 0.0,
                "wins": 0, "losses": 0, "ties": 0, "samples": float(samples), "metric": metric}

    diffs = [float(ref[qid][metric]) - float(base[qid][metric]) for qid in common_ids]
    mean_diff = sum(diffs) / len(diffs)
    wins = sum(1 for value in diffs if value > 1e-12)
    losses = sum(1 for value in diffs if value < -1e-12)
    ties = len(diffs) - wins - losses

    rng = random.Random(seed)
    n = len(diffs)
    boot: list[float] = []
    for _ in range(max(int(samples), 1)):
        boot.append(sum(diffs[rng.randrange(n)] for _ in range(n)) / n)
    boot.sort()
    low_index = int(0.025 * (len(boot) - 1))
    high_index = int(0.975 * (len(boot) - 1))
    return {
        "queries": float(n),
        "mean_diff": mean_diff,
        "ci_low": boot[low_index],
        "ci_high": boot[high_index],
        "wins": wins,
        "losses": losses,
        "ties": ties,
        "samples": float(max(int(samples), 1)),
        "metric": metric,
    }


def aggregate_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """把同一配置的多次 benchmark 运行聚合成 mean ± std。"""
    if not runs:
        return {}
    if len(runs) == 1:
        return runs[0]

    metric_keys = [key for key in runs[0] if key != "per_query"]
    aggregated: dict[str, Any] = {
        key: sum(float(run[key]) for run in runs) / len(runs) for key in metric_keys
    }
    aggregated["runs"] = float(len(runs))
    aggregated["std"] = {
        key: statistics.pstdev([float(run[key]) for run in runs]) for key in metric_keys
    }

    per_query_runs = [run.get("per_query") for run in runs]
    if all(isinstance(item, dict) for item in per_query_runs):
        common_ids = set(per_query_runs[0])
        for item in per_query_runs[1:]:
            common_ids &= set(item)
        merged: dict[str, dict[str, float]] = {}
        for query_id in sorted(common_ids):
            metric_names = per_query_runs[0][query_id].keys()
            merged[query_id] = {
                name: sum(item[query_id][name] for item in per_query_runs) / len(per_query_runs)
                for name in metric_names
            }
        aggregated["per_query"] = merged
    return aggregated


class LseRetriever:
    name = "lse"

    def __init__(
        self,
        docs_dir: Path,
        name_to_id: dict[str, str],
        options: SearchOptions | None = None,
        deterministic: bool = False,
    ) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="lse-public-"))
        self._index_dir = self._tmp / "index"
        IndexEngine(self._index_dir, deterministic=deterministic).build([docs_dir])
        self._engine = SearchEngine(self._index_dir, options=options)
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

    def __init__(
        self,
        docs: Sequence[EvalDoc],
        name_to_id: dict[str, str],
        deterministic: bool = False,
    ) -> None:
        import tantivy

        self._tmp = Path(tempfile.mkdtemp(prefix="lse-tantivy-"))
        index_dir = self._tmp / "index"
        index_dir.mkdir(parents=True, exist_ok=True)
        builder = tantivy.SchemaBuilder()
        builder.add_text_field("doc_id", stored=True)
        builder.add_text_field("title", stored=False)
        builder.add_text_field("body", stored=False)
        self._index = tantivy.Index(builder.build(), str(index_dir))
        writer = (
            self._index.writer(num_threads=1)
            if deterministic
            else self._index.writer()
        )
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
            # 代码 query 含 Python/Java 语法时默认 query parser 会报 Syntax Error。
            # 为了不把 baseline 的“解析失败”误当成检索能力差距，先把代码标点
            # 归一化为空白再做原生 BM25 查询；自然语言查询仍走原始 parser。
            safe_query = _native_code_query_fallback(query)
            try:
                parsed = self._index.parse_query(safe_query, ["title", "body"])
            except Exception:
                parsed, _ = self._index.parse_query_lenient(safe_query, ["title", "body"])
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


def _native_code_query_fallback(query: str) -> str:
    """默认 parser 失败的代码 query 兜底：保留词字符，其余标点转空白。"""
    cleaned = re.sub(r"[^0-9A-Za-z_\s]+", " ", query)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or "*"


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


def build_retriever(
    name: str,
    docs,
    docs_dir: Path,
    name_to_id: dict[str, str],
    lse_options: SearchOptions | None = None,
    deterministic: bool = False,
):
    if name == "lse":
        return LseRetriever(
            docs_dir, name_to_id, options=lse_options, deterministic=deterministic
        )
    if name == "tantivy":
        return TantivyBm25Retriever(docs, name_to_id, deterministic=deterministic)
    if name == "ripgrep":
        return RipgrepCountRetriever(docs_dir, name_to_id)
    raise ValueError(f"unknown baseline: {name}")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Public retrieval benchmark for lse")
    parser.add_argument("--dataset", default="scifact", help="BEIR dataset name or CoIR name (e.g. cosqa, codesearchnet-python)")
    parser.add_argument(
        "--jobs",
        type=int,
        default=0,
        help="数据集级并行度；0=自动（min(数据集数, 4)）。--dataset 支持 a,b,c 逗号列表，需配合含 {dataset} 的 --output-json",
    )
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--baselines", default="lse,tantivy,ripgrep")
    parser.add_argument("--top-k", type=int, default=100)
    parser.add_argument("--limit-queries", type=int, default=0)
    parser.add_argument(
        "--sample-docs",
        type=int,
        default=0,
        help="CoIR 固定种子采样文档数；0 表示全量（CodeSearchNet 建议 20000）",
    )
    parser.add_argument(
        "--sample-queries",
        type=int,
        default=0,
        help="CoIR 固定种子采样 query 数；0 表示全量（CodeSearchNet 建议 2000）",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="采样与 paired bootstrap 的随机种子（默认 42）",
    )
    parser.add_argument(
        "--qrels-split",
        default="test",
        choices=("test", "valid", "train", "all"),
        help="BEIR: test/train/all；CoIR: test/valid/train/all。dev 调参用 train/valid，最终报告用 test。",
    )
    parser.add_argument("--repeat", type=int, default=1, help="重复评测次数，>1 时报告 mean ± std")
    parser.add_argument(
        "--deterministic-index",
        action="store_true",
        help="索引写入固定单线程，降低 segment 布局 / 并列排序造成的运行间波动",
    )
    parser.add_argument(
        "--bootstrap-samples",
        type=int,
        default=2000,
        help="lse vs 各 baseline 的 paired bootstrap 重采样次数；0 关闭",
    )
    parser.add_argument(
        "--bootstrap-metric",
        choices=("ndcg@10", "recall@10", "mrr@10"),
        default="ndcg@10",
        help="paired bootstrap 使用的指标",
    )
    parser.add_argument(
        "--include-per-query",
        action="store_true",
        help="在 output JSON 中保存每个 query 的指标；默认只存聚合值与显著性",
    )
    parser.add_argument("--output-json", type=Path, default=None)

    lse_group = parser.add_argument_group("lse query options")
    lse_group.add_argument(
        "--lse-query-mode",
        choices=("auto", "natural", "structured"),
        default="auto",
        help="auto: 短关键词 AND / 长句加权 OR；natural: 强制自然 OR；structured: 旧 AST + 默认 AND。",
    )
    lse_group.add_argument(
        "--lse-auto-max-terms",
        type=int,
        default=DEFAULT_AUTO_STRUCTURED_MAX_TERMS,
        help="auto 模式下走结构化 AND 的内容词元上限；0 表示纯词项查询一律走自然 OR（当前默认）",
    )
    lse_group.add_argument("--lse-idf-power", type=float, default=0.25, help="自然查询词项 IDF 权重指数（默认 0.25）")
    lse_group.add_argument(
        "--lse-idf-long",
        type=float,
        default=None,
        help="长 query 使用的 IDF 幂次；默认关闭长度分段（实验开关，见 PUBLIC_EVAL §2.5）",
    )
    lse_group.add_argument(
        "--lse-idf-long-chars",
        type=int,
        default=160,
        help="触发 --lse-idf-long 的 query 字符数下限（严格大于）",
    )
    lse_group.add_argument("--lse-no-idf", action="store_true", help="关闭自然查询中的 IDF 词项加权")
    lse_group.add_argument(
        "--lse-concept-expansion",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="是否在自然查询中追加概念图谱同义词（默认开启）",
    )
    lse_group.add_argument("--lse-fields", default="", help="逗号分隔的默认搜索字段，默认 content,filename,path")
    lse_group.add_argument(
        "--lse-conjunction",
        choices=("and", "or"),
        default="and",
        help="structured 模式的 conjunction_by_default（默认 and）",
    )
    lse_group.add_argument(
        "--lse-rank-only",
        action="store_true",
        help="lse 只执行 compile + parse + rank，不读取正文 / 不计算 evidence span",
    )
    return parser.parse_args(argv)


def search_options_from_args(args: argparse.Namespace) -> SearchOptions:
    fields = tuple(field.strip() for field in args.lse_fields.split(",") if field.strip())
    return SearchOptions(
        query_mode=args.lse_query_mode,
        idf_power=None if args.lse_no_idf else args.lse_idf_power,
        idf_power_long=args.lse_idf_long,
        idf_power_long_chars=args.lse_idf_long_chars,
        auto_structured_max_terms=args.lse_auto_max_terms,
        concept_expansion=args.lse_concept_expansion,
        query_fields=fields or DEFAULT_SEARCH_FIELDS,
        conjunction_by_default=args.lse_conjunction == "and",
        include_spans=not args.lse_rank_only,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    raw_argv = list(argv) if argv is not None else sys.argv[1:]
    datasets = split_datasets(args.dataset)
    if len(datasets) > 1:
        if args.output_json is not None and DATASET_PLACEHOLDER not in str(args.output_json):
            print(
                f"multi-dataset mode requires --output-json containing {DATASET_PLACEHOLDER}",
                file=sys.stderr,
            )
            return 2
        print(f"datasets={','.join(datasets)} jobs={resolve_jobs(args.jobs, datasets)}")
        return run_parallel(Path(__file__), raw_argv, datasets, args.jobs)

    lse_options = search_options_from_args(args)
    repeat = max(args.repeat, 1)
    try:
        docs, queries, qrels = load_dataset(
            args.dataset,
            args.cache_dir,
            args.qrels_split,
            sample_docs=max(args.sample_docs, 0),
            sample_queries=max(args.sample_queries, 0),
            seed=args.seed,
        )
    except (FileNotFoundError, RuntimeError, ValueError, OSError) as error:
        print(f"dataset error: {error}", file=sys.stderr)
        return 2

    query_ids = [query_id for query_id in queries if qrels.get(query_id)]
    if args.limit_queries > 0:
        query_ids = query_ids[: args.limit_queries]
    selected_queries = {query_id: queries[query_id] for query_id in query_ids}

    print(f"dataset={args.dataset} split={args.qrels_split} docs={len(docs)} "
          f"queries={len(selected_queries)} qrels_queries={len(qrels)} "
          f"top_k={args.top_k} repeat={repeat}")
    if args.sample_docs > 0 or args.sample_queries > 0:
        print(
            f"sampling seed={args.seed} requested_docs={args.sample_docs} "
            f"requested_queries={args.sample_queries}"
        )

    retriever_names = [name.strip() for name in args.baselines.split(",") if name.strip()]
    runs: dict[str, list[dict[str, Any]]] = {}
    with tempfile.TemporaryDirectory(prefix=f"lse-bench-{args.dataset}-") as tmp:
        workdir = Path(tmp)
        docs_dir, name_to_id = materialize_docs(docs, workdir)
        for repetition in range(repeat):
            for name in retriever_names:
                label = name if repeat == 1 else f"{name} ({repetition + 1}/{repeat})"
                print(f"running baseline={label} ...", file=sys.stderr)
                retriever = build_retriever(
                    name,
                    docs,
                    docs_dir,
                    name_to_id,
                    lse_options,
                    deterministic=args.deterministic_index,
                )
                try:
                    metrics = evaluate_retriever(
                        retriever,
                        selected_queries,
                        qrels,
                        args.top_k,
                        collect_per_query=True,
                    )
                finally:
                    retriever.close()
                runs.setdefault(name, []).append(metrics)

    results: dict[str, dict[str, Any]] = {
        name: aggregate_runs(name_runs) for name, name_runs in runs.items()
    }

    significance: dict[str, dict[str, Any]] = {}
    if "lse" in results and args.bootstrap_samples > 0:
        for name in retriever_names:
            if name == "lse" or name not in results:
                continue
            significance[f"lse_vs_{name}"] = paired_bootstrap(
                results["lse"],
                results[name],
                metric=args.bootstrap_metric,
                samples=args.bootstrap_samples,
                seed=args.seed,
            )

    print("")
    print(f"{'baseline':<16} {'nDCG@10':>10} {'Recall@10':>10} {'MRR@10':>10} {'p50 ms':>10} {'total s':>10}")
    print("-" * 72)
    for name, metrics in results.items():
        print(f"{name:<16} {metrics['ndcg@10']:>10.4f} {metrics['recall@10']:>10.4f} "
              f"{metrics['mrr@10']:>10.4f} {metrics['p50_ms']:>10.2f} "
              f"{metrics['total_seconds']:>10.2f}")

    if significance:
        print("")
        print(f"paired bootstrap ({args.bootstrap_metric}, {args.bootstrap_samples} samples):")
        for key, stats in significance.items():
            print(
                f"{key:<24} mean_diff={stats['mean_diff']:+.4f} "
                f"95%CI=[{stats['ci_low']:+.4f}, {stats['ci_high']:+.4f}] "
                f"W/L/T={stats['wins']}/{stats['losses']}/{stats['ties']}"
            )

    public_results = {
        name: {key: value for key, value in metrics.items() if key != "per_query"}
        for name, metrics in results.items()
    }
    if args.include_per_query:
        public_results = results

    payload = {
        "dataset": args.dataset,
        "qrels_split": args.qrels_split,
        "docs": len(docs),
        "queries": len(selected_queries),
        "top_k": args.top_k,
        "repeat": repeat,
        "deterministic_index": bool(args.deterministic_index),
        "sampling": {
            "requested_docs": max(args.sample_docs, 0),
            "requested_queries": max(args.sample_queries, 0),
            "seed": args.seed,
        },
        "lse_options": {
            "query_mode": lse_options.query_mode,
            "natural_query": lse_options.natural_query,
            "auto_structured_max_terms": lse_options.auto_structured_max_terms,
            "idf_power": lse_options.idf_power,
            "idf_power_long": lse_options.idf_power_long,
            "idf_power_long_chars": lse_options.idf_power_long_chars,
            "concept_expansion": lse_options.concept_expansion,
            "query_fields": list(lse_options.query_fields),
            "conjunction_by_default": lse_options.conjunction_by_default,
            "include_spans": lse_options.include_spans,
            "rank_only": not lse_options.include_spans,
        },
        "meta": {
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "lse_version": LSE_VERSION,
            "command": " ".join(sys.argv),
        },
        "significance": significance,
        "results": public_results,
    }
    if args.output_json is not None:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nwrote {args.output_json}")
    return 0


def coir_file_spec(dataset: str, split: str = "test") -> tuple[str, str, str, str]:
    """返回 CoIR 数据集的 HF 仓库内相对路径。

    ``split`` 支持 test / valid / train；默认 test 以保持既有调用兼容。
    """
    if dataset in COIR_SIMPLE_DATASETS:
        repo = f"CoIR-Retrieval/{COIR_SIMPLE_DATASETS[dataset]}"
        return (
            repo,
            "corpus/corpus-00000-of-00001.parquet",
            "queries/queries-00000-of-00001.parquet",
            f"data/{split}-00000-of-00001.parquet",
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
            f"{prefix}qrels/{split}-00000-of-00001.parquet",
        )
    raise ValueError(f"unknown CoIR dataset: {dataset}")


def ensure_coir_dataset(dataset: str, cache_dir: Path, split: str = "test") -> tuple[Path, Path, Path]:
    repo, corpus_rel, queries_rel, qrels_rel = coir_file_spec(dataset, split)
    root = cache_dir / "coir" / dataset
    root.mkdir(parents=True, exist_ok=True)
    corpus_path = root / "corpus.parquet"
    queries_path = root / "queries.parquet"
    qrels_name = "qrels.parquet" if split == "test" else f"qrels-{split}.parquet"
    qrels_path = root / qrels_name

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


def _parquet_file(path: Path):
    try:
        import pyarrow.parquet as parquet
    except ImportError as error:
        raise RuntimeError(
            "pyarrow is required for CoIR datasets; run with: uv run --extra eval python ..."
        ) from error
    return parquet.ParquetFile(str(path))


def _iter_parquet_batches(path: Path, batch_size: int = 5000):
    """流式迭代 parquet batch，避免把 280k 文档一次性拉进内存。"""
    yield from _parquet_file(path).iter_batches(batch_size=batch_size)


def _read_parquet(path: Path):
    return _parquet_file(path).read()


def _read_coir_qrels(qrels_path: Path) -> dict[str, dict[str, float]]:
    qrels: dict[str, dict[str, float]] = {}
    for row in _read_parquet(qrels_path).to_pylist():
        score = float(row["score"])
        if score <= 0:
            continue
        qrels.setdefault(str(row["query-id"]), {})[str(row["corpus-id"])] = score
    return qrels


def select_sampled_query_ids(
    qrels: dict[str, dict[str, float]], sample_queries: int, seed: int
) -> list[str]:
    """按固定种子从 qrels 中选择 query，并返回稳定排序后的 id 列表。"""
    query_ids = sorted(qrels)
    if sample_queries <= 0 or sample_queries >= len(query_ids):
        return query_ids
    rng = random.Random(seed)
    return sorted(rng.sample(query_ids, sample_queries))


def _sample_relevant_doc_ids(
    qrels: dict[str, dict[str, float]], query_ids: Sequence[str]
) -> set[str]:
    relevant: set[str] = set()
    for query_id in query_ids:
        relevant.update(qrels.get(query_id, {}))
    return relevant


def sample_coir_docs(
    corpus_path: Path,
    relevant_ids: set[str],
    sample_docs: int,
    seed: int,
    batch_size: int = 5000,
) -> list[EvalDoc]:
    """流式扫描 corpus：保留全部相关文档，再 reservoir 抽样 negative 文档。

    保留相关文档是采样质量的关键：如果完全随机抽 20k 文档，会有部分
    qrels 正例不在样本中，从而低估所有 baseline。输出按 corpus 原始顺序
    排列，保证索引构建与并列排序可复现。
    """
    if sample_docs <= 0:
        raise ValueError("--sample-docs 必须大于 0 才能启用流式 CoIR 采样")
    if len(relevant_ids) > sample_docs:
        raise ValueError(
            f"sample-docs={sample_docs} 小于选中 query 的相关文档数 "
            f"{len(relevant_ids)}，无法保留全部正例"
        )

    negative_target = sample_docs - len(relevant_ids)
    rng = random.Random(seed)
    collected: dict[int, EvalDoc] = {}
    reservoir: list[tuple[int, EvalDoc]] = []
    missing_relevant = set(relevant_ids)
    negative_seen = 0
    position = 0

    for batch in _iter_parquet_batches(corpus_path, batch_size):
        for row in batch.to_pylist():
            doc_id = str(row.get("_id", ""))
            if not doc_id:
                position += 1
                continue
            doc = EvalDoc(
                doc_id=doc_id,
                title=str(row.get("title") or ""),
                text=str(row.get("text") or ""),
            )
            if doc_id in relevant_ids:
                collected[position] = doc
                missing_relevant.discard(doc_id)
            elif negative_target > 0:
                negative_seen += 1
                if len(reservoir) < negative_target:
                    reservoir.append((position, doc))
                else:
                    swap_index = rng.randrange(negative_seen)
                    if swap_index < negative_target:
                        reservoir[swap_index] = (position, doc)
            position += 1

    if missing_relevant:
        preview = ", ".join(sorted(missing_relevant)[:5])
        raise ValueError(f"{len(missing_relevant)} 个相关文档不在 corpus 中: {preview}")

    collected.update(reservoir)
    return [doc for _position, doc in sorted(collected.items())]


def load_coir_sampled_queries(
    queries_path: Path,
    query_ids: Sequence[str],
    batch_size: int = 5000,
) -> dict[str, str]:
    """流式扫描 queries parquet，只保留选中 qid 的查询文本。"""
    selected = set(query_ids)
    loaded: dict[str, str] = {}
    for batch in _iter_parquet_batches(queries_path, batch_size):
        for row in batch.to_pylist():
            query_id = str(row.get("_id", ""))
            if query_id in selected:
                loaded[query_id] = str(row.get("text") or "")
    missing = selected - set(loaded)
    if missing:
        preview = ", ".join(sorted(missing)[:5])
        raise ValueError(f"{len(missing)} 个选中 query 不在 queries parquet 中: {preview}")
    return {query_id: loaded[query_id] for query_id in query_ids}


def load_coir_dataset(
    corpus_path: Path,
    queries_path: Path,
    qrels_path: Path,
    extra_qrels_paths: Sequence[Path] = (),
    sample_docs: int = 0,
    sample_queries: int = 0,
    seed: int = 42,
):
    qrels: dict[str, dict[str, float]] = {}
    for path in (qrels_path, *extra_qrels_paths):
        for query_id, labels in _read_coir_qrels(path).items():
            qrels.setdefault(query_id, {}).update(labels)

    if sample_docs <= 0 and sample_queries <= 0:
        corpus_rows = _read_parquet(corpus_path).to_pylist()
        query_rows = _read_parquet(queries_path).to_pylist()
        docs = [
            EvalDoc(
                doc_id=str(row["_id"]),
                title=str(row.get("title") or ""),
                text=str(row.get("text") or ""),
            )
            for row in corpus_rows
        ]
        queries = {str(row["_id"]): str(row.get("text") or "") for row in query_rows}
        return docs, queries, qrels

    if sample_docs <= 0:
        raise ValueError(
            "CoIR 采样需要同时指定 --sample-docs > 0；"
            "仅采样 query 仍需全量 corpus，会放大内存与小文件开销"
        )

    selected_query_ids = select_sampled_query_ids(qrels, sample_queries, seed)
    if not selected_query_ids:
        raise ValueError(f"qrels 为空，无法采样: {qrels_path}")
    relevant_ids = _sample_relevant_doc_ids(qrels, selected_query_ids)
    docs = sample_coir_docs(corpus_path, relevant_ids, sample_docs, seed)
    queries = load_coir_sampled_queries(queries_path, selected_query_ids)
    sampled_qrels = {query_id: qrels[query_id] for query_id in selected_query_ids}
    return docs, queries, sampled_qrels


def load_dataset(
    dataset: str,
    cache_dir: Path,
    qrels_split: str = "test",
    sample_docs: int = 0,
    sample_queries: int = 0,
    seed: int = 42,
):
    if dataset in BEIR_DATASETS:
        if sample_docs > 0 or sample_queries > 0:
            raise ValueError("固定种子采样目前只支持 CoIR 数据集（含 CodeSearchNet）")
        root = ensure_beir_dataset(dataset, cache_dir)
        return load_beir_corpus(root), load_beir_queries(root), load_beir_qrels(root, qrels_split)
    if dataset in COIR_DATASETS:
        corpus_path, queries_path, _ = ensure_coir_dataset(dataset, cache_dir, "test")
        if qrels_split == "all":
            qrels_paths = [
                ensure_coir_dataset(dataset, cache_dir, split)[2]
                for split in ("test", "valid", "train")
            ]
            return load_coir_dataset(
                corpus_path,
                queries_path,
                qrels_paths[0],
                qrels_paths[1:],
                sample_docs=sample_docs,
                sample_queries=sample_queries,
                seed=seed,
            )
        _, _, qrels_path = ensure_coir_dataset(dataset, cache_dir, qrels_split)
        return load_coir_dataset(
            corpus_path,
            queries_path,
            qrels_path,
            sample_docs=sample_docs,
            sample_queries=sample_queries,
            seed=seed,
        )
    supported = sorted(BEIR_DATASETS | COIR_DATASETS)
    raise ValueError(f"unsupported dataset: {dataset}; choose one of {supported}")
if __name__ == "__main__":
    raise SystemExit(main())
