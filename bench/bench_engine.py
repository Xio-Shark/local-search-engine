"""lse 性能基准测试与消融实验套件 (Benchmark & Ablation Suite)。

度量指标：
1. 索引吞吐量 (docs/s, MB/s)
2. 索引膨胀比 (Index Bytes / Corpus Bytes)
3. 增量更新延迟 (无变更毫秒级短路 vs 局部变更)
4. 查询延迟分布 (p50, p90, p99 ms)
5. 动态证据区间 vs 固定 512 字符 Chunking 的上下文 Token 节省比
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from pathlib import Path

from lse.indexer import IndexEngine
from lse.searcher import SearchEngine


def generate_benchmark_corpus(target_dir: Path, num_docs: int = 500) -> tuple[int, int]:
    """生成包含代码、中英文档、配置和混合标识符的基准测试语料。"""
    target_dir.mkdir(parents=True, exist_ok=True)
    total_bytes = 0

    templates = [
        (
            "app_{i}.py",
            """# Python 微服务模块 {i}
import os
import sys
from typing import Optional

class UserManager{i}:
    \"\"\"用户身份认证与鉴权管理器。\"\"\"

    def __init__(self, db_conn: str = "postgresql://localhost/prod_{i}") -> None:
        self.db_conn = db_conn
        self.retry_budget = 3

    def authenticateUserToken(self, user_token: str, client_ip: str) -> bool:
        # 校验 JWT 令牌与签名验证
        if not user_token:
            raise ValueError("Invalid userToken exception")
        print(f"Verifying token for IP: {{client_ip}}")
        # 处理超时与重试
        for attempt in range(self.retry_budget):
            try:
                return True
            except TimeoutError:
                continue
        return False
""",
        ),
        (
            "doc_{i}.md",
            """# 系统架构设计规范文档 第 {i} 卷

## 1. 总体设计原则

本项目采用多流倒排索引与符号感知证据提取机制。
重点支持大规模知识库、个人笔记与分布式代码仓库的高速检索。

## 2. 存储与内存模型

在倒排索引构建过程中，避免全量文本重复存入索引目录，借助零存储（Zero-Storage）架构，
正文只保留在本地磁盘，倒排仅负责词项位置映射与 BM25 评分。
这使得索引膨胀率大幅降低，极大缓解了 Page Cache 换入换出抖动。
""",
        ),
        (
            "config_{i}.toml",
            """[server_{i}]
host = "127.0.0.1"
port = 80{i:02d}
environment = "production"
timeout_ms = 5000
enable_ssl = true
cluster_nodes = ["node-a", "node-b", "node-c"]
""",
        ),
    ]

    count = 0
    for idx in range(num_docs):
        tmpl_name, tmpl_content = templates[idx % len(templates)]
        file_path = target_dir / tmpl_name.format(i=idx)
        content = tmpl_content.format(i=idx)
        file_path.write_text(content, encoding="utf-8")
        total_bytes += len(content.encode("utf-8"))
        count += 1

    return count, total_bytes


def run_benchmark():
    print("=" * 70)
    print("🚀 开始 lse 综合性能基准测试与消融实验")
    print("=" * 70)

    with tempfile.TemporaryDirectory() as td:
        base_dir = Path(td)
        corpus_dir = base_dir / "corpus"
        index_dir = base_dir / "index"

        # 1. 生成基准测试语料 (600 个混合文档)
        t0 = time.perf_counter()
        doc_count, corpus_bytes = generate_benchmark_corpus(corpus_dir, num_docs=600)
        t1 = time.perf_counter()
        print(f"📦 语料准备完成: {doc_count} 个文档, {corpus_bytes / 1024:.2f} KB (耗时 {(t1-t0)*1000:.1f}ms)")

        # 2. 评测全量索引吞吐
        engine = IndexEngine(index_dir)
        t_start = time.perf_counter()
        status = engine.build([corpus_dir])
        t_build = time.perf_counter() - t_start

        throughput_docs = doc_count / t_build
        throughput_mb = (corpus_bytes / (1024 * 1024)) / t_build
        index_size = status.index_bytes
        expansion_ratio = (index_size / corpus_bytes) * 100 if corpus_bytes else 0

        print("\n📊 1. 全量构建基准 (Build Benchmark)")
        print(f"   • 文档数量:        {doc_count:,} 个")
        print(f"   • 语料大小:        {corpus_bytes / 1024:.2f} KB")
        print(f"   • 索引构建耗时:    {t_build * 1000:.2f} ms")
        print(f"   • 索引吞吐量:      {throughput_docs:.1f} docs/s ({throughput_mb:.2f} MB/s)")
        print(f"   • 索引目录体积:    {index_size / 1024:.2f} KB")
        print(f"   • 索引膨胀率:      {expansion_ratio:.2f}% (零存储架构实测)")

        # 3. 评测增量更新性能 (0 变更短路 vs 局部变更)
        t_up0 = time.perf_counter()
        engine.update([corpus_dir])
        t_up0_cost = (time.perf_counter() - t_up0) * 1000

        # 修改 5 个文件
        for i in range(5):
            p = corpus_dir / f"app_{i * 3}.py"
            if p.exists():
                p.write_text(p.read_text() + "\n# updated content touch", encoding="utf-8")

        t_up5 = time.perf_counter()
        engine.update([corpus_dir])
        t_up5_cost = (time.perf_counter() - t_up5) * 1000

        print("\n🔄 2. 增量更新基准 (Incremental Update Benchmark)")
        print(f"   • 无修改全盘扫描耗时: {t_up0_cost:.2f} ms (单趟元数据短路)")
        print(f"   • 5 个文件变更增量耗时: {t_up5_cost:.2f} ms")

        # 4. 评测查询延迟分布 (p50, p90, p99)
        searcher = SearchEngine(index_dir)
        test_queries = [
            "authenticateUserToken",
            "零存储架构",
            "UserManager",
            "timeout_ms AND enable_ssl",
            "ext:py authenticateUserToken",
            "知识库 架构设计",
            "retry_budget",
            "cluster_nodes",
            "doc_type:code retry",
            "分布式代码仓库",
        ]

        latencies = []
        for _ in range(20):
            for q in test_queries:
                tq0 = time.perf_counter()
                res = searcher.search(q, limit=10)
                latencies.append((time.perf_counter() - tq0) * 1000)

        latencies.sort()
        p50 = latencies[int(len(latencies) * 0.50)]
        p90 = latencies[int(len(latencies) * 0.90)]
        p99 = latencies[int(len(latencies) * 0.99)]

        print("\n⚡ 3. 查询延迟基准 (Query Latency Distribution)")
        print(f"   • 测试总查询数:    {len(latencies)} 次")
        print(f"   • 中位数延迟 (p50): {p50:.2f} ms")
        print(f"   • 90 分位延迟 (p90): {p90:.2f} ms")
        print(f"   • 99 分位延迟 (p99): {p99:.2f} ms")

        # 5. 消融实验：动态证据跨度 (Spans) vs 固定 512 字符分块 (Fixed Chunking)
        print("\n🔬 4. 消融实验：动态证据区间 vs 固定 512 字符分块 (Ablation)")
        res_sample = searcher.search("authenticateUserToken", limit=5)
        total_raw_chars = 0
        total_span_chars = 0
        fixed_chunk_chars = 512 * min(len(res_sample.hits), 5)

        for h in res_sample.hits:
            p = Path(h.path)
            if p.exists():
                total_raw_chars += len(p.read_text())
            for s in h.spans:
                total_span_chars += len(s.text)

        token_savings = (
            (1.0 - (total_span_chars / max(fixed_chunk_chars, 1))) * 100
            if fixed_chunk_chars > 0
            else 0.0
        )
        print(f"   • 原始文档全量字符: {total_raw_chars} 字符")
        print(f"   • 固定窗口等价字符: {fixed_chunk_chars} 字符 (512 字符 × {len(res_sample.hits)})")
        print(f"   • 动态自适应证据跨度: {total_span_chars} 字符 (语法完整闭合块)")
        print(f"   • LLM 上下文节省比:   {token_savings:.1f}%")
        print("=" * 70)


if __name__ == "__main__":
    run_benchmark()
