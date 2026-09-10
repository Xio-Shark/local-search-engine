from __future__ import annotations

from bench.bench_public import BEIR_DATASETS, COIR_DATASETS, coir_file_spec


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
