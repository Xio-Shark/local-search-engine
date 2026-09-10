"""lse query-level ablation harness on public datasets.

在 dev split 上比较查询编译策略，避免直接用 test split 调参：

- BEIR / SciFact：``qrels/train.tsv``（809 条）为 dev，``test.tsv``（300 条）最终报告
- CoIR / CosQA：``data/valid``（500 条）为 dev，``data/test``（500 条）最终报告

示例：
    uv run python bench/bench_ablation.py --dataset scifact
    uv run --extra eval python bench/bench_ablation.py --dataset cosqa --qrels-split valid
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import tempfile
from pathlib import Path
from typing import Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bench.bench_public import (  # noqa: E402
    BEIR_DATASETS,
    COIR_DATASETS,
    DEFAULT_CACHE,
    LseRetriever,
    TantivyBm25Retriever,
    evaluate_retriever,
    load_dataset,
    materialize_docs,
)
from lse import __version__ as LSE_VERSION  # noqa: E402
from lse.options import SearchOptions  # noqa: E402

ABLATION_VARIANTS: dict[str, SearchOptions] = {
    # 旧默认：结构化 AST + 默认 AND + 概念展开
    "structured_and": SearchOptions(
        natural_query=False, conjunction_by_default=True, concept_expansion=True
    ),
    # 只把默认连接语义切换为 OR，保留旧 AST / 概念展开
    "structured_or": SearchOptions(
        natural_query=False, conjunction_by_default=False, concept_expansion=True
    ),
    # 自然查询重写：与索引对齐的分词 + OR，不启用 IDF 词项加权
    "natural_or": SearchOptions(natural_query=True, idf_power=None, concept_expansion=True),
    # dev split 最优：对齐分词 + OR + IDF^0.25
    "natural_idf025": SearchOptions(natural_query=True, idf_power=0.25, concept_expansion=True),
    # 敏感性检查：更强 / 更弱的稀有词强调
    "natural_idf010": SearchOptions(natural_query=True, idf_power=0.10, concept_expansion=True),
    "natural_idf050": SearchOptions(natural_query=True, idf_power=0.50, concept_expansion=True),
    # 移除 filename / path 字段与概念展开
    "natural_idf025_content": SearchOptions(
        natural_query=True, idf_power=0.25, concept_expansion=True, query_fields=("content",)
    ),
    "natural_idf025_noconcept": SearchOptions(
        natural_query=True, idf_power=0.25, concept_expansion=False
    ),
}


def default_dev_split(dataset: str) -> str:
    return "train" if dataset in BEIR_DATASETS else "valid"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="lse query ablation on public dev splits")
    parser.add_argument("--dataset", default="scifact")
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--qrels-split", default="", help="默认 BEIR=train / CoIR=valid")
    parser.add_argument("--top-k", type=int, default=100)
    parser.add_argument("--limit-queries", type=int, default=0)
    parser.add_argument("--variants", default="", help="逗号分隔的变体名，默认全部")
    parser.add_argument("--include-tantivy", action="store_true", help="同时运行原生 BM25 下界")
    parser.add_argument("--output-json", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    split = args.qrels_split or default_dev_split(args.dataset)
    if args.dataset not in BEIR_DATASETS and args.dataset not in COIR_DATASETS:
        print(f"unsupported dataset: {args.dataset}", file=sys.stderr)
        return 2

    try:
        docs, queries, qrels = load_dataset(args.dataset, args.cache_dir, split)
    except (FileNotFoundError, RuntimeError, ValueError, OSError) as error:
        print(f"dataset error: {error}", file=sys.stderr)
        return 2

    query_ids = [query_id for query_id in queries if qrels.get(query_id)]
    if args.limit_queries > 0:
        query_ids = query_ids[: args.limit_queries]
    selected_queries = {query_id: queries[query_id] for query_id in query_ids}

    names = [name.strip() for name in args.variants.split(",") if name.strip()]
    if not names:
        names = list(ABLATION_VARIANTS)
    unknown = [name for name in names if name not in ABLATION_VARIANTS]
    if unknown:
        print(f"unknown variants: {unknown}", file=sys.stderr)
        return 2

    print(
        f"dataset={args.dataset} split={split} docs={len(docs)} queries={len(selected_queries)} "
        f"qrels_queries={len(qrels)} top_k={args.top_k}"
    )

    results: dict[str, dict[str, float]] = {}
    with tempfile.TemporaryDirectory(prefix=f"lse-ablation-{args.dataset}-") as tmp:
        docs_dir, name_to_id = materialize_docs(docs, Path(tmp))
        if args.include_tantivy:
            print("running baseline=tantivy ...", file=sys.stderr)
            retriever = TantivyBm25Retriever(docs, name_to_id)
            try:
                results["tantivy_bm25"] = evaluate_retriever(
                    retriever, selected_queries, qrels, args.top_k
                )
            finally:
                retriever.close()

        for name in names:
            print(f"running variant={name} ...", file=sys.stderr)
            retriever = LseRetriever(docs_dir, name_to_id, options=ABLATION_VARIANTS[name])
            try:
                results[name] = evaluate_retriever(retriever, selected_queries, qrels, args.top_k)
            finally:
                retriever.close()

    print("")
    header = f"{'variant':<28} {'nDCG@10':>10} {'Recall@10':>10} {'MRR@10':>10} {'p50 ms':>10} {'total s':>10}"
    print(header)
    print("-" * len(header))
    for name, metrics in results.items():
        print(
            f"{name:<28} {metrics['ndcg@10']:>10.4f} {metrics['recall@10']:>10.4f} "
            f"{metrics['mrr@10']:>10.4f} {metrics['p50_ms']:>10.2f} "
            f"{metrics['total_seconds']:>10.2f}"
        )

    payload = {
        "dataset": args.dataset,
        "qrels_split": split,
        "docs": len(docs),
        "queries": len(selected_queries),
        "top_k": args.top_k,
        "meta": {
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "lse_version": LSE_VERSION,
            "command": " ".join(sys.argv),
        },
        "variants": {
            name: {
                "natural_query": options.natural_query,
                "idf_power": options.idf_power,
                "concept_expansion": options.concept_expansion,
                "query_fields": list(options.query_fields),
                "conjunction_by_default": options.conjunction_by_default,
            }
            for name, options in ABLATION_VARIANTS.items()
            if name in names
        },
        "results": results,
    }
    if args.output_json is not None:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"\nwrote {args.output_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
