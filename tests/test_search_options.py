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

    # auto：短关键词查询保留 AND 精度
    short_auto = engine.search("alpha beta")
    assert short_auto.total_matches == 1
    assert Path(short_auto.hits[0].path).name == "both.txt"

    # auto：长查询自动切换为加权 OR
    long_auto = engine.search("alpha beta gamma delta")
    assert long_auto.total_matches == 3

    # 显式强制自然 OR / 结构化 AND
    natural = engine.search("alpha beta", options=SearchOptions(natural_query=True))
    assert natural.total_matches == 3
    strict = engine.search(
        "alpha beta", options=SearchOptions(natural_query=False, conjunction_by_default=True)
    )
    assert strict.total_matches == 1
    old_or = engine.search(
        "alpha beta", options=SearchOptions(natural_query=False, conjunction_by_default=False)
    )
    assert old_or.total_matches == 3

    # query_mode 字段等价可用
    forced_natural = engine.search("alpha beta", options=SearchOptions(query_mode="natural"))
    assert forced_natural.total_matches == 3
    forced_structured = engine.search("alpha beta", options=SearchOptions(query_mode="structured"))
    assert forced_structured.total_matches == 1


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
