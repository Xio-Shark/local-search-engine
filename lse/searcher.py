"""搜索引擎：BM25 查询 + AST 解析 + 动态局部共振证据区间。

基于 Tantivy 索引与递归下降 AST 解析器，支持：
1. 形式化 DSL 编译与字段别名翻译 (ext, type, filename, size, mtime)
2. CJK 与代码混合词项自适应短语加权与容错展开
3. 基于能量波函数的动态连续证据区间提取 (Evidence Spans)，消灭固定分块截断
4. Fast-Field 原生排序与范围过滤
"""

from __future__ import annotations

import math
import os
import re
import stat
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

from .concepts import load_project_concepts
from .config import (
    DEFAULT_INDEX_DIR,
    DEFAULT_SEARCH_LIMIT,
    SNIPPET_CONTEXT_CHARS,
    SNIPPET_MAX_COUNT,
)
from .indexer import IndexEngine
from .model import SearchHit, SearchResult
from .options import SearchOptions
from .query_ast import QueryCompiler
from .resonance import extract_evidence_spans
from .schema import register_tokenizers
from .tokenizer import tokenize_stream


class SearchEngine:
    """查询入口。

    与 IndexEngine 共享同一 index_dir；查询前 reload 以看到最新提交。
    """

    def __init__(
        self, index_dir: Path = DEFAULT_INDEX_DIR, options: SearchOptions | None = None
    ) -> None:
        self.index_dir = Path(index_dir)
        self.options = options or SearchOptions()
        self.engine = IndexEngine(self.index_dir)
        self.index = self.engine.index
        # 每次打开索引后注册 tokenizer（不持久化），否则 parse_query 报未注册
        register_tokenizers(self.index)

    def search(
        self,
        query: str,
        limit: int = DEFAULT_SEARCH_LIMIT,
        options: SearchOptions | None = None,
    ) -> SearchResult:
        start = datetime.now()
        if not query or not query.strip():
            return SearchResult(query=query, hits=[], total_matches=0, elapsed_ms=0)

        opts = options or self.options
        self.index.reload()
        searcher = self.index.searcher()

        # 1. 形式化 AST 编译：结合项目自适应概念图谱提取排序指令、翻译别名与自适应展开
        concept_map = load_project_concepts(self.index_dir)
        compiler = QueryCompiler(
            query, concept_map=concept_map, expand_concepts=opts.concept_expansion
        )
        plain_terms = compiler.plain_terms() if opts.natural_query else None

        # 2. 纯词项自然语言查询：用与索引侧一致的分词器重写为带 IDF 权重的 OR 查询；
        #    结构化语法（字段/布尔/短语/括号/排序）继续走 AST 编译路径。
        natural_query: str | None = None
        if plain_terms:
            natural_query = _build_natural_query(plain_terms, compiler, searcher, opts)

        if natural_query is not None:
            effective_query = natural_query
            sort_field: str | None = None
            sort_order = None
            conjunction_by_default = False
        else:
            compiled_query, sort_field, sort_order = compiler.compile()
            effective_query = compiled_query.strip() or "*"
            conjunction_by_default = opts.conjunction_by_default

        try:
            parsed = self.index.parse_query(
                effective_query,
                opts.query_fields,
                conjunction_by_default=conjunction_by_default,
            )
        except ValueError:
            # 自愈降级 1：使用 Tantivy 容错分析器
            try:
                parsed, _ = self.index.parse_query_lenient(
                    effective_query,
                    opts.query_fields,
                    conjunction_by_default=conjunction_by_default,
                )
            except Exception:
                # 自愈降级 2：剔除敏感操作符转为字面短语匹配，杜绝异常泄露
                escaped = re.sub(r'["*+?^=!:{}\[\]()|\\\/~]', " ", query).strip()
                parsed = self.index.parse_query(
                    f'"{escaped}"' if escaped else "*",
                    opts.query_fields,
                    conjunction_by_default=conjunction_by_default,
                )

        # 3. 执行搜索（带排序或原生 BM25 相关性打分）
        limit_val = min(max(limit, 1), 1000)
        if sort_field:
            hits = searcher.search(parsed, limit_val, order_by_field=sort_field, order=sort_order)
        else:
            hits = searcher.search(parsed, limit_val)

        # 4. 容错降级：仅对纯文本意图（无字段过滤:、无显式AND、无精确引号）在全词命中为 0 时降级为宽松匹配 (OR)
        if (
            hits.count == 0
            and not sort_field
            and " AND " not in query
            and ":" not in query
            and '"' not in query
        ):
            try:
                parsed_loose = self.index.parse_query(
                    effective_query,
                    opts.query_fields,
                    conjunction_by_default=False,
                )
                hits_loose = searcher.search(parsed_loose, limit_val)
                if hits_loose.count > 0:
                    hits = hits_loose
            except Exception:
                pass

        results = self._to_hits(searcher, hits, query)
        elapsed_ms = int((datetime.now() - start).total_seconds() * 1000)
        return SearchResult(
            query=query,
            hits=results,
            total_matches=hits.count,
            elapsed_ms=elapsed_ms,
        )

    def _to_hits(self, searcher, search_result, query: str) -> list[SearchHit]:
        terms = _query_terms(query)
        term_weights = {t: math.log1p(len(t)) for t in terms}

        raw_items = list(search_result.hits)
        if not raw_items:
            return []

        def _process_one(item: tuple[float, Any]) -> SearchHit | None:
            score, address = item
            doc = searcher.doc(address)
            try:
                path = doc.get_first("path")
            except (AttributeError, TypeError):
                return None
            path_str = str(path)
            content = _read_disk_file(path_str)
            mtime = _parse_mtime(doc.get_first("mtime"))
            try:
                score_val = float(score)
            except (TypeError, ValueError):
                score_val = 0.0

            # 求解连续局部证据区间（IDF 加权 + 符号语法感知）
            spans = extract_evidence_spans(content, terms, term_weights=term_weights)
            if spans:
                snippets = [s.text for s in spans]
            else:
                snippets = self._fallback_snippets(content, query)

            return SearchHit(
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

        # 针对多文件命中并发读取与切片（避免顺序磁盘 IO 阻塞）
        if len(raw_items) > 4:
            with ThreadPoolExecutor(max_workers=min(8, os.cpu_count() or 4)) as executor:
                res_hits = list(executor.map(_process_one, raw_items))
            return [h for h in res_hits if h is not None]
        else:
            hits = []
            for item in raw_items:
                h = _process_one(item)
                if h is not None:
                    hits.append(h)
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


# 正文缓存：key 为路径，value 为 (mtime_ns, size, text)。
# 不使用 lru_cache，因为文件更新后 mtime/size 变化必须让旧内容失效。
_FILE_CACHE_MAX = 1024
_file_cache: dict[str, tuple[int, int, str]] = {}


def clear_content_cache() -> None:
    """清空正文缓存。索引更新/监听变更后可主动调用。"""
    _file_cache.clear()


def _read_disk_file(path_str: str) -> str:
    """按需读取文档原文，并在文件 mtime/size 未变化时复用缓存。"""
    try:
        st = os.stat(path_str)
        if not stat.S_ISREG(st.st_mode):
            _file_cache.pop(path_str, None)
            return ""
    except OSError:
        _file_cache.pop(path_str, None)
        return ""

    cached = _file_cache.get(path_str)
    if cached and cached[0] == st.st_mtime_ns and cached[1] == st.st_size:
        return cached[2]

    try:
        raw = Path(path_str).read_bytes()
    except OSError:
        _file_cache.pop(path_str, None)
        return ""

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = raw.decode("gbk")
        except (UnicodeDecodeError, OSError):
            text = raw.decode("utf-8", errors="replace")

    # 读取期间文件若被修改，则不写入缓存，下一次调用会重新读取。
    try:
        st_after = os.stat(path_str)
    except OSError:
        return text
    if st_after.st_mtime_ns == st.st_mtime_ns and st_after.st_size == st.st_size:
        if len(_file_cache) >= _FILE_CACHE_MAX:
            _file_cache.pop(next(iter(_file_cache)))
        _file_cache[path_str] = (st.st_mtime_ns, st.st_size, text)
    return text


_CJK_QUERY_RE = re.compile(r"[\u4e00-\u9fff]")


def _build_natural_query(
    terms: list[str],
    compiler: QueryCompiler,
    searcher,
    options: SearchOptions,
) -> str | None:
    """把纯词项自然语言查询编译为与索引分词对齐的加权 OR 查询。

    查询词首先经过与索引侧相同的 ``tokenize_stream`` 分词；随后按 BM25 IDF
    计算词项权重（可关闭）。这样既避免了 query parser 默认分析器与索引
    analyzer 不一致造成的词项错配，也保留了“稀有词更重要”的排序先验。

    CJK 与中西混排词项仍走 ``QueryCompiler`` 的分组语义（例如 ``目录A``
    编译为 ``目录 AND a``），避免被拆成 OR 后把 ``目录B`` 一并召回。
    """
    clauses: list[str] = []
    seen_tokens: set[str] = set()
    num_docs = max(int(searcher.num_docs), 1)

    for term in terms:
        if _CJK_QUERY_RE.search(term):
            clause = compiler._compile_term(term)
            if clause:
                clauses.append(clause)
            continue

        candidates = list(tokenize_stream(term))
        if options.concept_expansion:
            for concept in compiler.concept_map.get(term.lower(), [])[:3]:
                candidates.extend(tokenize_stream(str(concept)))
        for token in candidates:
            if not token or token in seen_tokens or not any(ch.isalnum() for ch in token):
                continue
            seen_tokens.add(token)
            escaped = token.replace('"', '\\"')
            boost = _term_idf_boost(searcher, token, num_docs, options.idf_power)
            if boost is None:
                clauses.append(f'"{escaped}"')
            else:
                clauses.append(f'"{escaped}"^{boost:.4f}')

    if not clauses:
        return None
    return " OR ".join(clauses)


def _term_idf_boost(searcher, term: str, num_docs: int, power: float | None) -> float | None:
    """返回查询词项的 IDF 幂次权重；``None`` 表示保持 Tantivy 原生权重。"""
    if power is None:
        return None
    try:
        doc_freq = int(searcher.doc_freq("content", term))
    except (TypeError, ValueError, RuntimeError):
        return None
    idf = math.log(1.0 + (num_docs - doc_freq + 0.5) / (doc_freq + 0.5))
    if idf <= 0:
        return None
    return max(1e-3, idf ** max(power, 0.0))


def _query_terms(query: str) -> list[str]:
    """从查询提取用于高亮和定位的搜索词，保留版本号与技术名词中的数字。"""
    if not query:
        return []
    # 过滤字段过滤表达式
    cleaned = re.sub(r"[a-zA-Z_]+:(?:\[[^\]]*\]|\"[^\"]*\"|\S+)", " ", query)
    # 过滤布尔操作符与括号符号（注意：保留数字 0-9，避免截断 GPT-4o、C++17 等）
    cleaned = re.sub(r"\b(AND|OR|NOT)\b|[()\"^]+", " ", cleaned)
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
