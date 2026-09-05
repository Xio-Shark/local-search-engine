"""代码与自然语言多流分词体系。

提供：
1. Code Tokenizer：智能解离驼峰命名 (camelCase)、蛇形命名 (snake_case)、代码路径与符号
2. CJK & Mixed Tokenizer：支持中英混排（如 "GPT-4o架构"、"C++多线程"）、精准词元提取与双字/单字平滑回退
3. 文本归一化 (NFKC + 大小写规约)
"""

from __future__ import annotations

import re
import unicodedata

# CJK 汉字区间
_CJK_PATTERN = re.compile(r"[\u4e00-\u9fff]+")
# 混合标识符模式（英文、数字、代码符号）
_IDENTIFIER_PATTERN = re.compile(r"[a-zA-Z0-9_+\-./#]+")


def normalize_text(text: str) -> str:
    """Unicode NFKC 规约并统一空白字符。"""
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKC", text)
    return normalized


def split_identifier(identifier: str) -> list[str]:
    """分解代码与混合标识符。

    例如：
    - 'localSearchEngine' -> ['local', 'search', 'engine', 'localsearchengine']
    - 'delta_codec_v2' -> ['delta', 'codec', 'v2', 'delta_codec_v2']
    - 'com.localengine.IndexManager' -> ['com', 'localengine', 'index', 'manager', 'indexmanager']
    - 'C++' -> ['c++']
    """
    if not identifier:
        return []

    # 预先剥离路径与点号符号
    parts = re.split(r"[/\\._\-:]+", identifier)
    sub_tokens: list[str] = []

    for part in parts:
        if not part:
            continue
        # 识别驼峰分词 (camelCase / PascalCase)
        # 在小写/数字与大写字母之间插入切分点
        camel_split = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", part)
        # 在连续大写字母与后续小写字母之间插入切分点 (如 XMLReader -> XML Reader)
        camel_split = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", camel_split)
        
        words = [w.lower() for w in camel_split.split() if w]
        sub_tokens.extend(words)
        if len(words) > 1:
            sub_tokens.append("".join(words))

    # 结果去重并包含原标识符归一化形式
    cleaned_original = re.sub(r"\s+", "", identifier.lower())
    if cleaned_original and cleaned_original not in sub_tokens:
        sub_tokens.append(cleaned_original)

    seen = set()
    result = []
    for t in sub_tokens:
        if t and t not in seen and len(t) <= 128:
            seen.add(t)
            result.append(t)
    return result


def tokenize_cjk_run(cjk_text: str) -> list[str]:
    """对连续 CJK 汉字段进行多粒度展开（整词 + 2-gram + 1-gram 备选）。

    保证：
    1. 短语完整性优先（原词最高权重）
    2. 2-gram 满足紧凑倒排
    3. 1-gram 保证单汉字召回不丢失
    """
    length = len(cjk_text)
    if length == 0:
        return []
    if length == 1:
        return [cjk_text]
    if length == 2:
        return [cjk_text, cjk_text[0], cjk_text[1]]

    tokens: list[str] = []
    # 1. 保留整词
    tokens.append(cjk_text)
    # 2. 连续 2-gram
    for i in range(length - 1):
        tokens.append(cjk_text[i : i + 2])
    # 3. 单字（供单汉字检索命中）
    for ch in cjk_text:
        tokens.append(ch)

    # 保持顺序去重
    seen = set()
    ordered = []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            ordered.append(t)
    return ordered


def tokenize_stream(text: str) -> list[str]:
    """主分词入口：中英混排与代码混合多流分词。

    适用于文档预处理与查询解析前的统一词元提取。
    """
    if not text:
        return []

    text = normalize_text(text)
    tokens: list[str] = []

    # 按字符类型切分连续块
    # 正则捕获：连续 CJK 字符 或 连续西文标识符/数字/代码符号
    scanner = re.finditer(r"([\u4e00-\u9fff]+)|([a-zA-Z0-9_+\-./#]+)", text)
    for m in scanner:
        cjk_part, id_part = m.groups()
        if cjk_part:
            tokens.extend(tokenize_cjk_run(cjk_part))
        elif id_part:
            tokens.extend(split_identifier(id_part))

    return tokens
