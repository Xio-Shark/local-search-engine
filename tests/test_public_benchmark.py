from __future__ import annotations

from pathlib import Path

import pytest

from bench.bench_public import (
    BEIR_DATASETS,
    COIR_DATASETS,
    aggregate_runs,
    coir_file_spec,
    paired_bootstrap,
    sample_coir_docs,
    select_sampled_query_ids,
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

class _FakeBatch:
    def __init__(self, rows):
        self._rows = rows

    def to_pylist(self):
        return list(self._rows)


def test_select_sampled_query_ids_is_deterministic() -> None:
    qrels = {f"q{i:03d}": {f"c{i}": 1.0} for i in range(100)}
    selected_a = select_sampled_query_ids(qrels, 10, seed=42)
    selected_b = select_sampled_query_ids(qrels, 10, seed=42)
    assert selected_a == selected_b
    assert len(selected_a) == 10
    assert selected_a == sorted(selected_a)

    assert select_sampled_query_ids(qrels, 0, seed=42) == sorted(qrels)
    assert select_sampled_query_ids(qrels, 999, seed=42) == sorted(qrels)


def test_sample_coir_docs_keeps_all_relevant_and_is_deterministic(monkeypatch) -> None:
    rows = [
        {"_id": "c0", "title": "", "text": "doc zero"},
        {"_id": "c1", "title": "", "text": "doc one"},
        {"_id": "c2", "title": "", "text": "doc two"},
        {"_id": "c3", "title": "", "text": "doc three"},
        {"_id": "c4", "title": "", "text": "doc four"},
        {"_id": "c5", "title": "", "text": "doc five"},
    ]

    def _fake_batches(_path, batch_size=5000):
        for start in range(0, len(rows), batch_size):
            yield _FakeBatch(rows[start : start + batch_size])

    import bench.bench_public as bench_public

    monkeypatch.setattr(bench_public, "_iter_parquet_batches", _fake_batches)

    relevant = {"c1", "c5"}
    sampled_a = sample_coir_docs(Path("unused.parquet"), relevant, 4, seed=42, batch_size=2)
    sampled_b = sample_coir_docs(Path("unused.parquet"), relevant, 4, seed=42, batch_size=2)

    assert len(sampled_a) == 4
    assert relevant <= {doc.doc_id for doc in sampled_a}
    assert [doc.doc_id for doc in sampled_a] == [doc.doc_id for doc in sampled_b]
