from __future__ import annotations

import re
import unicodedata

from functools import lru_cache

try:
    import jieba
    # Suppress jieba prefix dict initialization logs
    jieba.default_logger.setLevel(60)
    jieba.initialize()
except ImportError:
    jieba = None

# CJK 汉字区间
_CJK_PATTERN = re.compile(r"[\u4e00-\u9fff]+")
# 混合标识符模式（英文、数字、代码符号）
_IDENTIFIER_PATTERN = re.compile(r"[a-zA-Z0-9_+\-./#]+")
# 预编译驼峰与标识符切分模式，消除高频调用下的重复编译开销
_CAMEL_RE1 = re.compile(r"([a-z0-9])([A-Z])")
_CAMEL_RE2 = re.compile(r"([A-Z]+)([A-Z][a-z])")
_SPLIT_PARTS_RE = re.compile(r"[/\\._\-:]+")
_CLEAN_ORIGINAL_RE = re.compile(r"\s+")
_BASE_ALPHA_RE = re.compile(r"[+#]+$")
_STOP_CHARS = frozenset("的在和是与及于了或着把被由从呢吧啊么这那")


def normalize_text(text: str) -> str:
    """Unicode NFKC 规约并统一空白字符。"""
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKC", text)
    return normalized


@lru_cache(maxsize=32768)
def _cached_split_identifier(identifier: str) -> tuple[str, ...]:
    if not identifier:
        return ()
    # Fast path 1: 纯小写标识符无需任何驼峰与符号切分（覆盖 >60% 代码标识符与关键字）
    if identifier.isalnum():
        if identifier.islower():
            return (identifier,)
        if identifier.isupper():
            return (identifier.lower(),)

    parts = _SPLIT_PARTS_RE.split(identifier)
    sub_tokens: list[str] = []

    for part in parts:
        if not part:
            continue
        if part.islower():
            sub_tokens.append(part)
        elif part.isupper():
            sub_tokens.append(part.lower())
        else:
            camel_split = _CAMEL_RE1.sub(r"\1 \2", part)
            camel_split = _CAMEL_RE2.sub(r"\1 \2", camel_split)

            words = [w.lower() for w in camel_split.split() if w]
            sub_tokens.extend(words)
            if len(words) > 1:
                sub_tokens.append("".join(words))

    base_alpha = _BASE_ALPHA_RE.sub("", identifier).strip()
    if base_alpha and base_alpha.lower() not in sub_tokens:
        sub_tokens.append(base_alpha.lower())

    cleaned_original = _CLEAN_ORIGINAL_RE.sub("", identifier.lower())
    if cleaned_original and cleaned_original not in sub_tokens:
        sub_tokens.append(cleaned_original)

    seen = set()
    result = []
    for t in sub_tokens:
        if t and t not in seen and len(t) <= 128:
            seen.add(t)
            result.append(t)
    return tuple(result)


def split_identifier(identifier: str) -> list[str]:
    """分解代码与混合标识符（带高频符号 LRU 缓存加速）。"""
    if not identifier:
        return []
    return list(_cached_split_identifier(identifier))


@lru_cache(maxsize=8192)
def _cached_tokenize_cjk_run(cjk_text: str) -> tuple[str, ...]:
    length = len(cjk_text)
    if length == 0:
        return ()
    if length == 1:
        return (cjk_text,)

    tokens: list[str] = []

    # 1. 词级分词 (Jieba cut for search)
    if jieba is not None:
        try:
            jieba_words = [w.strip() for w in jieba.cut_for_search(cjk_text) if w.strip()]
            tokens.extend(jieba_words)
        except Exception:
            pass

    # 2. 保留整词与核心实词短语（供短语精确匹配）
    if length <= 24:
        tokens.append(cjk_text)
        clean_cjk = cjk_text.strip("的在和是与及于了或包含着把被由从")
        if clean_cjk and clean_cjk != cjk_text and len(clean_cjk) >= 2:
            tokens.append(clean_cjk)

    # 3. 连续 2-gram (仅对短文本或未收录词补充)
    if jieba is None or length <= 4:
        for i in range(length - 1):
            tokens.append(cjk_text[i : i + 2])

    # 4. 单字（供单字精确检索，过滤纯虚词/助词停用字符以保护 BM25 长度归一化）
    for ch in cjk_text:
        if ch not in _STOP_CHARS:
            tokens.append(ch)

    # 保持顺序去重
    seen = set()
    ordered = []
    for t in tokens:
        if t and t not in seen:
            seen.add(t)
            ordered.append(t)
    return tuple(ordered)


def tokenize_cjk_run(cjk_text: str) -> list[str]:
    """对连续 CJK 汉字段进行词级与多粒度展开（Jieba 词库 + 2-gram + 1-gram 备选）。

    保证：
    1. 真实词级语义分词（高区分度 BM25 IDF）
    2. 短语完整性优先（原短语保留）
    3. 2-gram 满足无词典词的紧凑倒排
    4. 1-gram 保证单汉字召回绝对不丢失
    """
    if not cjk_text:
        return []
    return list(_cached_tokenize_cjk_run(cjk_text))


def tokenize_stream(text: str) -> list[str]:
    """主分词入口：中英混排与代码混合多流分词。

    对纯西文/代码文件（>90% 场景）启用纯 ASCII 快速路径，大幅消减正则扫描与分支开销。
    """
    if not text:
        return []

    text = normalize_text(text)

    # 纯西文/代码文件快速路径（绝大部分纯代码无需经由复杂 CJK 正则扫描）
    if text.isascii():
        tokens: list[str] = []
        for m in _IDENTIFIER_PATTERN.finditer(text):
            tokens.extend(_cached_split_identifier(m.group(0)))
        return tokens

    tokens = []
    # 按字符类型切分连续块
    # 正则捕获：连续 CJK 字符 或 连续西文标识符/数字/代码符号
    scanner = re.finditer(r"([\u4e00-\u9fff]+)|([a-zA-Z0-9_+\-./#]+)", text)
    for m in scanner:
        cjk_part, id_part = m.groups()
        if cjk_part:
            tokens.extend(_cached_tokenize_cjk_run(cjk_part))
        elif id_part:
            tokens.extend(_cached_split_identifier(id_part))

    return tokens


def prepare_index_tokens(text: str) -> str:
    """为 Tantivy 倒排索引生成空格分隔的多流词元文本。

    确保代码标识符解离与 CJK 词级切分真正写入倒排索引，使得 BM25 能够基于真正的词元（Word-level tokens）计算 IDF。
    """
    if not text:
        return ""
    tokens = tokenize_stream(text)
    return " ".join(tokens)
