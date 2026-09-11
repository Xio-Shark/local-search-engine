from __future__ import annotations

import pytest

from bench.bench_public import (
    BEIR_DATASETS,
    COIR_DATASETS,
    aggregate_runs,
    coir_file_spec,
    paired_bootstrap,
)


def test_beir_and_coir_dataset_names_are_registered() -> None:
    assert "scifact" in BEIR_DATASETS
    assert "cosqa" in COIR_DATASETS
    assert "codesearchnet-python" in COIR_DATASETS


def test_coir_simple_dataset_paths() -> None:
    repo, corpus, queries, qrels = coir_file_spec("cosqa")
    assert repo == "CoIR-Retrieval/cosqa"
    assert corpus == "corpus/corpus-00000-of-00001.parquet"
    assert queries == "queries/queries-00000-of-00001.parquet"
    assert qrels == "data/test-00000-of-00001.parquet"


def test_coir_split_paths() -> None:
    repo, _, _, qrels = coir_file_spec("cosqa", "valid")
    assert repo == "CoIR-Retrieval/cosqa"
    assert qrels == "data/valid-00000-of-00001.parquet"

    _, _, _, train_qrels = coir_file_spec("cosqa", "train")
    assert train_qrels == "data/train-00000-of-00001.parquet"


def test_coir_codesearchnet_paths() -> None:
    repo, corpus, queries, qrels = coir_file_spec("codesearchnet-python")
    assert repo == "CoIR-Retrieval/CodeSearchNet"
    assert corpus == "python-corpus/corpus-00000-of-00001.parquet"
    assert queries == "python-queries/queries-00000-of-00001.parquet"
    assert qrels == "python-qrels/test-00000-of-00001.parquet"


def test_paired_bootstrap_reports_wins_and_ci() -> None:
    reference = {
        "per_query": {
            "q1": {"ndcg@10": 1.0},
            "q2": {"ndcg@10": 0.5},
            "q3": {"ndcg@10": 0.0},
        }
    }
    baseline = {
        "per_query": {
            "q1": {"ndcg@10": 0.0},
            "q2": {"ndcg@10": 0.5},
            "q3": {"ndcg@10": 0.0},
        }
    }
    stats = paired_bootstrap(reference, baseline, samples=200)
    assert stats["queries"] == 3.0
    assert stats["wins"] == 1
    assert stats["losses"] == 0
    assert stats["ties"] == 2
    assert stats["ci_low"] <= stats["mean_diff"] <= stats["ci_high"]


def test_aggregate_runs_reports_mean_and_std() -> None:
    runs = [
        {"ndcg@10": 0.10, "recall@10": 0.20, "mrr@10": 0.30, "p50_ms": 1.0, "total_seconds": 2.0},
        {"ndcg@10": 0.20, "recall@10": 0.40, "mrr@10": 0.50, "p50_ms": 3.0, "total_seconds": 4.0},
    ]
    aggregated = aggregate_runs(runs)
    assert aggregated["ndcg@10"] == pytest.approx(0.15)
    assert aggregated["runs"] == 2.0
    assert aggregated["std"]["ndcg@10"] == pytest.approx(0.05)
