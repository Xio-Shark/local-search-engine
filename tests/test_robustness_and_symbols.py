from __future__ import annotations

from pathlib import Path
from lse.indexer import IndexEngine
from lse.query_ast import QueryCompiler
from lse.resonance import extract_evidence_spans
from lse.searcher import SearchEngine


def test_query_ast_self_healing():
    """验证查询编译器括号自愈与悬挂操作符修剪。"""
    c1 = QueryCompiler("(error AND timeout")
    compiled1, _, _ = c1.compile()
    assert compiled1.endswith(")")
    assert "(" in compiled1

    c2 = QueryCompiler("timeout AND")
    compiled2, _, _ = c2.compile()
    assert compiled2 == "timeout"

    c3 = QueryCompiler("OR error NOT")
    compiled3, _, _ = c3.compile()
    assert compiled3 == "error"

    c4 = QueryCompiler("(foo OR (bar AND))")
    compiled4, _, _ = c4.compile()
    assert "foo" in compiled4
    assert "bar" in compiled4


def test_search_engine_syntax_crash_immunity(sample_corpus):
    """验证即使输入非法语法查询，引擎绝不崩溃退出，优雅自愈或降级。"""
    searcher = SearchEngine(sample_corpus["index_dir"])

    # 未闭合括号
    res1 = searcher.search("(distributed OR system")
    assert isinstance(res1.total_matches, int)

    # 悬挂 AND / OR
    res2 = searcher.search("distributed AND")
    assert res2.total_matches >= 1

    # 特殊转义符号
    res3 = searcher.search("error [*:?]")
    assert isinstance(res3.total_matches, int)


def test_version_and_number_query_preservation(tmp_path: Path):
    """验证技术版本号（如 GPT-4o, C++17, v0.2.0）在提取与检索中保留数字。"""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    idx_dir = tmp_path / "index"

    f = data_dir / "tech.md"
    f.write_text("我们在集群中部署了 GPT-4o 架构与 C++17 运行库，版本为 v0.2.0。", encoding="utf-8")

    engine = IndexEngine(idx_dir)
    engine.build([data_dir])

    searcher = SearchEngine(idx_dir)
    # 验证带数字的版本检索
    res_gpt = searcher.search("GPT-4o")
    assert res_gpt.total_matches == 1

    res_cpp = searcher.search("C++17")
    assert res_cpp.total_matches == 1


def test_symbol_aware_code_spans():
    """验证多层代码符号感知与面包屑解析。"""
    code_content = """# 用户认证模块

import os

class TokenValidator:
    \"\"\"负责令牌有效性与重试预算。\"\"\"

    def verify_jwt_signature(self, token: str) -> bool:
        # 在此处验证签名
        if not token:
            raise ValueError("Token is empty")
        return True
"""
    spans = extract_evidence_spans(code_content, ["verify_jwt_signature", "Token"])
    assert len(spans) >= 1
    best_span = spans[0]
    assert "TokenValidator" in best_span.breadcrumbs or "verify_jwt_signature" in best_span.breadcrumbs
    assert "verify_jwt_signature" in best_span.text
    assert best_span.confidence > 0.0


def test_zero_storage_architecture(sample_corpus):
    """验证 content 字段不在索引内部重复存储，直接零拷贝自本地文件读取。"""
    engine = IndexEngine(sample_corpus["index_dir"])
    searcher = engine.index.searcher()
    # 检查 Tantivy Document 内部并未存储 content 文本
    doc = searcher.doc(searcher.search(engine.index.parse_query("*", ["content"]), 1).hits[0][1])
    assert doc.get_first("content") is None  # stored=False 生效
    assert doc.get_first("path") is not None


def test_resonance_sibling_method_breadcrumbs():
    """验证同类内并列方法退回上级缩进时，符号栈正确弹栈，杜绝面包屑串连。"""
    code = """class OrderService:
    def create_order(self):
        print("create")

    def cancel_order(self):
        print("cancel")
"""
    spans = extract_evidence_spans(code, ["cancel"])
    assert len(spans) >= 1
    # 面包屑应为 class OrderService > def cancel_order，绝不包含 def create_order
    assert "cancel_order" in spans[0].breadcrumbs
    assert "create_order" not in spans[0].breadcrumbs


def test_find_symbol_definition_class_methods():
    """验证 _find_symbol_definition 能够正确深入类内部定位方法并识别 method 类型。"""
    from lse.packer import _find_symbol_definition

    py_code = """class Authenticator:
    def __init__(self):
        pass

    def authenticate_header(self, auth: str) -> bool:
        return bool(auth)
"""
    dep = _find_symbol_definition(py_code, "authenticate_header", "auth.py")
    assert dep is not None
    assert dep.symbol == "authenticate_header"
    assert dep.kind == "method"
    assert "def authenticate_header" in dep.code
    assert dep.line_no == 5


def test_semantic_cjk_subwords_no_gibberish():
    """验证长汉字词语义切分优先，彻底消除'统架'、'计规'等无意义字元切片。"""
    from lse.query_ast import QueryCompiler

    c = QueryCompiler("系统架构设计规范")
    compiled, _, _ = c.compile()
    assert "架构" in compiled
    assert "设计" in compiled
    assert "规范" in compiled
    assert " OR 统架" not in compiled
    assert " OR 计规" not in compiled


