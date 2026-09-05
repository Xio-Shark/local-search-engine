from __future__ import annotations

from pathlib import Path
from lse.tokenizer import split_identifier, tokenize_cjk_run, tokenize_stream
from lse.query_ast import QueryCompiler
from lse.resonance import extract_evidence_spans
from lse.indexer import IndexEngine, _compute_content_hash
from lse.searcher import SearchEngine


def test_code_identifier_tokenization():
    tokens = split_identifier("localSearchEngine")
    assert "local" in tokens
    assert "search" in tokens
    assert "engine" in tokens
    assert "localsearchengine" in tokens

    snake_tokens = split_identifier("delta_codec_v2")
    assert "delta" in snake_tokens
    assert "codec" in snake_tokens
    assert "v2" in snake_tokens

    path_tokens = split_identifier("com.localengine.IndexManager")
    assert "index" in path_tokens
    assert "manager" in path_tokens


def test_cjk_and_mixed_tokenization():
    tokens = tokenize_cjk_run("搜索引擎")
    assert "搜索引擎" in tokens
    assert "搜索" in tokens
    assert "索引" in tokens
    assert "引擎" in tokens
    assert "搜" in tokens
    assert "引" in tokens

    mixed_tokens = tokenize_stream("测试 C++多线程 与 GPT-4o架构 设计")
    assert "测试" in mixed_tokens
    assert "c++" in mixed_tokens
    assert "多线程" in mixed_tokens
    assert "gpt-4o" in mixed_tokens or "gpt" in mixed_tokens
    assert "架构" in mixed_tokens


def test_query_ast_lexer_and_compiler():
    # 1. 字段别名与大小范围编译
    compiler = QueryCompiler('ext:md size:10KB..5MB sort:mtime:desc "distributed system"')
    compiled, sort_field, sort_order = compiler.compile()

    assert "extension:md" in compiled
    assert "size:[10240 TO 5242880]" in compiled
    assert '"distributed system"' in compiled
    assert sort_field == "mtime"

    # 2. 中文短语自动安全括号展开
    compiler2 = QueryCompiler("分布式系统 架构")
    compiled2, _, _ = compiler2.compile()
    assert '("分布式系统"^5 OR' in compiled2
    assert "分布式" in compiled2
    assert "布式" in compiled2

    # 3. 容错未闭合引号
    compiler3 = QueryCompiler('"未闭合短语')
    compiled3, _, _ = compiler3.compile()
    assert '"未闭合短语"' in compiled3


def test_dynamic_evidence_resonance_spans():
    content = """# 知识库主文档

这是引言部分。

## 核心架构设计

搜索引擎的核心在于倒排索引。
倒排索引结合 BM25 评分可以实现超高速精准检索。
在此处我们计算能量共振极大值。

## 存储细节

底层采用列式存储与变长整数压缩。
"""
    spans = extract_evidence_spans(content, ["倒排索引", "BM25", "检索"])
    assert len(spans) >= 1
    best_span = spans[0]
    # 验证行号正确性 (位于第 7-10 行附近)
    assert best_span.start_line >= 5
    assert best_span.end_line <= 12
    # 验证面包屑层级
    assert "核心架构设计" in best_span.breadcrumbs
    assert best_span.confidence > 0.0
    assert "倒排索引" in best_span.text


def test_content_hash_and_atomic_state(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    idx_dir = tmp_path / "index"

    f = data_dir / "test.md"
    f.write_text("固定不变的文件内容", encoding="utf-8")
    orig_hash = _compute_content_hash(f)
    assert len(orig_hash) == 32

    engine = IndexEngine(idx_dir)
    status = engine.build([data_dir])
    assert status.doc_count == 1

    # 验证 state.json 原子写入与 content_hash 记录
    state_file = idx_dir / "state.json"
    assert state_file.exists()
    assert not (idx_dir / "state.json.tmp").exists()

    # 验证搜索结果包含 spans 证据区间
    searcher = SearchEngine(idx_dir)
    res = searcher.search("固定不变")
    assert res.total_matches == 1
    hit = res.hits[0]
    assert len(hit.spans) >= 1
    assert hit.spans[0].start_line == 1
    assert "固定不变" in hit.spans[0].text
