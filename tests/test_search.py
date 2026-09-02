from __future__ import annotations

from pathlib import Path
from lse.searcher import SearchEngine


def test_chinese_search(sample_corpus):
    searcher = SearchEngine(sample_corpus["index_dir"])

    # 1. 连续中文短语
    res = searcher.search("本地全文本搜索引擎")
    assert res.total_matches >= 1
    assert any("doc1.md" in h.path for h in res.hits)

    # 2. 单汉字检索（单字不丢失）
    res_single = searcher.search("人")
    assert res_single.total_matches >= 1
    assert any("README.md" in h.path for h in res_single.hits)

    # 3. 组合词隐式 AND
    res_comb = searcher.search("简历 美团")
    assert res_comb.total_matches == 1
    assert "doc3.py" in res_comb.hits[0].path


def test_english_and_code_search(sample_corpus):
    searcher = SearchEngine(sample_corpus["index_dir"])

    # 1. 英文短语
    res_phrase = searcher.search('"distributed system"')
    assert res_phrase.total_matches >= 1

    # 2. 布尔组合
    res_bool = searcher.search("error AND (timeout OR retry)")
    assert res_bool.total_matches >= 1
    matched_names = [Path(h.path).name for h in res_bool.hits]
    assert "doc2.txt" in matched_names
    assert "doc3.py" in matched_names

    # 3. 单字母语言
    res_c = searcher.search("C")
    assert res_c.total_matches >= 1


def test_field_filters(sample_corpus):
    searcher = SearchEngine(sample_corpus["index_dir"])

    # 1. ext: 过滤
    res_ext = searcher.search("ext:md")
    assert res_ext.total_matches == 2
    for h in res_ext.hits:
        assert h.extension == "md"

    # 2. 字段过滤 + 关键词 AND（严格匹配，不可把非 md 文件召回）
    res_ext_term = searcher.search("ext:md 美团")
    assert res_ext_term.total_matches == 0  # 美团只在 doc3.py 里，不应被召回

    # 3. filename 精确匹配（不区分大小写）
    res_file = searcher.search("filename:readme.md")
    assert res_file.total_matches == 1
    assert Path(res_file.hits[0].path).name == "README.md"

    res_file_upper = searcher.search("filename:README.md")
    assert res_file_upper.total_matches == 1


def test_range_queries(sample_corpus):
    searcher = SearchEngine(sample_corpus["index_dir"])

    # 1. size 范围查询
    res_size = searcher.search("size:10..50000")
    assert res_size.total_matches == 4

    res_size_units = searcher.search("size:10B..500KB")
    assert res_size_units.total_matches == 4

    # 2. mtime 日期范围查询
    res_mtime = searcher.search("mtime:2020-01-01..2035-12-31")
    assert res_mtime.total_matches == 4


def test_sorting(sample_corpus):
    searcher = SearchEngine(sample_corpus["index_dir"])

    # 1. 按 size 升序
    res_asc = searcher.search("sort:size:asc")
    assert res_asc.total_matches == 4
    sizes = [h.size for h in res_asc.hits]
    assert sizes == sorted(sizes)

    # 2. 按 size 降序
    res_desc = searcher.search("sort:size:desc")
    assert res_desc.total_matches == 4
    sizes_desc = [h.size for h in res_desc.hits]
    assert sizes_desc == sorted(sizes_desc, reverse=True)

    # 3. 按 mtime 排序
    res_mtime = searcher.search("ext:md sort:mtime:desc")
    assert res_mtime.total_matches == 2


def test_snippets_extraction(sample_corpus):
    searcher = SearchEngine(sample_corpus["index_dir"])
    res = searcher.search("知识库")
    assert res.total_matches >= 1
    for h in res.hits:
        assert len(h.snippets) > 0
        assert "知识库" in h.snippets[0]

def test_cjk_expand_with_quotes(sample_corpus):
    searcher = SearchEngine(sample_corpus["index_dir"])
    # 带有双引号的精确中文短语，不应被粗暴拆成 OR
    res = searcher.search('"本地全文本搜索引擎"')
    assert res.total_matches == 1
    assert "doc1.md" in res.hits[0].path


def test_empty_and_wildcard_query(sample_corpus):
    searcher = SearchEngine(sample_corpus["index_dir"])
    res_empty = searcher.search("")
    assert res_empty.total_matches == 0
    assert len(res_empty.hits) == 0

    res_wildcard = searcher.search("*")
    assert res_wildcard.total_matches == 4
