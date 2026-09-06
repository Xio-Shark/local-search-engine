"""代码库自适应概念挖掘与动态意图投影 (Adaptive Codebase Concept Awareness)。

突破硬编码字典瓶颈：
在索引构建与增量更新阶段，自动挖掘目标代码库的：
1. 模块与路径拓扑共现（如 auth/ -> jwt_handler, token）
2. 复合符号与类名词族关联（如 RateLimitMiddleware -> ratelimit, limiter, token_bucket）
3. 文档标题与中英技术词汇对应关系
产出项目专属的自适应概念图谱，弥合自然语言意图与代码符号之间的词汇鸿沟。
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Sequence

from .model import IndexableFile
from .tokenizer import split_identifier

CONCEPTS_FILE = "concepts.json"

# 通用基础核心技术概念表（作为种子先验，支持后续项目级动态学习增广）
BASE_TECHNICAL_CONCEPTS: dict[str, list[str]] = {
    # 鉴权 / 认证 / 权限 / 令牌
    "鉴权": ["authenticate", "auth", "authenticator", "authorization", "jwt", "bearer", "token"],
    "认证": ["authenticate", "auth", "authenticator", "authorization", "jwt", "token"],
    "身份验证": ["authenticate", "auth", "credentials", "jwt", "token"],
    "授权": ["authorize", "authorization", "permission", "rbac", "scope", "token"],
    "令牌": ["token", "jwt", "bearer", "payload", "claims"],
    # 限流 / 频控 / 流量控制
    "限流": ["ratelimit", "rate_limit", "limiter", "token_bucket", "leaky_bucket", "sliding_window", "throttle"],
    "频控": ["ratelimit", "rate_limit", "limiter", "throttle", "frequency"],
    "防刷": ["ratelimit", "rate_limit", "throttle", "captcha"],
    # 缓存 / 淘汰 / 穿透
    "缓存": ["cache", "lru", "lru_cache", "redis", "memcached", "ttl"],
    "淘汰": ["evict", "eviction", "invalidate", "lru", "ttl"],
    "失效": ["invalidate", "expire", "expiration", "ttl"],
    # 数据库 / 事务 / 连接池
    "数据库": ["db", "database", "sql", "postgres", "mysql", "sqlite", "orm", "repository"],
    "连接池": ["connection_pool", "pool", "conn_pool", "connection", "acquire_connection"],
    "事务": ["transaction", "tx", "commit", "rollback", "contextmanager"],
    "回滚": ["rollback", "abort", "revert"],
    "提交": ["commit", "flush", "persist"],
    # 网络 / 路由 / 控制器 / 中间件
    "中间件": ["middleware", "interceptor", "filter", "pipeline"],
    "拦截器": ["interceptor", "middleware", "filter"],
    "路由": ["router", "route", "routing", "endpoint", "dispatch"],
    "控制器": ["controller", "handler", "service", "action"],
    "接口": ["api", "interface", "endpoint", "controller", "handler"],
    # 序列化 / 编码 / 解码
    "序列化": ["serialize", "serializer", "encode", "encoder", "json", "dumps", "marshal"],
    "反序列化": ["deserialize", "decode", "decoder", "loads", "unmarshal", "parse"],
    "解码": ["decode", "decoder", "deserialize", "unmarshal"],
    "编码": ["encode", "encoder", "serialize", "charset"],
    # 配置 / 环境变量
    "配置": ["config", "configuration", "settings", "options", "preferences"],
    "环境变量": ["environ", "env", "environment", "dotenv"],
    # 重试 / 超时 / 异常 / 熔断
    "重试": ["retry", "backoff", "attempt", "reconnect"],
    "超时": ["timeout", "deadline", "timed_out"],
    "熔断": ["circuit_breaker", "breaker", "fallback"],
    "异常": ["exception", "error", "fault", "raise", "catch"],
    # 英文核心技术词映射到代码别名与中文
    "authenticate": ["auth", "authenticator", "jwt", "鉴权", "认证"],
    "authenticator": ["authenticate", "auth", "jwt", "鉴权"],
    "auth": ["authenticate", "authenticator", "jwt", "bearer", "鉴权", "认证"],
    "jwt": ["token", "payload", "decode_token", "sign_token", "令牌"],
    "limiter": ["rate_limit", "token_bucket", "ratelimit", "限流"],
    "ratelimit": ["rate_limit", "limiter", "token_bucket", "限流"],
    "pool": ["connection_pool", "acquire_connection", "连接池"],
    "transaction": ["rollback", "commit", "tx", "事务"],
    "rollback": ["revert", "abort", "回滚"],
    "commit": ["提交", "persist", "flush"],
    "contextmanager": ["__enter__", "__exit__", "scope", "context", "上下文管理器"],
    "database": ["db", "sql", "数据库"],
    "cache": ["lru", "eviction", "invalidate", "缓存"],
    "invalidate": ["evict", "expire", "失效", "淘汰"],
    "serializer": ["serialize", "json", "marshal", "序列化"],
    "config": ["settings", "env", "environ", "配置"],
}


class AdaptiveConceptMiner:
    """从被索引的代码库与文档中挖掘拓扑概念关联。"""

    def __init__(self) -> None:
        self.co_occurrence: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.stop_words = frozenset({"the", "in", "and", "is", "for", "with", "from", "that", "this", "app", "file", "py", "rs", "go", "ts", "js"})

    def mine(self, files: Sequence[IndexableFile], sample_texts: list[str] | None = None) -> dict[str, list[str]]:
        """从文件集合和抽样文本中挖掘局部高频概念图。"""
        # 1. 从文件路径与层级结构中挖掘关联
        for f in files:
            path = f.path
            parts = [p.lower() for p in path.parts if p.lower() not in self.stop_words and len(p) >= 3]
            for i, p1 in enumerate(parts):
                tokens1 = split_identifier(p1)
                for j, p2 in enumerate(parts):
                    if i != j:
                        tokens2 = split_identifier(p2)
                        for t1 in tokens1:
                            if len(t1) >= 3 and t1 not in self.stop_words:
                                for t2 in tokens2:
                                    if len(t2) >= 3 and t2 != t1 and t2 not in self.stop_words:
                                        self.co_occurrence[t1][t2] += 2

        # 2. 从抽样文本中挖掘类名与函数共现
        if sample_texts:
            class_func_pattern = re.compile(
                r"\b(?:class|def|fn|func|interface|struct|type)\s+([a-zA-Z0-9_]{3,})\b"
            )
            for text in sample_texts[:300]:
                symbols = class_func_pattern.findall(text)
                if len(symbols) >= 2:
                    for s1 in symbols:
                        tokens1 = split_identifier(s1)
                        for s2 in symbols:
                            if s1 != s2:
                                tokens2 = split_identifier(s2)
                                for t1 in tokens1:
                                    for t2 in tokens2:
                                        if t1 != t2 and len(t1) >= 3 and len(t2) >= 3:
                                            self.co_occurrence[t1][t2] += 1

        # 3. 生成Top-K关联图
        concept_graph: dict[str, list[str]] = {}
        for term, neighbors in self.co_occurrence.items():
            sorted_neighbors = sorted(neighbors.items(), key=lambda x: x[1], reverse=True)
            top_terms = [n for n, score in sorted_neighbors if score >= 2][:4]
            if top_terms:
                concept_graph[term] = top_terms

        return concept_graph


def merge_concept_maps(
    base: dict[str, list[str]], dynamic: dict[str, list[str]]
) -> dict[str, list[str]]:
    """合并基础种子概念与项目动态挖掘概念。"""
    merged: dict[str, list[str]] = {}
    all_keys = set(base.keys()) | set(dynamic.keys())
    for k in all_keys:
        lst = []
        seen = set()
        for item in base.get(k, []):
            if item not in seen:
                seen.add(item)
                lst.append(item)
        for item in dynamic.get(k, []):
            if item not in seen and item != k:
                seen.add(item)
                lst.append(item)
        if lst:
            merged[k] = lst
    return merged


def save_project_concepts(index_dir: Path, concepts: dict[str, list[str]]) -> None:
    """将项目自适应概念图谱持久化至索引目录。"""
    try:
        path = Path(index_dir) / CONCEPTS_FILE
        path.write_text(json.dumps(concepts, ensure_ascii=False, indent=2))
    except OSError:
        pass


def load_project_concepts(index_dir: Path | None = None) -> dict[str, list[str]]:
    """从索引目录加载项目概念图谱，并与基础词表融合。"""
    if not index_dir:
        return BASE_TECHNICAL_CONCEPTS
    path = Path(index_dir) / CONCEPTS_FILE
    if not path.exists():
        return BASE_TECHNICAL_CONCEPTS
    try:
        data = json.loads(path.read_text())
        if isinstance(data, dict):
            return merge_concept_maps(BASE_TECHNICAL_CONCEPTS, data)
        return BASE_TECHNICAL_CONCEPTS
    except (OSError, ValueError):
        return BASE_TECHNICAL_CONCEPTS
