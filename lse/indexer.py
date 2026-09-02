"""索引构建器：全量 / 增量 / 重建。

基于 tantivy IndexWriter：
- 全量 build：清空后写入全部发现文件
- 增量 update：对比上轮 metadata，仅写入变更/新增，删除消失文件
- 重建 rebuild：删除整个索引目录后重新构建
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import tantivy

from .config import DEFAULT_INDEX_DIR
from .discovery import discover_files, is_text_file
from .model import IndexStatus, IndexableFile
from .schema import build_schema, register_tokenizers, to_epoch_mtime

META_FILE = "state.json"


class IndexEngine:
    """索引管理入口。

    index_dir 默认 ~/Library/Application Support/lse/index 等平台目录。
    """

    def __init__(self, index_dir: Path = DEFAULT_INDEX_DIR) -> None:
        self.index_dir = Path(index_dir)
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.schema = build_schema()
        self.index = tantivy.Index(self.schema, str(self.index_dir))
        # tantivy 自定义 tokenizer 不持久化：每次使用索引都要注册，
        # 且必须在 writer() 之后调用（writer 打开时会快照 tokenizer manager）。
        # 写入侧在 _write_batch/update 里 writer 创建后注册；
        # 搜索侧在 parse_query 前注册。

    # ---------- 公开操作 ----------

    def build(
        self, roots: list[Path], extra_exclude: list[str] | set[str] | None = None
    ) -> IndexStatus:
        """全量构建：删除旧索引后重建。"""
        files = self._collect(roots, extra_exclude)
        # 新目录重建（避免残留旧索引）
        shutil.rmtree(self.index_dir, ignore_errors=True)
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.index = tantivy.Index(self.schema, str(self.index_dir))
        self._write_batch(files)
        self._save_state(files, roots)
        return self.status()

    def update(
        self, roots: list[Path], extra_exclude: list[str] | set[str] | None = None
    ) -> IndexStatus:
        """增量更新：仅针对指定 roots 写入新增/变更与删除已消失文件，保留未扫描 roots 的索引。"""
        files = self._collect(roots, extra_exclude)
        state = self._load_state()
        previous_files = state.get("files", [])
        previous_roots = state.get("roots", [])

        resolved_roots = [r.resolve() for r in roots]

        def is_under_roots(path_str: str) -> bool:
            try:
                p = Path(path_str).resolve()
                return any(p == r or r in p.parents for r in resolved_roots)
            except OSError:
                return False

        previous_paths = {f["path"] for f in previous_files}
        previous_by_path = {item["path"]: item for item in previous_files}
        current_by_path = {str(f.path): f for f in files}

        # 仅当文件原本位于本次更新 roots 路径下、且当前磁盘上已消失时，才判定为删除
        removed = [p for p in previous_paths if is_under_roots(p) and p not in current_by_path]

        added_or_changed = [
            f
            for f in files
            if str(f.path) not in previous_paths
            or previous_by_path[str(f.path)]["mtime"] != f.mtime
            or previous_by_path[str(f.path)]["size"] != f.size_bytes
        ]

        writer = self.index.writer(num_threads=1)
        register_tokenizers(self.index)
        try:
            for path in removed:
                writer.delete_documents_by_term("path", path)
            for f in added_or_changed:
                writer.delete_documents_by_term("path", str(f.path))
                writer.add_document(
                    tantivy.Document.from_dict(
                        {
                            "path": str(f.path),
                            "filename": f.path.name,
                            "extension": f.extension.lstrip("."),
                            "content": _read_text(f.path),
                            "size": f.size_bytes,
                            "mtime": to_epoch_mtime(f.mtime),
                            "doc_type": f.doc_type,
                        }
                    )
                )
            writer.commit()
        finally:
            writer.wait_merging_threads()

        # 合并未涉及本次 roots 的历史文件记录
        preserved_files = [f for f in previous_files if not is_under_roots(f["path"])]
        current_serialized = [
            {
                "path": str(f.path),
                "extension": f.extension.lstrip("."),
                "size": f.size_bytes,
                "mtime": f.mtime,
                "doc_type": f.doc_type,
            }
            for f in files
        ]
        all_roots = list({str(r.resolve()) for r in roots} | set(previous_roots))
        self._save_state_raw(preserved_files + current_serialized, all_roots)
        return self.status()

    def rebuild(
        self, roots: list[Path], extra_exclude: list[str] | set[str] | None = None
    ) -> IndexStatus:
        """重建：等价于 build（删除全部后重建）。"""
        return self.build(roots, extra_exclude)

    # ---------- 内部 ----------

    def _collect(
        self, roots: list[Path], extra_exclude: list[str] | set[str] | None = None
    ) -> list[IndexableFile]:
        merged: list[IndexableFile] = []
        exclude_set = set(extra_exclude) if extra_exclude else None
        for root in roots:
            root = Path(root)
            if root.is_file():
                if is_text_file(root, exclude_set):
                    stat = root.stat()
                    merged.append(
                        IndexableFile(
                            path=root,
                            extension=root.suffix.lower(),
                            size_bytes=stat.st_size,
                            mtime=stat.st_mtime,
                            doc_type=_doc_type_for(root),
                        )
                    )
            elif root.is_dir():
                merged.extend(discover_files(root, extra_exclude))
            else:
                raise FileNotFoundError(f"路径不存在: {root}")
        # 去重（同一文件被多个 root 覆盖时保留第一个）
        seen: set[str] = set()
        unique: list[IndexableFile] = []
        for f in merged:
            key = str(f.path)
            if key not in seen:
                seen.add(key)
                unique.append(f)
        return unique

    def _write_batch(self, files: list[IndexableFile]) -> None:
        writer = self.index.writer(num_threads=4)
        register_tokenizers(self.index)
        try:
            for f in files:
                writer.add_document(
                    tantivy.Document.from_dict(
                        {
                            "path": str(f.path),
                            "filename": f.path.name,
                            "extension": f.extension.lstrip("."),
                            "content": _read_text(f.path),
                            "size": f.size_bytes,
                            "mtime": to_epoch_mtime(f.mtime),
                            "doc_type": f.doc_type,
                        }
                    )
                )
            writer.commit()
        finally:
            writer.wait_merging_threads()

    def status(self) -> IndexStatus:
        try:
            self.index.reload()
            searcher = self.index.searcher()
            doc_count = searcher.num_docs
        except Exception:
            doc_count = 0
        total_bytes = _dir_size(self.index_dir)
        last_updated = None
        meta_path = self.index_dir / META_FILE
        if meta_path.exists():
            try:
                last_updated = datetime.fromisoformat(
                    json.loads(meta_path.read_text()).get("last_updated", "")
                )
            except (ValueError, KeyError):
                pass
        return IndexStatus(
            doc_count=doc_count,
            index_bytes=total_bytes,
            index_dir=str(self.index_dir),
            last_updated=last_updated,
        )

    # ---------- 状态持久化 ----------

    def _state_path(self) -> Path:
        return self.index_dir / META_FILE

    def _save_state(self, files: list[IndexableFile], roots: list[Path] | None = None) -> None:
        state_files = [
            {
                "path": str(f.path),
                "extension": f.extension.lstrip("."),
                "size": f.size_bytes,
                "mtime": f.mtime,
                "doc_type": f.doc_type,
            }
            for f in files
        ]
        state_roots = [str(r.resolve()) for r in (roots or [])]
        self._save_state_raw(state_files, state_roots)

    def _save_state_raw(self, file_dicts: list[dict], roots: list[str]) -> None:
        state = {
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "roots": roots,
            "files": file_dicts,
        }
        self._state_path().write_text(json.dumps(state, ensure_ascii=False))

    def _load_state(self) -> dict:
        path = self._state_path()
        if not path.exists():
            return {"roots": [], "files": []}
        try:
            data = json.loads(path.read_text())
            if isinstance(data, dict):
                return data
            return {"roots": [], "files": []}
        except (ValueError, OSError):
            return {"roots": [], "files": []}


def _read_text(path: Path) -> str:
    """读取文件文本，优先 utf-8 严格解码，失败回退 gbk，最后 replace 容错。"""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            return path.read_text(encoding="gbk")
        except (UnicodeDecodeError, OSError):
            try:
                return path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                return ""
    except OSError:
        return ""


def _doc_type_for(path: Path) -> str:
    from .config import TEXT_SUFFIXES

    return TEXT_SUFFIXES.get(path.suffix.lower(), "note")


def _dir_size(directory: Path) -> int:
    total = 0
    for path in directory.rglob("*"):
        if path.is_file():
            try:
                total += path.stat().st_size
            except OSError:
                pass
    return total
