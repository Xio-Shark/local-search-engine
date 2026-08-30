"""搜索引擎：BM25 查询 + 高亮 + 字段过滤。

查询输入直接交给 tantivy parse_query；对形如 `ext:md filename:foo` 的
字段过滤，tantivy 原生支持 `field:value` 语法。返回自定义 SearchHit 列表。
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

# 匹配 field:value 前缀（如 ext:md、filename:readme.md、mtime:2025-01-01..2025-12-31）
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

        translated = self._translate_query(query)
        expanded = self._expand_cjk_query(translated)
        parsed = self.index.parse_query(expanded, DEFAULT_SEARCH_FIELDS)
        hits = searcher.search(parsed, min(limit, 1000))

        results = self._to_hits(searcher, hits, query)
        elapsed_ms = int((datetime.now() - start).total_seconds() * 1000)
        return SearchResult(
            query=query,
            hits=results,
            total_matches=hits.count,
            elapsed_ms=elapsed_ms,
        )

    def _expand_cjk_query(self, query: str) -> str:
        """把查询中的连续 CJK 段切成 2-gram 并用 OR 连接。

        索引侧 content 用 ngram(2,2)，查询词若按整串隐式 AND 会导致
        长中文查询必为 0 命中；这里拆成 OR 让 BM25 打分排序即可。
        字段前缀（filename:/ext: 等）与英文原样保留。
        """
        if not query:
            return query

        def expand(match: re.Match[str]) -> str:
            segment = match.group(0)
            if len(segment) < 4:
                return segment
            grams = [segment[i : i + 2] for i in range(len(segment) - 1)]
            return " OR ".join(grams)

        # 匹配连续 CJK（含中文标点隔离），不含字段前缀部分
        cjk_segment_re = re.compile(r"[\u4e00-\u9fff]{4,}")
        return cjk_segment_re.sub(expand, query)

    def _translate_query(self, query: str) -> str:
        """把 `ext:md type:note` 等别名翻译为 schema 字段名。"""

        def replace(match: re.Match[str]) -> str:
            field = match.group(1)
            target = self._FIELD_ALIASES.get(field.lower())
            if target and target != field.lower():
                return target + ":"
            return match.group(0)

        return _FIELD_PREFIX_RE.sub(replace, query)

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
            hits.append(
                SearchHit(
                    path=path_str,
                    filename=Path(path_str).name,
                    extension=doc.get_first("extension") or "",
                    doc_type=doc.get_first("doc_type") or "",
                    size=doc.get_first("size") or 0,
                    mtime=mtime,
                    score=score,
                    snippets=self._snippets(content, query),
                )
            )
        return hits

    def _snippets(self, content: str, query: str) -> list[str]:
        """从内容提取含查询词片段（简单窗口截取），cli 端负责高亮显示。"""
        if not content:
            return []
        terms = _query_terms(query)
        if not terms:
            return [content[: SNIPPET_CONTEXT_CHARS * 2]]
        lowered = content.lower()
        hits_positions: list[int] = []
        for term in terms:
            start = 0
            while True:
                idx = lowered.find(term, start)
                if idx == -1:
                    break
                hits_positions.append(idx)
                start = idx + len(term)
        if not hits_positions:
            return [content[: SNIPPET_CONTEXT_CHARS * 2]]
        # 取第一个命中位置的前后窗口
        center = min(hits_positions)
        start = max(0, center - SNIPPET_CONTEXT_CHARS)
        end = min(len(content), center + SNIPPET_CONTEXT_CHARS)
        snippet = content[start:end].replace("\n", " ").strip()
        if start > 0:
            snippet = "…" + snippet
        if end < len(content):
            snippet = snippet + "…"
        return [snippet]


def _query_terms(query: str) -> list[str]:
    """从查询提取用于高亮的词（简单切分：字母数字段与 CJK 段）。"""
    if not query:
        return []
    parts = re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+", query.lower())
    terms: list[str] = []
    for part in parts:
        if re.match(r"^[a-z0-9_]+$", part):
            terms.append(part)
        else:
            # CJK：按 2-gram 切（与索引 tokenizer 对齐）
            if len(part) == 1:
                terms.append(part)
            elif len(part) == 2:
                terms.append(part)
            else:
                terms.extend(part[i : i + 2] for i in range(len(part) - 1))
    return terms


def _parse_mtime(value) -> datetime:
    if value is None:
        return datetime.min
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromtimestamp(float(value))
    except (TypeError, ValueError):
        return datetime.min
