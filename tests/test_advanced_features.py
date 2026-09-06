from __future__ import annotations

import ast
from pathlib import Path

from lse.packer import (
    _resolve_file_imports,
    _skeletonize_general_code,
    _skeletonize_py_node,
)
from lse.query_ast import QueryCompiler
from lse.resonance import extract_evidence_spans


def test_concept_expansion_bilingual():
    """测试双向技术概念投影：自然语言意图展开与代码关键词投影。"""
    # 1. 英文概念投影到代码别名与中文
    c1 = QueryCompiler("database transaction rollback contextmanager")
    compiled1, _, _ = c1.compile()
    assert "transaction" in compiled1
    assert "rollback" in compiled1
    assert "事务" in compiled1 or "tx" in compiled1
    assert "__enter__" in compiled1 or "scope" in compiled1

    # 2. 中文意图投影到英文代码标识符
    c2 = QueryCompiler("用户 鉴权 令牌")
    compiled2, _, _ = c2.compile()
    assert "authenticate" in compiled2 or "auth" in compiled2 or "jwt" in compiled2
    assert "token" in compiled2 or "bearer" in compiled2


def test_python_interface_skeletonization():
    """测试 Python 类与函数的接口存根化（Skeletonization）：保留签名、文档与类型，折叠深层函数体。"""
    py_code = '''class DatabaseManager:
    """企业级数据库长连接与事务管理器。"""
    pool_size: int
    timeout: float

    def __init__(self, host: str, port: int = 5432) -> None:
        """初始化连接池。"""
        self.host = host
        self.port = port
        self.active_sessions = []
        for i in range(10):
            self.active_sessions.append(object())

    def execute_transaction(self, query: str, params: dict) -> bool:
        """执行事务操作并保证 ACID。"""
        if not query:
            raise ValueError("Query is empty")
        print(f"Executing {query} with {params}")
        # 很多复杂的业务逻辑
        result = True
        return result
'''
    tree = ast.parse(py_code)
    class_node = tree.body[0]
    lines = py_code.splitlines()

    stub = _skeletonize_py_node(class_node, lines)

    # 验证关键契约完备
    assert "class DatabaseManager:" in stub
    assert "企业级数据库长连接与事务管理器" in stub
    assert "pool_size: int" in stub
    assert "def __init__(self, host: str, port: int = 5432) -> None:" in stub
    assert "def execute_transaction(self, query: str, params: dict) -> bool:" in stub
    assert "执行事务操作并保证 ACID" in stub
    assert "..." in stub
    # 验证内部实现被优雅折叠
    assert "self.active_sessions.append(object())" not in stub
    assert "print(f\"Executing" not in stub


def test_general_code_skeletonization():
    """测试多语言（TS / Go / Rust）结构体与接口签名骨架抽取。"""
    ts_code = """export class PaymentService {
    private client: HttpClient;
    public apiKey: string;

    constructor(apiKey: string) {
        this.apiKey = apiKey;
        this.client = new HttpClient();
    }

    public async processCharge(amount: number, currency: string): Promise<boolean> {
        if (amount <= 0) {
            throw new Error("Invalid amount");
        }
        const resp = await this.client.post("/charge", { amount, currency });
        return resp.status === 200;
    }
}
"""
    lines = ts_code.splitlines()
    stub = _skeletonize_general_code(lines, 0, len(lines) - 1, "class")
    assert "export class PaymentService {" in stub
    assert "public async processCharge(amount: number, currency: string): Promise<boolean> { ... }" in stub
    assert "throw new Error" not in stub


def test_rust_and_go_import_resolution(tmp_path: Path):
    """测试 Rust 和 Go 源文件的静态依赖与导入解析。"""
    project_dir = tmp_path / "rust_go_project"
    project_dir.mkdir()

    # 1. Rust mod / use 解析
    src_dir = project_dir / "src"
    src_dir.mkdir()
    (src_dir / "auth.rs").write_text("pub struct AuthToken;\n", encoding="utf-8")
    main_rs = src_dir / "main.rs"
    rs_content = """
mod auth;
use crate::auth::AuthToken;
"""
    main_rs.write_text(rs_content, encoding="utf-8")
    syms, files = _resolve_file_imports(str(main_rs), rs_content)
    assert "auth" in syms
    assert "AuthToken" in syms
    assert str(src_dir / "auth.rs") in files

    # 2. Go import 解析
    pkg_dir = project_dir / "pkg"
    pkg_dir.mkdir()
    (pkg_dir / "service.go").write_text("package pkg\ntype MyService struct{}\n", encoding="utf-8")
    main_go = project_dir / "main.go"
    go_content = """
package main
import (
    "rust_go_project/pkg"
)
"""
    main_go.write_text(go_content, encoding="utf-8")
    go_syms, go_files = _resolve_file_imports(str(main_go), go_content)
    assert any("service.go" in f for f in go_files)


def test_smart_span_gap_merging():
    """测试相邻碎片区间的无缝融合（消除函数中间 2~5 行空隙切口）。"""
    code = """class Calculator:
    def add(self, a: int, b: int) -> int:
        # 加法操作
        return a + b

    def subtract(self, a: int, b: int) -> int:
        # 减法操作
        return a - b
"""
    # 查询命中 add 和 subtract
    spans = extract_evidence_spans(code, ["加法操作", "减法操作"])
    # 智能融合后应合并为一个自闭合类完整跨度，而不是切断为两半
    assert len(spans) == 1
    assert "def add" in spans[0].text
    assert "def subtract" in spans[0].text
    assert spans[0].start_line <= 2
    assert spans[0].end_line >= 7
