"""工业级信息检索 (IR) 质量与 Context 压缩度基准评测。

解决核心痛点：
严苛评估搜索引擎的实际召回质量与排序能力，消灭“只测吞吐与耗时、不测搜索准不准”的评测缺陷。

评测指标：
1. Hit@1 & Hit@3 准确率
2. MRR (Mean Reciprocal Rank，平均倒数排名)
3. 1-Hop 依赖符号召回率 (Dependency Recall)
4. Context Token 压缩比 (Token Compression Ratio)
5. 端到端打包延迟 (Pack Latency)
"""

from __future__ import annotations

import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from lse.indexer import IndexEngine
from lse.packer import ContextPacker, estimate_tokens
from lse.searcher import SearchEngine


@dataclass
class GoldQuery:
    query: str
    target_file: str
    target_symbol: str
    expected_deps: list[str]


def _generate_realistic_codebase(root: Path) -> None:
    """生成具备多层跨文件调用、业务命名的真实微服务代码库。"""
    (root / "auth").mkdir(parents=True)
    (root / "limiter").mkdir(parents=True)
    (root / "db").mkdir(parents=True)
    (root / "cache").mkdir(parents=True)
    (root / "api").mkdir(parents=True)
    (root / "utils").mkdir(parents=True)
    (root / "config").mkdir(parents=True)

    # 1. auth/jwt_handler.py
    (root / "auth" / "jwt_handler.py").write_text('''"""JWT 令牌处理与签名验证。"""
from dataclasses import dataclass

@dataclass
class TokenPayload:
    user_id: str
    tenant_id: str
    exp: int

def decode_token(raw_token: str, secret: str) -> TokenPayload | None:
    """解码并检验 JWT 令牌中的 payload 和 exp 过期时间。"""
    if not raw_token or not secret:
        return None
    if "expired" in raw_token:
        raise ValueError("token expired signature error")
    return TokenPayload(user_id="u_123", tenant_id="t_main", exp=1999999999)

def sign_token(payload: TokenPayload, secret: str) -> str:
    """为指定用户签名生成新的 JWT 凭证字符串。"""
    return f"eyJ.{payload.user_id}.{secret}"
''', encoding="utf-8")

    # 2. auth/authenticator.py
    (root / "auth" / "authenticator.py").write_text('''"""API 认证网关中间件。"""
from .jwt_handler import decode_token, TokenPayload

class APIAuthenticator:
    """请求头身份鉴权器。"""

    def __init__(self, secret_key: str) -> None:
        self.secret_key = secret_key

    def authenticate_header(self, auth_header: str) -> TokenPayload:
        """解析 HTTP Authorization 头部并完成 Bearer 鉴权。"""
        if not auth_header or not auth_header.startswith("Bearer "):
            raise PermissionError("Missing Bearer authorization header")
        token = auth_header[7:].strip()
        payload = decode_token(token, self.secret_key)
        if not payload:
            raise PermissionError("Invalid token payload")
        return payload
''', encoding="utf-8")

    # 3. limiter/token_bucket.py
    (root / "limiter" / "token_bucket.py").write_text('''"""令牌桶速率限制核心算法。"""
import time
from dataclasses import dataclass

@dataclass
class LimiterMetrics:
    current_tokens: float
    last_updated: float

class TokenBucketLimiter:
    """平滑突发流量的令牌桶限流实现。"""

    def __init__(self, capacity: int, refill_rate: float) -> None:
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.state: dict[str, LimiterMetrics] = {}

    def acquire_token(self, key: str, tokens: int = 1) -> bool:
        """尝试从令牌桶中消费配额，返回是否被允许放行。"""
        now = time.time()
        metric = self.state.get(key, LimiterMetrics(current_tokens=self.capacity, last_updated=now))
        elapsed = now - metric.last_updated
        metric.current_tokens = min(self.capacity, metric.current_tokens + elapsed * self.refill_rate)
        metric.last_updated = now
        if metric.current_tokens >= tokens:
            metric.current_tokens -= tokens
            self.state[key] = metric
            return True
        return False
''', encoding="utf-8")

    # 4. limiter/middleware.py
    (root / "limiter" / "middleware.py").write_text('''"""限流网络中间件。"""
from .token_bucket import TokenBucketLimiter

class RateLimitMiddleware:
    """IP 级别流量拦截器。"""

    def __init__(self, limiter: TokenBucketLimiter) -> None:
        self.limiter = limiter

    def handle_request(self, client_ip: str) -> tuple[int, str]:
        """拦截网络请求，若超限则返回 HTTP 429 错误状态。"""
        allowed = self.limiter.acquire_token(client_ip)
        if not allowed:
            return 429, "exceed rate limit retry after 60s"
        return 200, "OK"
''', encoding="utf-8")

    # 5. db/connection_pool.py
    (root / "db" / "connection_pool.py").write_text('''"""数据库连接池管理。"""
from dataclasses import dataclass

@dataclass
class Connection:
    conn_id: int
    is_busy: bool

class ConnectionPool:
    """线程安全的数据库长连接池。"""

    def __init__(self, max_size: int = 10) -> None:
        self.max_size = max_size
        self.pool = [Connection(i, False) for i in range(max_size)]

    def acquire_connection(self, timeout_sec: float = 3.0) -> Connection:
        """从连接池中借出一个可用连接，超时则报错。"""
        for conn in self.pool:
            if not conn.is_busy:
                conn.is_busy = True
                return conn
        raise TimeoutError("database pool acquire timeout, all active_connections busy")

    def release_connection(self, conn: Connection) -> None:
        """归还连接至连接池。"""
        conn.is_busy = False
''', encoding="utf-8")

    # 6. db/transaction.py
    (root / "db" / "transaction.py").write_text('''"""事务上下文管理器。"""
from .connection_pool import ConnectionPool, Connection

class TransactionScope:
    """自动提交与回滚的数据库事务作用域。"""

    def __init__(self, pool: ConnectionPool) -> None:
        self.pool = pool
        self.conn: Connection | None = None

    def __enter__(self) -> Connection:
        self.conn = self.pool.acquire_connection()
        return self.conn

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type:
            # 异常发生时自动回滚事务
            pass
        if self.conn:
            self.pool.release_connection(self.conn)
''', encoding="utf-8")

    # 7. cache/lru_cache.py
    (root / "cache" / "lru_cache.py").write_text('''"""基于 LRU 策略的高性能内存缓存。"""
from collections import OrderedDict

class LRUCacheLayer:
    """支持 TTL 和容量淘汰的 LRU 缓存层。"""

    def __init__(self, max_entries: int = 1000) -> None:
        self.cache: OrderedDict[str, str] = OrderedDict()
        self.max_entries = max_entries

    def get_or_set(self, key: str, default_val: str) -> str:
        """读取缓存值，不存在则写入并刷新淘汰顺序。"""
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        if len(self.cache) >= self.max_entries:
            self.cache.popitem(last=False)
        self.cache[key] = default_val
        return default_val

    def invalidate(self, key: str) -> None:
        """从缓存中主动失效指定键。"""
        self.cache.pop(key, None)
''', encoding="utf-8")

    # 8. api/order_controller.py
    (root / "api" / "order_controller.py").write_text('''"""订单处理与结算控制器。"""
from ..auth.authenticator import APIAuthenticator
from ..db.transaction import TransactionScope
from ..cache.lru_cache import LRUCacheLayer

class OrderController:
    """核心订单业务控制器。"""

    def __init__(self, auth: APIAuthenticator, tx: TransactionScope, cache: LRUCacheLayer) -> None:
        self.auth = auth
        self.tx = tx
        self.cache = cache

    def create_order(self, auth_header: str, items: list[dict]) -> dict:
        """创建订单，完成鉴权并写入事务数据库。"""
        payload = self.auth.authenticate_header(auth_header)
        with self.tx as conn:
            # 写入订单数据
            order_id = f"ord_{payload.user_id}_999"
        self.cache.invalidate(f"user_orders_{payload.user_id}")
        return {"order_id": order_id, "status": "created"}
''', encoding="utf-8")

    # 9. utils/serializer.py
    (root / "utils" / "serializer.py").write_text('''"""数据序列化工具。"""
from datetime import datetime
import json

def serialize_datetime(dt: datetime) -> str:
    """将 datetime 转换为标准 ISO8601 字符串格式。"""
    return dt.isoformat()

def dumps_clean(obj: dict) -> str:
    """序列化字典为紧凑 JSON。"""
    return json.dumps(obj, separators=(",", ":"))
''', encoding="utf-8")

    # 10. config/settings.py
    (root / "config" / "settings.py").write_text('''"""应用配置加载器。"""
import os
from dataclasses import dataclass

@dataclass
class AppConfig:
    db_url: str
    secret_key: str
    port: int

def load_config_from_env() -> AppConfig:
    """从系统环境变量加载应用运行时参数。"""
    db = os.environ.get("DATABASE_URL", "sqlite:///memory:")
    sec = os.environ.get("APP_SECRET", "default_secret")
    p = int(os.environ.get("APP_PORT", "8080"))
    return AppConfig(db_url=db, secret_key=sec, port=p)
''', encoding="utf-8")


BENCHMARK_QUERIES = [
    GoldQuery(
        query="JWT token payload decode exp",
        target_file="auth/jwt_handler.py",
        target_symbol="decode_token",
        expected_deps=["TokenPayload"],
    ),
    GoldQuery(
        query="Bearer header APIAuthenticator authenticate",
        target_file="auth/authenticator.py",
        target_symbol="authenticate_header",
        expected_deps=["decode_token"],
    ),
    GoldQuery(
        query="sliding window token bucket rate limit capacity",
        target_file="limiter/token_bucket.py",
        target_symbol="acquire_token",
        expected_deps=["LimiterMetrics"],
    ),
    GoldQuery(
        query="RateLimitMiddleware request client_ip 429",
        target_file="limiter/middleware.py",
        target_symbol="handle_request",
        expected_deps=["acquire_token"],
    ),
    GoldQuery(
        query="connection pool acquire timeout active_connections",
        target_file="db/connection_pool.py",
        target_symbol="acquire_connection",
        expected_deps=["Connection"],
    ),
    GoldQuery(
        query="database transaction rollback commit contextmanager",
        target_file="db/transaction.py",
        target_symbol="TransactionScope",
        expected_deps=["acquire_connection", "release_connection"],
    ),
    GoldQuery(
        query="LRU cache ttl eviction invalidate",
        target_file="cache/lru_cache.py",
        target_symbol="invalidate",
        expected_deps=[],
    ),
    GoldQuery(
        query="create order checkout payment",
        target_file="api/order_controller.py",
        target_symbol="create_order",
        expected_deps=["authenticate_header", "invalidate"],
    ),
    GoldQuery(
        query="serialize datetime json isoformat",
        target_file="utils/serializer.py",
        target_symbol="serialize_datetime",
        expected_deps=[],
    ),
    GoldQuery(
        query="AppConfig load environment variable",
        target_file="config/settings.py",
        target_symbol="load_config_from_env",
        expected_deps=["AppConfig"],
    ),
    GoldQuery(
        query="token expired signature error",
        target_file="auth/jwt_handler.py",
        target_symbol="decode_token",
        expected_deps=["TokenPayload"],
    ),
    GoldQuery(
        query="exceed rate limit retry after",
        target_file="limiter/middleware.py",
        target_symbol="handle_request",
        expected_deps=["acquire_token"],
    ),
]


def run_ir_benchmarks() -> None:
    print("=" * 72)
    print("📊 运行标准信息检索 (IR) 质量与 Context 胶囊压缩度 Benchmark")
    print("=" * 72)

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        repo_dir = root / "project"
        idx_dir = root / "index"
        _generate_realistic_codebase(repo_dir)

        # 1. 建立索引
        engine = IndexEngine(idx_dir)
        engine.build([repo_dir])

        searcher = SearchEngine(idx_dir)
        packer = ContextPacker(idx_dir)

        hit_1_count = 0
        hit_3_count = 0
        reciprocal_ranks: list[float] = []
        ext_recall_scores: list[float] = []
        context_recall_scores: list[float] = []
        token_savings: list[float] = []
        latencies_ms: list[float] = []

        print(f"{'Query':<36} | {'Rank':<5} | {'ExtDeps':<8} | {'CtxCov':<8} | {'Tokens':<10} | {'Time'}")
        print("-" * 80)

        for gq in BENCHMARK_QUERIES:
            t0 = time.perf_counter()
            capsule, _ = packer.pack(gq.query, budget_tokens=1500, include_deps=True)
            elapsed = (time.perf_counter() - t0) * 1000.0
            latencies_ms.append(elapsed)

            # 评估排名 (Search Rank)
            res = searcher.search(gq.query, limit=5)
            rank = 0
            for idx, hit in enumerate(res.hits, 1):
                if gq.target_file in hit.path:
                    rank = idx
                    break

            if rank == 1:
                hit_1_count += 1
            if 1 <= rank <= 3:
                hit_3_count += 1

            reciprocal_rank = 1.0 / rank if rank > 0 else 0.0
            reciprocal_ranks.append(reciprocal_rank)

            # 评估 1-hop 依赖召回（严谨区分：跨文件反查 vs 同文件语法自闭包）
            found_deps = {d.symbol for d in capsule.dependencies}
            anchor_combined_code = "\n".join(a.code for a in capsule.anchors)

            target_code = (repo_dir / gq.target_file).read_text(encoding="utf-8")
            external_deps = []
            intra_file_deps = []
            for d in gq.expected_deps:
                if f"class {d}" in target_code or f"def {d}" in target_code:
                    intra_file_deps.append(d)
                else:
                    external_deps.append(d)

            # 外部跨文件反查召回（必须由 packer 真正反查并抽取到 dependencies 中）
            if external_deps:
                ext_hit = len([d for d in external_deps if d in found_deps])
                ext_recall = ext_hit / len(external_deps)
                ext_recall_scores.append(ext_recall)
                ext_str = f"{int(ext_recall * 100)}%"
            else:
                ext_str = "—"

            # 胶囊完整上下文覆盖率（外部依赖在 dependencies + 同文件符号被锚点闭包吸附）
            if gq.expected_deps:
                matched_all = [
                    d for d in gq.expected_deps
                    if d in found_deps or f"class {d}" in anchor_combined_code or f"def {d}" in anchor_combined_code
                ]
                cov_recall = len(matched_all) / len(gq.expected_deps)
                context_recall_scores.append(cov_recall)
                cov_str = f"{int(cov_recall * 100)}%"
            else:
                cov_str = "—"

            # 评估 Token 压缩率 (Capsule Tokens vs Full File Tokens)
            target_full_text = target_code
            full_tokens = estimate_tokens(target_full_text)
            capsule_tokens = capsule.estimated_tokens
            saving = max(0.0, (full_tokens - capsule_tokens) / max(full_tokens, 1)) * 100.0
            token_savings.append(saving)

            rank_str = f"#{rank}" if rank > 0 else "MISS"
            token_str = f"{capsule_tokens} tok"
            print(f"{gq.query[:34]:<36} | {rank_str:<5} | {ext_str:<8} | {cov_str:<8} | {token_str:<10} | {elapsed:.2f}ms")

        total = len(BENCHMARK_QUERIES)
        mrr = sum(reciprocal_ranks) / total
        hit_1_rate = (hit_1_count / total) * 100.0
        hit_3_rate = (hit_3_count / total) * 100.0
        avg_ext_recall = (sum(ext_recall_scores) / max(len(ext_recall_scores), 1)) * 100.0
        avg_cov_recall = (sum(context_recall_scores) / max(len(context_recall_scores), 1)) * 100.0
        p50_latency = sorted(latencies_ms)[len(latencies_ms) // 2]
        p99_latency = sorted(latencies_ms)[int(len(latencies_ms) * 0.95)]

        print("=" * 72)
        print("🎯 IR 质量与 Context 压缩实测总结：")
        print(f"  • Hit@1 准确率:                 {hit_1_rate:.1f}% ({hit_1_count}/{total})")
        print(f"  • Hit@3 准确率:                 {hit_3_rate:.1f}% ({hit_3_count}/{total})")
        print(f"  • MRR (平均倒数排名):            {mrr:.3f}")
        print(f"  • 严格跨文件 1-Hop 依赖反查召回:  {avg_ext_recall:.1f}% ({len(ext_recall_scores)}组有效)")
        print(f"  • 胶囊完整上下文符号覆盖率:      {avg_cov_recall:.1f}% ({len(context_recall_scores)}组有效)")
        print(f"  • 平均打包生成延迟 (P50):         {p50_latency:.2f} ms")
        print(f"  • 95 分位打包延迟 (P95):         {p99_latency:.2f} ms")
        print("=" * 72)


if __name__ == "__main__":
    run_ir_benchmarks()
