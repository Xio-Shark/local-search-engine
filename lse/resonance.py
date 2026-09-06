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
# 多语言代码块/符号定义识别 (Python, Go, Rust, Java, JS/TS, C/C++)
_CODE_SYMBOL_RE = re.compile(
    r"^\s*(?:(?:export|pub|public|private|protected|async|static|final|const)\s+)*"
    r"(class|def|fn|func|function|struct|interface|trait|enum|type)\s+([a-zA-Z0-9_]+)"
)


def _analyze_structures(lines: list[str]) -> tuple[list[str], list[tuple[int, int] | None]]:
    """分析行级别结构符号面包屑与封闭块边界。

    返回：
    - line_breadcrumbs: 每行所属的分层面包屑（如 '用户认证模块 > class TokenValidator > def verify'）
    - line_blocks: 每行所属语法块的 (start_line, end_line) 起止闭包
    """
    num_lines = len(lines)
    breadcrumbs: list[str] = [""] * num_lines
    blocks: list[tuple[int, int] | None] = [None] * num_lines

    md_heading_stack: list[tuple[int, str]] = []
    symbol_stack: list[tuple[int, str, int]] = []  # (indent_or_depth, symbol_name, start_line)

    for idx, line in enumerate(lines):
        line_clean = line.strip()
        if not line_clean:
            # 继承上一行的面包屑
            if idx > 0:
                breadcrumbs[idx] = breadcrumbs[idx - 1]
            continue

        # 1. 检查 Markdown 标题
        h_match = _MD_HEADING_RE.match(line_clean)
        if h_match:
            level = len(h_match.group(1))
            title = h_match.group(2).strip()
            while md_heading_stack and md_heading_stack[-1][0] >= level:
                md_heading_stack.pop()
            md_heading_stack.append((level, title))
            # 标题出现时清空代码符号栈
            symbol_stack.clear()

        # 2. 检查代码符号 (class, def, fn, func, etc.)
        # 纯注释行不参与缩进层级弹栈判定（避免未缩进注释误破坏符号层级）
        is_comment = line_clean.startswith(("#", "//", "/*", "*"))
        indent = len(line) - len(line.lstrip())
        if not is_comment:
            while symbol_stack and indent <= symbol_stack[-1][0]:
                symbol_stack.pop()

        sym_match = _CODE_SYMBOL_RE.match(line)
        if sym_match:
            kind, name = sym_match.group(1), sym_match.group(2)
            symbol_str = f"{kind} {name}"
            while symbol_stack and indent <= symbol_stack[-1][0]:
                symbol_stack.pop()

            # 计算该语法块的自然闭包结束行
            block_end = idx
            if "{" in line:
                b_cnt = line.count("{") - line.count("}")
                for j in range(idx + 1, num_lines):
                    b_cnt += lines[j].count("{") - lines[j].count("}")
                    block_end = j
                    if b_cnt <= 0:
                        break
            else:
                for j in range(idx + 1, num_lines):
                    l_str = lines[j].strip()
                    if not l_str or l_str.startswith(("#", "//", "/*", "*")):
                        block_end = j
                        continue
                    l_ind = len(lines[j]) - len(lines[j].lstrip())
                    if l_ind <= indent:
                        break
                    block_end = j

            # 去除尾部空行
            while block_end > idx and not lines[block_end].strip():
                block_end -= 1

            symbol_stack.append((indent, symbol_str, idx, block_end))

        # 3. 汇总当前行面包屑
        parts = [h[1] for h in md_heading_stack] + [s[1] for s in symbol_stack]
        if parts:
            breadcrumbs[idx] = " > ".join(parts)

        if symbol_stack:
            top_start = symbol_stack[-1][2]
            top_end = symbol_stack[-1][3]
            blocks[idx] = (top_start, top_end)

    return breadcrumbs, blocks


def extract_evidence_spans(
    content: str,
    query_terms: Sequence[str],
    max_spans: int = 3,
    sigma: float = 2.0,
    window_radius: int = 3,
    term_weights: dict[str, float] | None = None,
) -> list[EvidenceSpan]:
    """从文本内容中求解并提取动态结构化证据区间。

    参数：
    - content: 文档完整原文
    - query_terms: 查询词元列表
    - max_spans: 最多返回的证据段数量
    - sigma: 平滑核标准差
    - window_radius: 局部能量共振窗口半宽
    - term_weights: 可选的词项 IDF 权重字典，替代简单字符长度
    """
    if not content or not query_terms:
        return []

    lines = content.splitlines()
    num_lines = len(lines)
    if num_lines == 0:
        return []

    # 1. 结构与符号分析
    line_breadcrumbs, line_blocks = _analyze_structures(lines)

    norm_terms = [t.lower().strip() for t in query_terms if t.strip()]
    if not norm_terms:
        return []

    # 2. 计算每行命中能量与词项多样性
    raw_energy = [0.0] * num_lines
    line_hit_distinct = [0] * num_lines

    for idx, line in enumerate(lines):
        lower_line = line.lower()
        distinct_count = 0
        line_weight_sum = 0.0
        for term in norm_terms:
            count = lower_line.count(term)
            if count > 0:
                distinct_count += 1
                base_w = term_weights.get(term) if term_weights else None
                if base_w is None:
                    base_w = math.log1p(len(term))
                line_weight_sum += base_w * min(count, 3)

        if distinct_count > 0:
            line_hit_distinct[idx] = distinct_count
            # 多词共同命中赋予协同加权
            co_occur_boost = 1.0 + 0.3 * (distinct_count - 1)
            raw_energy[idx] = line_weight_sum * co_occur_boost

    # 3. 高斯加权平滑滤波
    smoothed_energy = [0.0] * num_lines
    for idx in range(num_lines):
        if raw_energy[idx] == 0:
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

    # 4. 寻找局部波峰
    peaks: list[tuple[float, int]] = []
    max_energy = max(smoothed_energy) if smoothed_energy else 0.0
    threshold = 0.15 * max_energy if max_energy > 0 else 0.0
    if threshold <= 0:
        return []

    for idx in range(num_lines):
        val = smoothed_energy[idx]
        if val > threshold:
            left = smoothed_energy[idx - 1] if idx > 0 else 0
            right = smoothed_energy[idx + 1] if idx + 1 < num_lines else 0
            if val >= left and val >= right:
                peaks.append((val, idx))

    peaks.sort(key=lambda p: p[0], reverse=True)

    spans: list[EvidenceSpan] = []
    covered_lines: set[int] = set()

    for peak_energy, center_line in peaks:
        if center_line in covered_lines:
            continue

        # 向两侧自适应延伸证据区间
        start_l = center_line
        blank_run = 0
        while start_l > 0 and smoothed_energy[start_l - 1] > threshold * 0.35:
            prev_line = lines[start_l - 1].strip()
            if _MD_HEADING_RE.match(prev_line):
                # 遇到上一级标题，将其包含作为本节起点后停止向上延伸
                start_l -= 1
                break
            if prev_line == "":
                blank_run += 1
                if blank_run >= 2:
                    break
            else:
                blank_run = 0
            start_l -= 1

        end_l = center_line
        blank_run = 0
        while end_l < num_lines - 1 and smoothed_energy[end_l + 1] > threshold * 0.35:
            next_line = lines[end_l + 1].strip()
            if _MD_HEADING_RE.match(next_line):
                # 遇到下一个标题，不跨越至下一个独立章节
                break
            if next_line == "":
                blank_run += 1
                if blank_run >= 2:
                    break
            else:
                blank_run = 0
            end_l += 1

        # 若命中了语法结构块（且跨度在 40 行内），自闭合吸附整个符号语法块
        if line_blocks[center_line]:
            block_start, block_end = line_blocks[center_line]
            if (block_end - block_start) <= 40:
                start_l = min(start_l, block_start)
                end_l = max(end_l, block_end)
            elif block_start < start_l and (end_l - block_start) <= 40:
                start_l = block_start

        # 规整：剔除首尾的空白行
        while start_l <= end_l and lines[start_l].strip() == "":
            start_l += 1
        while end_l >= start_l and lines[end_l].strip() == "":
            end_l -= 1
        if start_l > end_l:
            continue

        # 标记已覆盖
        for ln in range(start_l, end_l + 1):
            covered_lines.add(ln)

        span_lines = lines[start_l : end_l + 1]
        span_text = "\n".join(span_lines).strip()
        if not span_text:
            continue

        breadcrumb = line_breadcrumbs[center_line] or line_breadcrumbs[start_l]
        confidence = min(1.0, peak_energy / (max_energy + 1e-6))

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

    spans.sort(key=lambda s: s.start_line)

    # 智能合并同一文件内紧邻的碎片证据段（消除类/函数内仅有 2~5 行空隙导致的上下文割裂）
    merged_spans: list[EvidenceSpan] = []
    for s in spans:
        if not merged_spans:
            merged_spans.append(s)
            continue
        prev = merged_spans[-1]
        # 若两段重叠或间隔 <= 6 行，且融合后总行数不超过 50 行，融合为自闭合完整证据段
        if s.start_line <= prev.end_line + 6 and (max(s.end_line, prev.end_line) - prev.start_line + 1) <= 50:
            new_end = max(s.end_line, prev.end_line)
            combined_lines = lines[prev.start_line - 1 : new_end]
            combined_text = "\n".join(combined_lines).strip()
            bc = prev.breadcrumbs if len(prev.breadcrumbs) >= len(s.breadcrumbs) else s.breadcrumbs
            merged_spans[-1] = EvidenceSpan(
                start_line=prev.start_line,
                end_line=new_end,
                breadcrumbs=bc,
                confidence=max(prev.confidence, s.confidence),
                text=combined_text,
                highlighted_text=_highlight_terms(combined_text, norm_terms),
            )
        else:
            merged_spans.append(s)

    return merged_spans[:max_spans]


def _highlight_terms(text: str, terms: list[str]) -> str:
    """对证据段内的关键词进行 ANSI 醒目高亮。"""
    if not terms or not text:
        return text
    sorted_terms = sorted(set(terms), key=len, reverse=True)
    pattern = re.compile("(" + "|".join(re.escape(t) for t in sorted_terms if t) + ")", re.IGNORECASE)
    return pattern.sub(r"\033[1;33m\1\033[0m", text)
