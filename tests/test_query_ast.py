from __future__ import annotations

from lse.query_ast import QueryCompiler


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
    assert "系统" in compiled2

    # 3. 容错未闭合引号
    compiler3 = QueryCompiler('"未闭合短语')
    compiled3, _, _ = compiler3.compile()
    assert '"未闭合短语"' in compiled3
