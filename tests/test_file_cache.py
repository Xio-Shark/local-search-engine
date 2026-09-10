from __future__ import annotations

import os
from pathlib import Path

from lse.searcher import _read_disk_file, clear_content_cache


def test_content_cache_reloads_after_size_change(tmp_path: Path) -> None:
    target = tmp_path / "note.txt"
    target.write_text("old", encoding="utf-8")
    clear_content_cache()

    assert _read_disk_file(str(target)) == "old"
    target.write_text("new-longer-content", encoding="utf-8")
    assert _read_disk_file(str(target)) == "new-longer-content"


def test_content_cache_reloads_after_mtime_change_same_size(tmp_path: Path) -> None:
    target = tmp_path / "same-size.txt"
    target.write_text("aaaa", encoding="utf-8")
    clear_content_cache()
    stat_before = target.stat()
    assert _read_disk_file(str(target)) == "aaaa"

    target.write_text("bbbb", encoding="utf-8")
    stat_after = target.stat()
    if stat_after.st_mtime_ns == stat_before.st_mtime_ns:
        # APFS 的时间戳精度足够高，通常不需要；此分支用于保证测试在低精度
        # 文件系统（或 CI 缓存目录）上仍然有确定性。
        os.utime(
            target,
            ns=(stat_before.st_atime_ns, stat_before.st_mtime_ns + 1_000_000),
        )

    assert _read_disk_file(str(target)) == "bbbb"


def test_content_cache_evicts_missing_file(tmp_path: Path) -> None:
    target = tmp_path / "gone.txt"
    target.write_text("before", encoding="utf-8")
    clear_content_cache()

    assert _read_disk_file(str(target)) == "before"
    target.unlink()
    assert _read_disk_file(str(target)) == ""

    target.write_text("after", encoding="utf-8")
    assert _read_disk_file(str(target)) == "after"
