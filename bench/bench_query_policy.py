"""Query profile / auto-AND policy sweep on public dev splits.

与 ``bench_ablation.py`` 的区别：这里的每个策略只改 ``SearchOptions``，索引与
文档目录只构建一次，因此可以在一轮里扫过完整的 auto 阈值网格。

- BEIR / SciFact：``qrels/train.tsv``（810 条）为 dev
- BEIR / NFCorpus：``qrels/train.tsv``（2591 条）为 dev
- BEIR / FiQA：``qrels/train.tsv``（5501 条）为 dev
- CoIR / CosQA：``data/valid``（500 条）为 dev

示例：
    uv run --extra eval python bench/bench_query_policy.py --dataset nfcorpus
    uv run --extra eval python bench/bench_query_policy.py --dataset scifact --include-tantivy
"""

from __future__ import annotations

import argparse
import json
import platform
import random
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bench.bench_public import (  # noqa: E402
    BEIR_DATASETS,
    COIR_DATASETS,
    DEFAULT_CACHE,
    TantivyBm25Retriever,
    evaluate_retriever,
    load_dataset,
    materialize_docs,
    paired_bootstrap,
)
from bench.parallel import (  # noqa: E402
    DATASET_PLACEHOLDER,
    resolve_jobs,
    run_parallel,
    split_datasets,
)
from lse import __version__ as LSE_VERSION  # noqa: E402
from lse.concepts import load_project_concepts  # noqa: E402
from lse.indexer import IndexEngine  # noqa: E402
from lse.options import DEFAULT_AUTO_STRUCTURED_MAX_TERMS, SearchOptions  # noqa: E402
from lse.query_ast import QueryCompiler  # noqa: E402
from lse.searcher import _NATURAL_CONNECTIVES, SearchEngine, _looks_like_code_query  # noqa: E402

AUTO_THRESHOLD_GRID = (0, 1, 2, 3, 4, 5, 6, 8, 12)

#: gap 诊断：固定 natural 路径，只切换 IDF 权重 / 概念展开 / 查询字段，
#: 用来解释 FiQA、Arguana 上相对原生 BM25 的残余负 gap 来自哪里。
GAP_VARIANTS: dict[str, dict[str, Any]] = {
    "natural": {},
    "natural_no_idf": {"idf_power": None},
    "natural_idf050": {"idf_power": 0.5},
    "natural_idf100": {"idf_power": 1.0},
    "natural_noconcept": {"concept_expansion": False},
    "natural_content_only": {"query_fields": ("content",)},
    "natural_idf100_noconcept": {"idf_power": 1.0, "concept_expansion": False},
    "natural_idf100_content": {"idf_power": 1.0, "query_fields": ("content",)},
}

#: 长度分段 IDF：query 字符数超过阈值时改用候选幂次，阈值以下保持 0.25。
#: 用于验证 §2.4 诊断出的“长 query 需要更高 IDF 幂次”是否可做成 profile。
LENGTH_RULE_VARIANTS: dict[str, dict[str, Any]] = {
    "natural": {},
    "natural_idf100": {"idf_power": 1.0},
    "len100_idf050": {"idf_power_long": 0.5, "idf_power_long_chars": 100},
    "len100_idf100": {"idf_power_long": 1.0, "idf_power_long_chars": 100},
    "len160_idf050": {"idf_power_long": 0.5, "idf_power_long_chars": 160},
    "len160_idf100": {"idf_power_long": 1.0, "idf_power_long_chars": 160},
    "len240_idf050": {"idf_power_long": 0.5, "idf_power_long_chars": 240},
    "len240_idf100": {"idf_power_long": 1.0, "idf_power_long_chars": 240},
}


def build_policies(suite: str = "auto") -> dict[str, SearchOptions]:
    """策略集合：``auto`` 连接语义网格，``gap`` 打分旋钮，``length`` 长度分段 IDF。"""
    if suite == "gap":
        return {
            name: SearchOptions(query_mode="natural", include_spans=False, **kwargs)
            for name, kwargs in GAP_VARIANTS.items()
        }
    if suite == "length":
        return {
            name: SearchOptions(query_mode="natural", include_spans=False, **kwargs)
            for name, kwargs in LENGTH_RULE_VARIANTS.items()
        }
    policies: dict[str, SearchOptions] = {
        "structured_and": SearchOptions(natural_query=False, include_spans=False),
        "structured_or": SearchOptions(
            natural_query=False, conjunction_by_default=False, include_spans=False
        ),
        "natural": SearchOptions(query_mode="natural", include_spans=False),
    }
    for threshold in AUTO_THRESHOLD_GRID:
        policies[f"auto@{threshold}"] = SearchOptions(
            auto_structured_max_terms=threshold, include_spans=False
        )
    return policies


class EngineRetriever:
    """在同一个已建好的索引 / SearchEngine 上按策略检索。"""

    name = "lse"

    def __init__(self, engine: SearchEngine, name_to_id: dict[str, str], options: SearchOptions) -> None:
        self._engine = engine
        self._name_to_id = name_to_id
        self._options = options

    def retrieve(self, query: str, top_k: int) -> list[str]:
        result = self._engine.search(query, limit=top_k, options=self._options)
        ranked: list[str] = []
        for hit in result.hits:
            doc_id = self._name_to_id.get(Path(hit.path).name)
            if doc_id is not None:
                ranked.append(doc_id)
        return ranked

    def close(self) -> None:
        return None


def query_features(query: str, concept_map: dict[str, list[str]]) -> dict[str, Any]:
    """记录 query profile 特征，用于解释阈值扫描结果。"""
    compiler = QueryCompiler(query, concept_map=concept_map, expand_concepts=True)
    plain_terms = compiler.plain_terms()
    if plain_terms is None:
        return {
            "kind": "structured",
            "content_terms": -1,
            "chars": len(query),
            "code_like": False,
        }
    content_terms = [t for t in plain_terms if t.lower() not in _NATURAL_CONNECTIVES]
    return {
        "kind": "code" if _looks_like_code_query(query) else "plain",
        "content_terms": len(content_terms),
        "chars": len(query),
        "code_like": _looks_like_code_query(query),
    }


def _bucket_label(content_terms: int) -> str:
    if content_terms < 0:
        return "structured"
    if content_terms >= 6:
        return "6+"
    return str(content_terms)


#: 查询长度分桶（字符数），用于检查残余 gap 是否集中在长 / 多主题 query。
LENGTH_BUCKETS: tuple[tuple[int | None, str], ...] = (
    (20, "<=20"),
    (40, "21-40"),
    (80, "41-80"),
    (160, "81-160"),
    (None, ">160"),
)


def _length_label(chars: int) -> str:
    for limit, label in LENGTH_BUCKETS:
        if limit is None or chars <= limit:
            return label
    return ">160"


def bucket_analysis(
    results: dict[str, dict[str, Any]],
    features: dict[str, dict[str, Any]],
    policy_a: str,
    policy_b: str,
    metric: str = "ndcg@10",
    key: str = "content_terms",
) -> list[dict[str, Any]]:
    """按 ``key`` 分桶比较两个策略（内容词元数或 query 字符长度）。"""
    per_query_a = results[policy_a]["per_query"]
    per_query_b = results[policy_b]["per_query"]
    buckets: dict[str, dict[str, float]] = {}
    for query_id, feature in features.items():
        if query_id not in per_query_a or query_id not in per_query_b:
            continue
        if key == "chars":
            label = _length_label(int(feature["chars"]))
        else:
            label = _bucket_label(int(feature["content_terms"]))
        bucket = buckets.setdefault(label, {"n": 0.0, "a": 0.0, "b": 0.0, "a_win": 0.0})
        value_a = float(per_query_a[query_id][metric])
        value_b = float(per_query_b[query_id][metric])
        bucket["n"] += 1
        bucket["a"] += value_a
        bucket["b"] += value_b
        bucket["a_win"] += 1.0 if value_a > value_b else 0.0

    if key == "chars":
        order = [label for _, label in LENGTH_BUCKETS]
    else:
        order = [str(index) for index in range(0, 6)] + ["6+", "structured"]
    rows: list[dict[str, Any]] = []
    for label in order:
        bucket = buckets.get(label)
        if not bucket or bucket["n"] == 0:
            continue
        n = bucket["n"]
        rows.append(
            {
                "key": key,
                "bucket": label,
                "queries": int(n),
                f"{policy_a}": bucket["a"] / n,
                f"{policy_b}": bucket["b"] / n,
                "delta": (bucket["a"] - bucket["b"]) / n,
                "a_win_rate": bucket["a_win"] / n,
            }
        )
    return rows


def print_bucket_table(rows: list[dict[str, Any]], policy_a: str, policy_b: str) -> None:
    if not rows:
        return
    width = max(len(str(row["bucket"])) for row in rows) + 2
    print("")
    print(f"{'bucket':<{width}} {'queries':>8} {policy_a:>14} {policy_b:>14} {'delta':>9} {'a_win':>7}")
    print("-" * (width + 56))
    for row in rows:
        print(
            f"{row['bucket']:<{width}} {row['queries']:>8} {row[policy_a]:>14.4f} "
            f"{row[policy_b]:>14.4f} {row['delta']:>+9.4f} {row['a_win_rate']:>7.3f}"
        )


def default_dev_split(dataset: str) -> str:
    return "train" if dataset in BEIR_DATASETS else "valid"


def select_query_subset(query_ids: list[str], subset: str, seed: int = 42) -> list[str]:
    """按固定种子把 query 固定切成两半（``a`` / ``b``）；``all`` 原样返回。

    A/B 协议：在 A 半上选规则，在从未参与选择的 B 半上报告。切分只依赖
    query id 排序 + 固定种子，因此可复现且与策略无关。
    """
    if subset == "all":
        return list(query_ids)
    ordered = sorted(query_ids)
    random.Random(seed).shuffle(ordered)
    half = len(ordered) // 2
    chosen = set(ordered[:half] if subset == "a" else ordered[half:])
    return [query_id for query_id in query_ids if query_id in chosen]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="lse query policy sweep on public dev splits")
    parser.add_argument("--dataset", default="scifact")
    parser.add_argument(
        "--suite",
        choices=("auto", "gap", "length"),
        default="auto",
        help="auto: 连接语义阈值网格；gap: 残余负 gap 诊断；length: 长度分段 IDF 规则",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=0,
        help="数据集级并行度；0=自动（min(数据集数, 4)）。--dataset 支持 a,b,c 逗号列表",
    )
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--qrels-split", default="", help="默认 BEIR=train / CoIR=valid")
    parser.add_argument("--top-k", type=int, default=100)
    parser.add_argument("--limit-queries", type=int, default=0)
    parser.add_argument(
        "--query-subset",
        choices=("all", "a", "b"),
        default="all",
        help="按 --subset-seed 把 query 固定切成两半，用于 A/B 协议（A 选规则 / B 报告）",
    )
    parser.add_argument("--subset-seed", type=int, default=42)
    parser.add_argument("--policies", default="", help="逗号分隔策略名，默认全部")
    parser.add_argument("--include-tantivy", action="store_true", help="同时运行原生 BM25 参考线")
    parser.add_argument(
        "--include-per-query",
        action="store_true",
        help="在 JSON 中保存每个 query 的指标与 profile（默认只存聚合值、显著性与分桶）",
    )
    parser.add_argument("--bootstrap-samples", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--deterministic-index", action="store_true")
    parser.add_argument("--output-json", type=Path, default=None)
    return parser.parse_args(argv)


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

    split = args.qrels_split or default_dev_split(args.dataset)
    if args.dataset not in BEIR_DATASETS and args.dataset not in COIR_DATASETS:
        print(f"unsupported dataset: {args.dataset}", file=sys.stderr)
        return 2

    timings: dict[str, float] = {}
    started = time.perf_counter()
    try:
        docs, queries, qrels = load_dataset(args.dataset, args.cache_dir, split)
    except (FileNotFoundError, RuntimeError, ValueError, OSError) as error:
        print(f"dataset error: {error}", file=sys.stderr)
        return 2
    timings["dataset_load_s"] = time.perf_counter() - started

    query_ids = [query_id for query_id in queries if qrels.get(query_id)]
    if args.limit_queries > 0:
        query_ids = query_ids[: args.limit_queries]
    query_ids = select_query_subset(query_ids, args.query_subset, args.subset_seed)
    selected_queries = {query_id: queries[query_id] for query_id in query_ids}

    policies = build_policies(args.suite)
    names = [name.strip() for name in args.policies.split(",") if name.strip()] or list(policies)
    unknown = [name for name in names if name not in policies]
    if unknown:
        print(f"unknown policies: {unknown}", file=sys.stderr)
        return 2

    print(
        f"dataset={args.dataset} split={split} subset={args.query_subset} docs={len(docs)} "
        f"queries={len(selected_queries)} "
        f"qrels_queries={len(qrels)} top_k={args.top_k} policies={len(names)}"
    )

    results: dict[str, dict[str, Any]] = {}
    features: dict[str, dict[str, Any]] = {}
    with tempfile.TemporaryDirectory(prefix=f"lse-policy-{args.dataset}-") as tmp:
        workdir = Path(tmp)
        mark = time.perf_counter()
        docs_dir, name_to_id = materialize_docs(docs, workdir)
        timings["materialize_s"] = time.perf_counter() - mark

        mark = time.perf_counter()
        index_dir = workdir / "index"
        IndexEngine(index_dir, deterministic=args.deterministic_index).build([docs_dir])
        timings["index_build_s"] = time.perf_counter() - mark

        mark = time.perf_counter()
        engine = SearchEngine(index_dir)
        concept_map = load_project_concepts(index_dir)
        for query_id, query_text in selected_queries.items():
            features[query_id] = query_features(query_text, concept_map)
        timings["feature_extract_s"] = time.perf_counter() - mark
        timings["policy_eval_s"] = 0.0

        if args.include_tantivy:
            print("running baseline=tantivy ...", file=sys.stderr)
            retriever = TantivyBm25Retriever(
                docs, name_to_id, deterministic=args.deterministic_index
            )
            try:
                results["tantivy_bm25"] = evaluate_retriever(
                    retriever, selected_queries, qrels, args.top_k, collect_per_query=True
                )
            finally:
                retriever.close()

        for name in names:
            print(f"running policy={name} ...", file=sys.stderr)
            retriever = EngineRetriever(engine, name_to_id, policies[name])
            results[name] = evaluate_retriever(
                retriever, selected_queries, qrels, args.top_k, collect_per_query=True
            )
            timings["policy_eval_s"] += float(results[name]["total_seconds"])

    significance = {}
    for name in names:
        if name == "natural":
            continue
        significance[f"{name}_vs_natural"] = paired_bootstrap(
            results[name], results["natural"], samples=args.bootstrap_samples, seed=args.seed
        )

    timings["total_s"] = time.perf_counter() - started
    print(
        "timings: "
        + " ".join(f"{key}={value:.2f}s" for key, value in timings.items())
    )

    header = f"{'policy':<18} {'nDCG@10':>10} {'Recall@10':>10} {'MRR@10':>10} {'p50 ms':>10} {'total s':>10}"
    print("")
    print(header)
    print("-" * len(header))
    for name, metrics in results.items():
        print(
            f"{name:<18} {metrics['ndcg@10']:>10.4f} {metrics['recall@10']:>10.4f} "
            f"{metrics['mrr@10']:>10.4f} {metrics['p50_ms']:>10.2f} "
            f"{metrics['total_seconds']:>10.2f}"
        )

    print("")
    print(f"paired bootstrap vs natural (ndcg@10, {args.bootstrap_samples} samples):")
    for key, stats in significance.items():
        print(
            f"{key:<32} mean_diff={stats['mean_diff']:+.4f} "
            f"95%CI=[{stats['ci_low']:+.4f}, {stats['ci_high']:+.4f}] "
            f"W/L/T={stats['wins']}/{stats['losses']}/{stats['ties']}"
        )

    bucket_reference = "structured_and" if "structured_and" in results else None
    if bucket_reference is None and "tantivy_bm25" in results:
        bucket_reference = "tantivy_bm25"
    buckets = (
        bucket_analysis(results, features, "natural", bucket_reference)
        if bucket_reference
        else []
    )
    length_buckets = (
        bucket_analysis(results, features, "natural", bucket_reference, key="chars")
        if bucket_reference
        else []
    )
    if buckets:
        print_bucket_table(buckets, "natural", bucket_reference)
    if length_buckets:
        print_bucket_table(length_buckets, "natural", bucket_reference)

    public_results: dict[str, dict[str, Any]] = {}
    for name, metrics in results.items():
        public_results[name] = (
            metrics
            if args.include_per_query
            else {key: value for key, value in metrics.items() if key != "per_query"}
        )
    query_kinds: dict[str, int] = {}
    for feature in features.values():
        kind = str(feature["kind"])
        query_kinds[kind] = query_kinds.get(kind, 0) + 1

    payload = {
        "dataset": args.dataset,
        "qrels_split": split,
        "suite": args.suite,
        "query_subset": args.query_subset,
        "subset_seed": args.subset_seed,
        "docs": len(docs),
        "queries": len(selected_queries),
        "top_k": args.top_k,
        "deterministic_index": bool(args.deterministic_index),
        "auto_structured_max_terms_default": DEFAULT_AUTO_STRUCTURED_MAX_TERMS,
        "query_kinds": query_kinds,
        "policies": {
            name: {
                "query_mode": options.query_mode,
                "natural_query": options.natural_query,
                "auto_structured_max_terms": options.auto_structured_max_terms,
                "idf_power": options.idf_power,
                "idf_power_long": options.idf_power_long,
                "idf_power_long_chars": options.idf_power_long_chars,
                "concept_expansion": options.concept_expansion,
                "conjunction_by_default": options.conjunction_by_default,
                "rank_only": not options.include_spans,
            }
            for name, options in policies.items()
            if name in names
        },
        "meta": {
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "lse_version": LSE_VERSION,
            "command": " ".join(sys.argv),
        },
        "significance": significance,
        "bucket_reference": bucket_reference,
        "buckets": buckets,
        "length_buckets": length_buckets,
        "timings": timings,
        "results": public_results,
    }
    if args.output_json is not None:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nwrote {args.output_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
