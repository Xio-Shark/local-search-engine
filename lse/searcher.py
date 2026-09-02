"""搜索引擎：BM25 查询 + 高亮 + 字段过滤。

查询输入交由 tantivy parse_query，结合 CJK 扩展、字段别名翻译、
数值/日期范围查询转换与 fast-field 原生排序。返回自定义 SearchHit 列表。
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import tantivy

from .config import (
    DEFAULT_INDEX_DIR,
    DEFAULT_SEARCH_LIMIT,
    DEFAULT_SEARCH_FIELDS,
    SNIPPET_CONTEXT_CHARS,
    SNIPPET_MAX_COUNT,
)
from .indexer import IndexEngine
from .model import SearchHit, SearchResult
from .schema import register_tokenizers

# 匹配 field: 前缀（如 ext:md、filename:readme.md）
_FIELD_PREFIX_RE = re.compile(r"([a-zA-Z_]+):")


class SearchEngine:
    """查询入口。

    与 IndexEngine 共享同一 index_dir；查询前 reload 以看到最新提交。
    查询 DSL 中常用别名自动翻译：ext→extension、type→doc_type、name→filename。
    """

    _FIELD_ALIASES = {
        "ext": "extension",
        "type": "doc_type",
        "name": "filename",
        "filename": "filename",
        "path": "path",
        "size": "size",
        "mtime": "mtime",
        "content": "content",
    }

    def __init__(self, index_dir: Path = DEFAULT_INDEX_DIR) -> None:
        self.index_dir = Path(index_dir)
        self.engine = IndexEngine(self.index_dir)
        self.index = self.engine.index
        # 每次打开索引后注册 tokenizer（不持久化），否则 parse_query 报未注册
        register_tokenizers(self.index)

    def search(self, query: str, limit: int = DEFAULT_SEARCH_LIMIT) -> SearchResult:
        start = datetime.now()
        if not query or not query.strip():
            return SearchResult(query=query, hits=[], total_matches=0, elapsed_ms=0)

        self.index.reload()
        searcher = self.index.searcher()

        # 1. 抽取 sort: 排序指令（如 sort:mtime, sort:size:asc）
        cleaned_query, sort_field, sort_order = self._extract_sort(query)

        # 2. 翻译别名与范围语法 (size:.. / mtime:..)
        translated = self._translate_query(cleaned_query)

        # 3. 对中文长词合理扩展（带括号与原短语加权，不污染布尔与字段过滤）
        expanded = self._expand_cjk_query(translated)

        # 4. 若去除排序指令后 query 为空，默认检索全部文档
        effective_query = expanded.strip() or "*"
        parsed = self.index.parse_query(
            effective_query,
            DEFAULT_SEARCH_FIELDS,
            conjunction_by_default=True,
        )

        # 5. 执行搜索（带排序或原生 BM25 相关性打分）
        limit_val = min(max(limit, 1), 1000)
        if sort_field:
            hits = searcher.search(parsed, limit_val, order_by_field=sort_field, order=sort_order)
        else:
            hits = searcher.search(parsed, limit_val)

        results = self._to_hits(searcher, hits, cleaned_query)
        elapsed_ms = int((datetime.now() - start).total_seconds() * 1000)
        return SearchResult(
            query=query,
            hits=results,
            total_matches=hits.count,
            elapsed_ms=elapsed_ms,
        )

    def _extract_sort(self, query: str) -> tuple[str, str | None, tantivy.Order]:
        """提取并在查询串中剥离 sort:field 指令。"""
        sort_match = re.search(r"\bsort:([a-zA-Z_]+)(?::(asc|desc))?\b", query, flags=re.IGNORECASE)
        sort_field = None
        sort_order = tantivy.Order.Desc
        if sort_match:
            field_name = sort_match.group(1).lower()
            direction = (sort_match.group(2) or "desc").lower()
            if field_name in ("mtime", "size"):
                sort_field = field_name
                sort_order = tantivy.Order.Asc if direction == "asc" else tantivy.Order.Desc
            query = query[:sort_match.start()] + " " + query[sort_match.end():]
            query = query.strip()
        return query, sort_field, sort_order

    def _expand_cjk_query(self, query: str) -> str:
        """对普通查询项中连续 >=4 字的 CJK 词进行扩展，同时保留短语高权重与双字召回。

        被引号包裹的短语、字段过滤表达式（如 ext:md、path:...）保持原样不变。
        扩展结果强制使用括号包裹，确保在 conjunction_by_default 下与其他条件保持 AND 语义。
        """
        if not query:
            return query

        pattern = re.compile(
            r'("[^"]*")|'                                  # Group 1: quoted string
            r'([a-zA-Z_]+:(?:\[[^\]]*\]|"[^"]*"|\S+))|'  # Group 2: field filter
            r'(\S+)'                                       # Group 3: plain term
        )

        out = []
        for m in pattern.finditer(query):
            quoted, field_filter, term = m.groups()
            if quoted:
                out.append(quoted)
            elif field_filter:
                out.append(field_filter)
            elif term:
                # 连续 CJK 汉字 >= 4 个字符且未包含操作符
                if re.fullmatch(r"[\u4e00-\u9fff]{4,}", term):
                    grams = [term[i : i + 2] for i in range(len(term) - 1)]
                    expanded = f'("{term}"^5 OR {" OR ".join(grams)})'
                    out.append(expanded)
                else:
                    out.append(term)

        return " ".join(out)

    def _translate_query(self, query: str) -> str:
        """翻译别名及范围语法。"""
        # 1. 字段别名翻译（ext->extension 等）
        def replace_alias(match: re.Match[str]) -> str:
            field = match.group(1)
            target = self._FIELD_ALIASES.get(field.lower())
            if target and target != field.lower():
                return target + ":"
            return match.group(0)

        query = _FIELD_PREFIX_RE.sub(replace_alias, query)

        # 2. size 范围翻译（支持 10KB..5MB 或 100..5000）
        def parse_bytes(val: str) -> int:
            val = val.strip().upper()
            if val.endswith("KB"):
                return int(float(val[:-2]) * 1024)
            elif val.endswith("MB"):
                return int(float(val[:-2]) * 1024 * 1024)
            elif val.endswith("GB"):
                return int(float(val[:-2]) * 1024 * 1024 * 1024)
            elif val.endswith("B"):
                return int(val[:-1])
            return int(val)

        def replace_size_range(m):
            start = parse_bytes(m.group(1)) if m.group(1) else "*"
            end = parse_bytes(m.group(2)) if m.group(2) else "*"
            return f"size:[{start} TO {end}]"

        query = re.sub(
            r"\bsize:(\d+(?:\.\d+)?(?:[KMGT]?B)?)\.\.(\d+(?:\.\d+)?(?:[KMGT]?B)?)\b",
            replace_size_range,
            query,
            flags=re.IGNORECASE,
        )

        # 3. mtime 日期范围翻译 (mtime:2025-01-01..2025-12-31)
        def replace_date_range(m):
            start = f"{m.group(1)}T00:00:00Z" if m.group(1) else "*"
            end = f"{m.group(2)}T23:59:59Z" if m.group(2) else "*"
            return f"mtime:[{start} TO {end}]"

        query = re.sub(
            r"\bmtime:(\d{4}-\d{2}-\d{2})\.\.(\d{4}-\d{2}-\d{2})\b",
            replace_date_range,
            query,
        )

        return query

    def _to_hits(self, searcher, search_result, query: str) -> list[SearchHit]:
        hits: list[SearchHit] = []
        for score, address in search_result.hits:
            doc = searcher.doc(address)
            try:
                path = doc.get_first("path")
                content = doc.get_first("content") or ""
            except (AttributeError, TypeError):
                continue
            path_str = str(path)
            mtime = _parse_mtime(doc.get_first("mtime"))
            try:
                score_val = float(score)
            except (TypeError, ValueError):
                score_val = 0.0
            hits.append(
                SearchHit(
                    path=path_str,
                    filename=Path(path_str).name,
                    extension=doc.get_first("extension") or "",
                    doc_type=doc.get_first("doc_type") or "",
                    size=doc.get_first("size") or 0,
                    mtime=mtime,
                    score=score_val,
                    snippets=self._snippets(content, query),
                )
            )
        return hits

    def _snippets(self, content: str, query: str) -> list[str]:
        """从内容提取含查询词片段（多窗口截取，合并重叠区域）。"""
        if not content:
            return []
        terms = _query_terms(query)
        if not terms:
            first_chunk = content[: SNIPPET_CONTEXT_CHARS * 2].replace("\n", " ").strip()
            return [first_chunk + ("…" if len(content) > len(first_chunk) else "")]

        lowered = content.lower()
        hits_positions: list[int] = []
        for term in terms:
            if not term:
                continue
            start = 0
            while True:
                idx = lowered.find(term.lower(), start)
                if idx == -1:
                    break
                hits_positions.append(idx)
                start = idx + max(len(term), 1)

        if not hits_positions:
            first_chunk = content[: SNIPPET_CONTEXT_CHARS * 2].replace("\n", " ").strip()
            return [first_chunk + ("…" if len(content) > len(first_chunk) else "")]

        hits_positions.sort()
        windows: list[tuple[int, int]] = []
        for pos in hits_positions:
            w_start = max(0, pos - SNIPPET_CONTEXT_CHARS)
            w_end = min(len(content), pos + SNIPPET_CONTEXT_CHARS)
            if windows and w_start <= windows[-1][1]:
                windows[-1] = (windows[-1][0], max(windows[-1][1], w_end))
            else:
                windows.append((w_start, w_end))
            if len(windows) >= SNIPPET_MAX_COUNT:
                break

        snippets: list[str] = []
        for w_start, w_end in windows[:SNIPPET_MAX_COUNT]:
            snippet_str = content[w_start:w_end].replace("\n", " ").strip()
            prefix = "…" if w_start > 0 else ""
            suffix = "…" if w_end < len(content) else ""
            snippets.append(f"{prefix}{snippet_str}{suffix}")

        return snippets


def _query_terms(query: str) -> list[str]:
    """从查询提取用于高亮和定位的搜索词，过滤字段前缀与操作符。"""
    if not query:
        return []
    # 过滤字段过滤表达式
    cleaned = re.sub(r"[a-zA-Z_]+:(?:\[[^\]]*\]|\"[^\"]*\"|\S+)", " ", query)
    # 过滤布尔操作符与括号符号
    cleaned = re.sub(r"\b(AND|OR|NOT)\b|[()\"^0-9]+", " ", cleaned)
    parts = re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+", cleaned.lower())
    terms: list[str] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if re.match(r"^[a-z0-9_]+$", part):
            terms.append(part)
        else:
            terms.append(part)
            if len(part) > 2:
                terms.extend(part[i : i + 2] for i in range(len(part) - 1))

    seen: set[str] = set()
    unique: list[str] = []
    for t in terms:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return unique


def _parse_mtime(value) -> datetime:
    if value is None:
        return datetime.min
    if isinstance(value, datetime):
        return value
    try:
        # Tantivy date fast field returns nanoseconds since epoch
        val_float = float(value)
        if val_float > 1e14:  # nanoseconds
            val_float = val_float / 1e9
        return datetime.fromtimestamp(val_float)
    except (TypeError, ValueError, OSError):
        return datetime.min
