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


def test_query_policy_grid_covers_auto_thresholds() -> None:
    from bench.bench_query_policy import build_policies

    policies = build_policies()
    assert policies["natural"].query_mode == "natural"
    assert policies["structured_and"].natural_query is False
    assert policies["auto@0"].auto_structured_max_terms == 0
    assert "auto@3" in policies
    # 策略扫描本身不该把 evidence span 读取算进延迟
    assert all(not options.include_spans for options in policies.values())


def test_parallel_dataset_helpers() -> None:
    from bench.parallel import child_argv, resolve_jobs, split_datasets

    assert split_datasets("scifact, nfcorpus ,,fiqa") == ["scifact", "nfcorpus", "fiqa"]
    assert resolve_jobs(0, ["a", "b", "c"]) == 3
    assert resolve_jobs(0, ["a"] * 9) == 4
    assert resolve_jobs(2, ["a", "b", "c"]) == 2

    argv = child_argv(
        ["--dataset", "a,b", "--output-json", "bench/results/{dataset}.json"], "b"
    )
    assert argv[-4:] == ["--dataset", "b", "--jobs", "1"]
    assert argv[-5] == "bench/results/b.json"


def test_multi_dataset_mode_requires_placeholder(capsys) -> None:
    from bench.bench_query_policy import main

    assert main(["--dataset", "scifact,nfcorpus", "--output-json", "bench/results/out.json"]) == 2
    assert "{dataset}" in capsys.readouterr().err


def test_bucket_analysis_groups_by_content_terms() -> None:
    from bench.bench_query_policy import bucket_analysis

    results = {
        "natural": {"per_query": {"q1": {"ndcg@10": 1.0}, "q2": {"ndcg@10": 0.0}}},
        "structured_and": {"per_query": {"q1": {"ndcg@10": 0.5}, "q2": {"ndcg@10": 0.0}}},
    }
    features = {
        "q1": {"content_terms": 2},
        "q2": {"content_terms": 7},
        "q3": {"content_terms": -1},
    }
    rows = bucket_analysis(results, features, "natural", "structured_and")
    assert [row["bucket"] for row in rows] == ["2", "6+"]
    assert rows[0]["delta"] == pytest.approx(0.5)
    assert rows[0]["a_win_rate"] == pytest.approx(1.0)
    assert rows[1]["delta"] == pytest.approx(0.0)


def test_gap_suite_only_toggles_scoring_knobs() -> None:
    from bench.bench_query_policy import build_policies

    policies = build_policies("gap")
    assert {"natural", "natural_no_idf", "natural_idf100", "natural_content_only"} <= set(policies)
    assert all(options.query_mode == "natural" for options in policies.values())
    assert policies["natural"].idf_power == 0.25
    assert policies["natural_no_idf"].idf_power is None
    assert policies["natural_idf100"].idf_power == 1.0
    assert policies["natural_content_only"].query_fields == ("content",)
    assert all(not options.include_spans for options in policies.values())


def test_bucket_analysis_by_query_length() -> None:
    from bench.bench_query_policy import bucket_analysis

    results = {
        "natural": {"per_query": {"q1": {"ndcg@10": 1.0}, "q2": {"ndcg@10": 0.5}}},
        "tantivy_bm25": {"per_query": {"q1": {"ndcg@10": 0.0}, "q2": {"ndcg@10": 0.5}}},
    }
    features = {"q1": {"chars": 15}, "q2": {"chars": 400}}
    rows = bucket_analysis(results, features, "natural", "tantivy_bm25", key="chars")
    assert [row["bucket"] for row in rows] == ["<=20", ">160"]
    assert rows[0]["delta"] == pytest.approx(1.0)
    assert all(row["key"] == "chars" for row in rows)


def test_length_suite_and_query_subset() -> None:
    from bench.bench_query_policy import build_policies, select_query_subset

    policies = build_policies("length")
    assert policies["natural"].idf_power_long is None
    assert policies["len160_idf100"].idf_power == 0.25
    assert policies["len160_idf100"].idf_power_long == 1.0
    assert policies["len160_idf100"].idf_power_long_chars == 160
    assert all(options.query_mode == "natural" for options in policies.values())

    query_ids = [f"q{index:03d}" for index in range(10)]
    half_a = select_query_subset(query_ids, "a", seed=42)
    half_b = select_query_subset(query_ids, "b", seed=42)
    assert len(half_a) == len(half_b) == 5
    assert not set(half_a) & set(half_b)
    assert sorted(half_a + half_b) == sorted(query_ids)
    assert select_query_subset(query_ids, "a", seed=42) == half_a
    assert select_query_subset(query_ids, "all") == query_ids


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
