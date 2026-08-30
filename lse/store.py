"""索引目录与元数据管理。

统一封装 IndexEngine 的存储目录，供 CLI 与 rag 集成使用。
"""

from __future__ import annotations

import shutil
from pathlib import Path

from .config import DEFAULT_INDEX_DIR
from .indexer import IndexEngine


class IndexStore:
    """索引目录门面。"""

    def __init__(self, index_dir: Path = DEFAULT_INDEX_DIR) -> None:
        self.index_dir = Path(index_dir)
        self.engine = IndexEngine(self.index_dir)

    def exists(self) -> bool:
        return self.index_dir.exists() and any(self.index_dir.iterdir())

    def clear(self) -> None:
        """删除整个索引（rebuild 前置）。"""
        shutil.rmtree(self.index_dir, ignore_errors=True)
        self.index_dir.mkdir(parents=True, exist_ok=True)

    def index_engine(self) -> IndexEngine:
        return self.engine
