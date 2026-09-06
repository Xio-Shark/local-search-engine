"""测试新增的核心创新特性：自适应项目概念挖掘、契约保留型存根以及吞吐优化。"""

import ast
from pathlib import Path
from lse.concepts import AdaptiveConceptMiner, merge_concept_maps, save_project_concepts, load_project_concepts, BASE_TECHNICAL_CONCEPTS
from lse.model import IndexableFile
from lse.packer import _skeletonize_py_node
from lse.query_ast import QueryCompiler


def test_contract_preserving_skeleton_with_guard_clauses():
    """验证契约保留型存根能够精准保留前置校验断言与异常抛出，折叠纯内部计算。"""
    py_code = '''def process_user_payment(account_id: str, amount_cents: int, idempotency_key: str | None = None) -> PaymentReceipt:
    """处理用户支付扣款核心事务。"""
    if not account_id:
        raise ValueError("Invalid account_id: cannot be empty")
    if amount_cents <= 0:
        raise ValueError("amount_cents must be strictly positive")
    assert idempotency_key != "", "Idempotency key cannot be empty string"
    
    # 复杂计算与内部重试循环
    attempts = 0
    while attempts < 3:
        status = call_payment_gateway(account_id, amount_cents)
        if status.is_success:
            return PaymentReceipt(id=status.tx_id, success=True)
        attempts += 1
    raise RuntimeError("Payment gateway unreachable")
'''
    tree = ast.parse(py_code)
    func_node = tree.body[0]
    lines = py_code.splitlines()

    stub = _skeletonize_py_node(func_node, lines)

    # 1. 保留签名与文档
    assert "def process_user_payment" in stub
    assert "处理用户支付扣款核心事务" in stub
    # 2. 保留关键契约与前置保护
    assert "raise ValueError(\"Invalid account_id: cannot be empty\")" in stub
    assert "raise ValueError(\"amount_cents must be strictly positive\")" in stub
    assert "assert idempotency_key != \"\"" in stub
    # 3. 内部循环被折叠
    assert "call_payment_gateway" not in stub
    assert "while attempts < 3:" not in stub
    assert "..." in stub


def test_adaptive_concept_miner():
    """验证从文件结构中自动挖掘共现拓扑概念。"""
    miner = AdaptiveConceptMiner()
    files = [
        IndexableFile(Path("/repo/order/payment_service.py"), ".py", 100, 1.0, "code", ""),
        IndexableFile(Path("/repo/order/order_controller.py"), ".py", 100, 1.0, "code", ""),
        IndexableFile(Path("/repo/auth/jwt_authenticator.py"), ".py", 100, 1.0, "code", ""),
        IndexableFile(Path("/repo/auth/token_verifier.py"), ".py", 100, 1.0, "code", ""),
    ]
    graph = miner.mine(files)

    # 验证提取出了 order 与 payment / controller 的关联
    assert "payment" in graph or "order" in graph
    if "payment" in graph:
        assert "order" in graph["payment"]
    if "jwt" in graph:
        assert "auth" in graph["jwt"]


def test_dynamic_concept_expansion_in_compiler(tmp_path: Path):
    """验证编译查询时能动态注入项目自适应挖掘的概念。"""
    custom_map = merge_concept_maps(
        BASE_TECHNICAL_CONCEPTS,
        {"结算": ["settlement", "checkout", "clearing"]}
    )
    save_project_concepts(tmp_path, custom_map)
    loaded = load_project_concepts(tmp_path)

    assert "结算" in loaded
    assert "checkout" in loaded["结算"]

    # 验证 QueryCompiler 使用了注入的动态概念
    compiler = QueryCompiler("订单 结算", concept_map=loaded)
    compiled_q, _, _ = compiler.compile()
    assert "checkout" in compiled_q
    assert "settlement" in compiled_q
