"""查询期开关（自然查询重写 / IDF 权重 / 字段选择）与自然语言分类测试。"""

from __future__ import annotations

from pathlib import Path

from lse.indexer import IndexEngine
from lse.options import SearchOptions
from lse.query_ast import QueryCompiler
from lse.searcher import SearchEngine


def _build_index(tmp_path: Path, files: dict[str, str]) -> Path:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    for name, text in files.items():
        (corpus / name).write_text(text, encoding="utf-8")
    index_dir = tmp_path / "index"
    IndexEngine(index_dir).build([corpus])
    return index_dir


def test_plain_terms_classification() -> None:
    # 小写 and/or/not 与普通括号属于自然语言标点，不应触发结构化语义
    assert QueryCompiler("error timeout").plain_terms() == ["error", "timeout"]
    plain = QueryCompiler("heart disease and stroke (adults)")
    assert plain.plain_terms() == ["heart", "disease", "and", "stroke", "adults"]

    # 大写操作符 / 字段 / 短语 / 排序 / 通配符仍为结构化查询
    assert QueryCompiler("error AND timeout").plain_terms() is None
    assert QueryCompiler('"distributed system"').plain_terms() is None
    assert QueryCompiler("ext:md error").plain_terms() is None
    assert QueryCompiler("sort:size:desc").plain_terms() is None
    assert QueryCompiler("error *").plain_terms() is None


def test_natural_query_switch_or_and(tmp_path: Path) -> None:
    index_dir = _build_index(
        tmp_path,
        {
            "both.txt": "alpha beta",
            "alpha.txt": "alpha only",
            "beta.txt": "beta only",
        },
    )
    engine = SearchEngine(index_dir)

    natural = engine.search("alpha beta")
    assert natural.total_matches == 3
    assert Path(natural.hits[0].path).name == "both.txt"

    strict = engine.search(
        "alpha beta", options=SearchOptions(natural_query=False, conjunction_by_default=True)
    )
    assert strict.total_matches == 1
    assert Path(strict.hits[0].path).name == "both.txt"

    old_or = engine.search(
        "alpha beta", options=SearchOptions(natural_query=False, conjunction_by_default=False)
    )
    assert old_or.total_matches == 3


def test_query_fields_switch(tmp_path: Path) -> None:
    index_dir = _build_index(
        tmp_path,
        {
            "alpha_doc.txt": "gamma",
            "other.txt": "alpha content",
        },
    )
    engine = SearchEngine(index_dir)

    filename_only = engine.search(
        "alpha_doc.txt", options=SearchOptions(query_fields=("filename",))
    )
    assert filename_only.total_matches == 1
    assert Path(filename_only.hits[0].path).name == "alpha_doc.txt"

    content_only = engine.search("gamma", options=SearchOptions(query_fields=("content",)))
    assert content_only.total_matches == 1
    assert Path(content_only.hits[0].path).name == "alpha_doc.txt"


def test_mixed_cjk_query_keeps_group_semantics(tmp_path: Path) -> None:
    index_dir = _build_index(
        tmp_path,
        {
            "a.txt": "目录A文档内容",
            "b.txt": "目录B文档内容",
        },
    )
    engine = SearchEngine(index_dir)
    result = engine.search("目录A")
    assert result.total_matches == 1
    assert Path(result.hits[0].path).name == "a.txt"


def test_idf_weighting_can_be_disabled(tmp_path: Path) -> None:
    index_dir = _build_index(tmp_path, {"a.txt": "rare common alpha"})
    engine = SearchEngine(index_dir)
    weighted = engine.search("rare common", options=SearchOptions(idf_power=0.25))
    unweighted = engine.search("rare common", options=SearchOptions(idf_power=None))
    assert weighted.total_matches == 1
    assert unweighted.total_matches == 1
