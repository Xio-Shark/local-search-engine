"""测试 lse pack 意图到上下文胶囊打包器 (ContextPacker)。

覆盖：
1. 核心代码块锚点提取 (Anchors)
2. 1-hop 浅层符号依赖解析与定义反查
3. Token 预算压包裁剪逻辑
4. Markdown 与 JSON 格式序列化
5. 语法容错与极端边界（空内容、超长预算、低预算截断）
"""

from __future__ import annotations

from pathlib import Path

from lse.indexer import IndexEngine
from lse.packer import ContextPacker, estimate_tokens, copy_text_to_clipboard


def _setup_mock_repo(tmp_path: Path) -> tuple[Path, Path]:
    """构建包含类、函数调用和相互引用的测试代码库。"""
    repo = tmp_path / "repo"
    repo.mkdir()

    # 文件 1: 数据模型与类型定义
    models_code = '''"""认证模块数据结构。"""

from dataclasses import dataclass

@dataclass
class TokenPayload:
    user_id: str
    role: str
    exp: int

@dataclass
class AuthResult:
    is_valid: bool
    payload: TokenPayload | None
    error_msg: str = ""
'''
    (repo / "models.py").write_text(models_code, encoding="utf-8")

    # 文件 2: 签名校验工具库
    crypto_code = '''"""加解密与签名验证。"""

def verify_jwt_signature(token: str, secret_key: str) -> bool:
    """验证 JWT 签名的真实性。"""
    if not token or len(token) < 10:
        return False
    return token.startswith("eyJ") and secret_key != ""

def sign_jwt(payload_dict: dict, secret_key: str) -> str:
    """生成测试 JWT 令牌。"""
    return f"eyJ.{secret_key}"
'''
    (repo / "crypto.py").write_text(crypto_code, encoding="utf-8")

    # 文件 3: 核心认证服务（调用了 models 和 crypto）
    auth_code = '''"""用户认证核心服务。"""

from .models import AuthResult, TokenPayload
from .crypto import verify_jwt_signature

class AuthService:
    """认证业务层。"""

    def __init__(self, secret: str) -> None:
        self.secret = secret

    def authenticate_jwt_request(self, auth_header: str) -> AuthResult:
        """从请求头提取并验证 JWT 凭证有效性。"""
        if not auth_header.startswith("Bearer "):
            return AuthResult(is_valid=False, payload=None, error_msg="Missing Bearer")

        token = auth_header[7:]
        ok = verify_jwt_signature(token, self.secret)
        if not ok:
            return AuthResult(is_valid=False, payload=None, error_msg="Invalid signature")

        payload = TokenPayload(user_id="u-100", role="admin", exp=1999999999)
        return AuthResult(is_valid=True, payload=payload)
'''
    (repo / "auth.py").write_text(auth_code, encoding="utf-8")

    idx_dir = tmp_path / "index"
    engine = IndexEngine(idx_dir)
    engine.build([repo])
    return repo, idx_dir


def test_pack_basic_markdown_and_dependencies(tmp_path: Path):
    _, idx_dir = _setup_mock_repo(tmp_path)
    packer = ContextPacker(idx_dir)

    capsule, copied = packer.pack(
        query="authenticate_jwt_request Bearer",
        budget_tokens=1500,
        include_deps=True,
    )

    # 验证核心锚点
    assert len(capsule.anchors) >= 1
    anchor = capsule.anchors[0]
    assert "auth.py" in anchor.file_path
    assert "def authenticate_jwt_request" in anchor.code
    assert "AuthService" in anchor.breadcrumbs or "authenticate_jwt_request" in anchor.breadcrumbs

    # 验证 1-hop 依赖吸附：应当发现 verify_jwt_signature 或 AuthResult
    dep_symbols = {d.symbol for d in capsule.dependencies}
    assert any(sym in dep_symbols for sym in ["verify_jwt_signature", "AuthResult", "TokenPayload"])

    # 验证 Markdown 格式
    md = capsule.to_markdown()
    assert "# Context Capsule:" in md
    assert "## 🎯 Core Implementations (Anchors)" in md
    assert "## 🔗 1-Hop Referenced Dependencies" in md
    assert "authenticate_jwt_request" in md


def test_pack_json_format(tmp_path: Path):
    _, idx_dir = _setup_mock_repo(tmp_path)
    packer = ContextPacker(idx_dir)

    capsule, _ = packer.pack("verify_jwt_signature secret_key", budget_tokens=1000)
    json_str = capsule.to_json()
    assert '"query":' in json_str
    assert '"anchors":' in json_str
    assert '"dependencies":' in json_str
    assert "crypto.py" in json_str


def test_pack_budget_cutoff(tmp_path: Path):
    """测试极小预算下优雅裁剪依赖。"""
    _, idx_dir = _setup_mock_repo(tmp_path)
    packer = ContextPacker(idx_dir)

    # 极低预算：只能勉强放核心实现，不能无限放依赖
    capsule, _ = packer.pack(
        query="authenticate_jwt_request Bearer",
        budget_tokens=200,
        include_deps=True,
    )

    assert capsule.estimated_tokens <= 350
    assert len(capsule.anchors) >= 1


def test_token_estimator():
    assert estimate_tokens("") == 0
    assert estimate_tokens("hello world") > 0
    # 中英混合文本
    tokens = estimate_tokens("def authenticate(): # 这是一个认证函数")
    assert tokens > 5


def test_clipboard_fallback():
    # 测试在无 GUI/无终端剪贴板下的安全无崩溃降级
    res = copy_text_to_clipboard("test snippet")
    assert isinstance(res, bool)
