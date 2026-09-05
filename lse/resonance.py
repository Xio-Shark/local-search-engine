"""动态局部共振证据区间求解器 (Dynamic Evidence Resonance Spans)。

创新理念：
消灭机械死板的固定 Chunking。在文档连续流形上，利用多尺度高斯平滑波函数，
动态求解查询关键词在文档中的“局部能量共振极大值区间”，自适应输出紧凑且结构完整的证据跨度。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class EvidenceSpan:
    """动态涌现的局部证据区间。"""

    start_line: int
    end_line: int
    breadcrumbs: str  # 所属章节/符号路径，如 "# 核心架构 > ## 倒排索引"
    confidence: float
    text: str
    highlighted_text: str = ""


# Markdown 标题识别
_MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")
# Python / 代码块识别
_CODE_BLOCK_RE = re.compile(r"^\s*(class|def|func|function|public|private)\s+([a-zA-Z0-9_]+)")


def extract_evidence_spans(
    content: str,
    query_terms: Sequence[str],
    max_spans: int = 3,
    sigma: float = 2.0,
    window_radius: int = 3,
) -> list[EvidenceSpan]:
    """从文本内容中求解并提取动态证据区间。

    参数：
    - content: 文档完整原文
    - query_terms: 查询词元列表
    - max_spans: 最多返回的高共振证据段数量
    - sigma: 高斯平滑核标准差
    - window_radius: 局部能量共振窗口半宽
    """
    if not content or not query_terms:
        return []

    lines = content.splitlines()
    num_lines = len(lines)
    if num_lines == 0:
        return []

    # 1. 维护章节面包屑上下文（行级映射）
    line_breadcrumbs: list[str] = [""] * num_lines
    heading_stack: list[tuple[int, str]] = []  # (level, title)

    for idx, line in enumerate(lines):
        line_clean = line.strip()
        h_match = _MD_HEADING_RE.match(line_clean)
        if h_match:
            level = len(h_match.group(1))
            title = h_match.group(2).strip()
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, title))
        elif not heading_stack:
            c_match = _CODE_BLOCK_RE.match(line_clean)
            if c_match:
                symbol = f"{c_match.group(1)} {c_match.group(2)}"
                heading_stack.append((1, symbol))

        if heading_stack:
            line_breadcrumbs[idx] = " > ".join(h[1] for h in heading_stack)

    # 2. 计算每行词项命中基础能量 E(i)
    # 词项长度越长、信息量越大，分配越高的瞬时能量权重
    norm_terms = [t.lower().strip() for t in query_terms if t.strip()]
    if not norm_terms:
        return []

    raw_energy = [0.0] * num_lines
    for idx, line in enumerate(lines):
        lower_line = line.lower()
        for term in norm_terms:
            count = lower_line.count(term)
            if count > 0:
                # 能量权重对数递增
                weight = math.log1p(len(term)) * min(count, 3)
                raw_energy[idx] += weight

    # 3. 高斯滑动窗口连续波函数平滑
    smoothed_energy = [0.0] * num_lines
    for idx in range(num_lines):
        if raw_energy[idx] == 0:
            # 局部有能量才展开扩散
            has_local = any(
                raw_energy[k] > 0
                for k in range(max(0, idx - window_radius), min(num_lines, idx + window_radius + 1))
            )
            if not has_local:
                continue

        total_weight = 0.0
        acc_energy = 0.0
        for offset in range(-window_radius, window_radius + 1):
            k = idx + offset
            if 0 <= k < num_lines:
                kernel = math.exp(- (offset ** 2) / (2.0 * sigma * sigma))
                acc_energy += raw_energy[k] * kernel
                total_weight += kernel
        smoothed_energy[idx] = acc_energy / max(total_weight, 1e-6)

    # 4. 寻找局部波峰极大值点与连通证据区间
    peaks: list[tuple[float, int]] = []
    threshold = 0.15 * max(smoothed_energy) if max(smoothed_energy) > 0 else 0.0
    if threshold <= 0:
        return []

    for idx in range(num_lines):
        val = smoothed_energy[idx]
        if val > threshold:
            # 是否局部波峰
            left = smoothed_energy[idx - 1] if idx > 0 else 0
            right = smoothed_energy[idx + 1] if idx + 1 < num_lines else 0
            if val >= left and val >= right:
                peaks.append((val, idx))

    # 按波峰能量降序排列
    peaks.sort(key=lambda p: p[0], reverse=True)

    spans: list[EvidenceSpan] = []
    covered_lines: set[int] = set()

    for peak_energy, center_line in peaks:
        if center_line in covered_lines:
            continue

        # 向两侧动态延伸证据区间，直到能量跌落至谷底或遇到自然段落空行
        start_l = center_line
        while start_l > 0 and smoothed_energy[start_l - 1] > threshold * 0.4:
            start_l -= 1
            if lines[start_l].strip() == "":
                break

        end_l = center_line
        while end_l < num_lines - 1 and smoothed_energy[end_l + 1] > threshold * 0.4:
            end_l += 1
            if lines[end_l].strip() == "":
                break

        # 边界修剪与约束
        span_range = range(start_l, end_l + 1)
        for ln in span_range:
            covered_lines.add(ln)

        span_lines = lines[start_l : end_l + 1]
        span_text = "\n".join(span_lines).strip()
        if not span_text:
            continue

        breadcrumb = line_breadcrumbs[center_line] or (line_breadcrumbs[start_l] if start_l < num_lines else "")
        confidence = min(1.0, peak_energy / (max(smoothed_energy) + 1e-6))

        # ANSI 高亮
        highlighted = _highlight_terms(span_text, norm_terms)

        spans.append(
            EvidenceSpan(
                start_line=start_l + 1,  # 1-indexed
                end_line=end_l + 1,
                breadcrumbs=breadcrumb,
                confidence=round(confidence, 3),
                text=span_text,
                highlighted_text=highlighted,
            )
        )

        if len(spans) >= max_spans:
            break

    # 按行号自上而下排序
    spans.sort(key=lambda s: s.start_line)
    return spans


def _highlight_terms(text: str, terms: list[str]) -> str:
    """对证据段内的关键词进行 ANSI 醒目高亮。"""
    if not terms or not text:
        return text
    sorted_terms = sorted(set(terms), key=len, reverse=True)
    pattern = re.compile("(" + "|".join(re.escape(t) for t in sorted_terms if t) + ")", re.IGNORECASE)
    return pattern.sub(r"\033[1;33m\1\033[0m", text)
