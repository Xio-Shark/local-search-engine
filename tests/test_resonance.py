from __future__ import annotations

from lse.resonance import extract_evidence_spans


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
