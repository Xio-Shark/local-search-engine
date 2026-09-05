"""领域模型：索引文档、证据区间与搜索结果对外形态。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


@dataclass
class IndexableFile:
    """一个待索引文件的基本信息。"""

    path: Path
    extension: str
    size_bytes: int
    mtime: float  # epoch seconds
    doc_type: str
    content_hash: str = ""  # 内容指纹，用于抗 touch/git 切换误伤


@dataclass(frozen=True)
class IndexedDoc:
    """写入 tantivy 的文档字段（与 schema 对齐）。"""

    path: str
    filename: str
    extension: str
    content: str
    size: int
    mtime: datetime
    doc_type: str
    code_terms: str = ""  # 解离的代码符号流


@dataclass(frozen=True)
class SearchHit:
    """单条搜索结果。"""

    path: str
    filename: str
    extension: str
    doc_type: str
    size: int
    mtime: datetime
    score: float
    snippets: list[str] = field(default_factory=list)
    spans: list[Any] = field(default_factory=list)  # list[EvidenceSpan]


@dataclass(frozen=True)
class SearchResult:
    """一次查询的完整返回。"""

    query: str
    hits: list[SearchHit]
    total_matches: int
    elapsed_ms: int


@dataclass(frozen=True)
class IndexStatus:
    """索引状态摘要（status 子命令展示）。"""

    doc_count: int
    index_bytes: int
    index_dir: str
    last_updated: datetime | None = None
