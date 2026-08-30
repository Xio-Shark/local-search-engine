"""文件发现：递归扫描目录，产出待索引文本文件。

- 按后缀白名单（config.TEXT_SUFFIXES）识别文本文件
- 跳过二进制/依赖/缓存目录
- 跳过超大文件
"""

from __future__ import annotations

import os
from pathlib import Path

from .config import (
    MAX_FILE_BYTES,
    SKIP_DIR_NAMES,
    SKIP_FILENAMES,
    SKIP_PATH_FRAGMENTS,
    SKIP_SUFFIXES,
    TEXT_SUFFIXES,
)
from .model import IndexableFile


def _skip_path(path: Path) -> bool:
    path_str = str(path)
    return any(fragment in path_str for fragment in SKIP_PATH_FRAGMENTS)


def is_text_file(path: Path) -> bool:
    """判断文件是否应进入索引（后缀白名单 + 大小 + 名字排除 + 路径片段排除）。"""
    if _skip_path(path):
        return False
    if path.name in SKIP_FILENAMES:
        return False
    suffix = path.suffix.lower()
    if suffix not in TEXT_SUFFIXES or suffix in SKIP_SUFFIXES:
        return False
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return False
    except OSError:
        return False
    return True


def _should_skip_dir(name: str) -> bool:
    return name in SKIP_DIR_NAMES


def discover_files(root: Path) -> list[IndexableFile]:
    """递归扫描 root，返回文本文件列表（跳过 SKIP_DIR_NAMES 中的目录）。

    对 symlink 目录不跟随，避免循环；文件按 mtime 排序保证稳定顺序。
    """
    results: list[IndexableFile] = []

    def walk(directory: Path) -> None:
        if _skip_path(directory):
            return
        try:
            entries = sorted(os.scandir(directory), key=lambda e: e.name)
        except OSError:
            return
        for entry in entries:
            if _should_skip_dir(entry.name):
                continue
            try:
                if entry.is_dir(follow_symlinks=False):
                    walk(Path(entry.path))
                elif entry.is_file(follow_symlinks=False) and is_text_file(Path(entry.path)):
                    entry_stat = entry.stat()
                    results.append(
                        IndexableFile(
                            path=Path(entry.path),
                            extension=Path(entry.path).suffix.lower(),
                            size_bytes=entry_stat.st_size,
                            mtime=entry_stat.st_mtime,
                            doc_type=TEXT_SUFFIXES[Path(entry.path).suffix.lower()],
                        )
                    )
            except OSError:
                continue

    walk(root)
    results.sort(key=lambda f: f.path)
    return results
