"""搜索引擎：BM25 查询 + AST 解析 + 动态局部共振证据区间。

基于 Tantivy 索引与递归下降 AST 解析器，支持：
1. 形式化 DSL 编译与字段别名翻译 (ext, type, filename, size, mtime)
2. CJK 与代码混合词项自适应短语加权与容错展开
3. 基于能量波函数的动态连续证据区间提取 (Evidence Spans)，消灭固定分块截断
4. Fast-Field 原生排序与范围过滤
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path


from .config import (
    DEFAULT_INDEX_DIR,
    DEFAULT_SEARCH_FIELDS,
    DEFAULT_SEARCH_LIMIT,
    SNIPPET_CONTEXT_CHARS,
    SNIPPET_MAX_COUNT,
)
from .indexer import IndexEngine
from .model import SearchHit, SearchResult
from .query_ast import QueryCompiler
from .resonance import extract_evidence_spans
from .schema import register_tokenizers
from .tokenizer import tokenize_stream


class SearchEngine:
    """查询入口。

    与 IndexEngine 共享同一 index_dir；查询前 reload 以看到最新提交。
    """

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

        # 1. 形式化 AST 编译：提取排序指令、翻译别名与自适应展开
        compiler = QueryCompiler(query)
        compiled_query, sort_field, sort_order = compiler.compile()

        # 2. 若去除排序指令后 query 为空，默认检索全部文档
        effective_query = compiled_query.strip() or "*"
        parsed = self.index.parse_query(
            effective_query,
            DEFAULT_SEARCH_FIELDS,
            conjunction_by_default=True,
        )

        # 3. 执行搜索（带排序或原生 BM25 相关性打分）
        limit_val = min(max(limit, 1), 1000)
        if sort_field:
            hits = searcher.search(parsed, limit_val, order_by_field=sort_field, order=sort_order)
        else:
            hits = searcher.search(parsed, limit_val)

        results = self._to_hits(searcher, hits, query)
        elapsed_ms = int((datetime.now() - start).total_seconds() * 1000)
        return SearchResult(
            query=query,
            hits=results,
            total_matches=hits.count,
            elapsed_ms=elapsed_ms,
        )

    def _to_hits(self, searcher, search_result, query: str) -> list[SearchHit]:
        hits: list[SearchHit] = []
        terms = _query_terms(query)
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

            # 求解连续局部共振证据区间
            spans = extract_evidence_spans(content, terms)
            if spans:
                snippets = [s.text for s in spans]
            else:
                snippets = self._fallback_snippets(content, query)

            hits.append(
                SearchHit(
                    path=path_str,
                    filename=Path(path_str).name,
                    extension=doc.get_first("extension") or "",
                    doc_type=doc.get_first("doc_type") or "",
                    size=doc.get_first("size") or 0,
                    mtime=mtime,
                    score=score_val,
                    snippets=snippets,
                    spans=spans,
                )
            )
        return hits

    def _fallback_snippets(self, content: str, query: str) -> list[str]:
        """后备摘要提取（当波函数未能提取有效证据跨度时兜底）。"""
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
    tokens = tokenize_stream(cleaned)
    seen: set[str] = set()
    unique: list[str] = []
    for t in tokens:
        if t and t not in seen:
            seen.add(t)
            unique.append(t)
    return unique


def _parse_mtime(value) -> datetime:
    if value is None:
        return datetime.min
    if isinstance(value, datetime):
        return value
    try:
        val_float = float(value)
        if val_float > 1e14:  # nanoseconds
            val_float = val_float / 1e9
        return datetime.fromtimestamp(val_float)
    except (TypeError, ValueError, OSError):
        return datetime.min
