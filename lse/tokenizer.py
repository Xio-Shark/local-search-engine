from __future__ import annotations

import re
import unicodedata

try:
    import jieba
    # Suppress jieba prefix dict initialization logs
    jieba.default_logger.setLevel(60)
except ImportError:
    jieba = None

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

    # 针对带有语言符号后缀的标识符（如 C++, C#, F#），解离出基础字母以支持单字母语言检索
    base_alpha = re.sub(r"[+#]+$", "", identifier).strip()
    if base_alpha and base_alpha.lower() not in sub_tokens:
        sub_tokens.append(base_alpha.lower())

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
    """对连续 CJK 汉字段进行词级与多粒度展开（Jieba 词库 + 2-gram + 1-gram 备选）。

    保证：
    1. 真实词级语义分词（高区分度 BM25 IDF）
    2. 短语完整性优先（原短语保留）
    3. 2-gram 满足无词典词的紧凑倒排
    4. 1-gram 保证单汉字召回绝对不丢失
    """
    length = len(cjk_text)
    if length == 0:
        return []
    if length == 1:
        return [cjk_text]

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
    _STOP_CHARS = frozenset("的在和是与及于了或着把被由从呢吧啊么这那")
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


def prepare_index_tokens(text: str) -> str:
    """为 Tantivy 倒排索引生成空格分隔的多流词元文本。

    确保代码标识符解离与 CJK 词级切分真正写入倒排索引，使得 BM25 能够基于真正的词元（Word-level tokens）计算 IDF。
    """
    if not text:
        return ""
    tokens = tokenize_stream(text)
    return " ".join(tokens)
