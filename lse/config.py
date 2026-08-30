"""配置常量。

所有可调参数集中于此，便于 CLI / 库调用方覆盖。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# ---- 索引存储 ----
# 跨平台标准数据目录：
#   Windows: %LOCALAPPDATA%\lse\index
#   macOS:   ~/Library/Application Support/lse/index
#   Linux:   ~/.local/share/lse/index
# 可用环境变量 LSE_DATA_DIR 覆盖。


def _platform_default_index_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
        return base / "lse" / "index"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "lse" / "index"
    return Path.home() / ".local" / "share" / "lse" / "index"


DEFAULT_INDEX_DIR = Path(os.environ.get("LSE_DATA_DIR", str(_platform_default_index_dir())))

# ---- 文件发现 ----
# 文本后缀 → 文档类型标签
TEXT_SUFFIXES: dict[str, str] = {
    ".md": "note",
    ".markdown": "note",
    ".txt": "note",
    ".tex": "note",
    ".typ": "note",
    ".rst": "note",
    ".log": "data",
    ".csv": "data",
    ".tsv": "data",
    ".json": "data",
    ".jsonl": "data",
    ".yaml": "config",
    ".yml": "config",
    ".toml": "config",
    ".ini": "config",
    ".cfg": "config",
    ".conf": "config",
    ".properties": "config",
    ".xml": "config",
    ".html": "doc",
    ".htm": "doc",
    ".css": "code",
    ".js": "code",
    ".ts": "code",
    ".jsx": "code",
    ".tsx": "code",
    ".py": "code",
    ".java": "code",
    ".kt": "code",
    ".go": "code",
    ".rs": "code",
    ".c": "code",
    ".h": "code",
    ".cpp": "code",
    ".hpp": "code",
    ".cs": "code",
    ".swift": "code",
    ".sh": "code",
    ".bash": "code",
    ".zsh": "code",
    ".rb": "code",
    ".php": "code",
    ".sql": "code",
    ".vue": "code",
    ".svelte": "code",
    ".scala": "code",
    ".gradle": "config",
    ".kts": "config",
    ".dockerfile": "config",
    ".makefile": "config",
    ".env": "config",
}

# 目录名（任意层级出现即跳过）
SKIP_DIR_NAMES: frozenset[str] = frozenset({
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".idea",
    ".vscode",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".cache",
    ".next",
    ".nuxt",
    ".turbo",
    "build",
    "dist",
    "target",
})

# 路径片段（路径包含即跳过，用于通用名字如 runs 但仅特定路径）
SKIP_PATH_FRAGMENTS: tuple[str, ...] = (
    "/.claude/worktrees/",
    "/worktrees/",
    "/private/runs/",
    "/private/ai-tools-archive/worktrees/",
)

# 文件名/后缀明确跳过（二进制、依赖、产物）
SKIP_FILENAMES: frozenset[str] = frozenset({".DS_Store", "package-lock.json"})
SKIP_SUFFIXES: frozenset[str] = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".svg",
    ".pdf", ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
    ".db", ".sqlite", ".sqlite3", ".class", ".jar", ".war",
    ".exe", ".dll", ".so", ".dylib", ".o", ".a", ".bin",
    ".wav", ".mp3", ".mp4", ".mov", ".avi", ".mkv",
    ".ttf", ".otf", ".woff", ".woff2", ".icns",
    ".pem", ".key", ".crt",
})

# ---- 索引参数 ----
# 单文件最大读取字节（大于此值跳过）
MAX_FILE_BYTES = 64 * 1024 * 1024
DEFAULT_INDEX_THREADS = min(8, os.cpu_count() or 4)
MAX_INDEX_THREADS = 64
# 批量写入时一次 add 的文档数
WRITE_BATCH_SIZE = 256

# ---- 查询参数 ----
MAX_QUERY_LENGTH = 2048
MAX_SEARCH_LIMIT = 1000
DEFAULT_SEARCH_LIMIT = 10
DEFAULT_SEARCH_FIELDS = ("content", "filename", "path")

# ---- Snippet ----
SNIPPET_CONTEXT_CHARS = 80
SNIPPET_MAX_COUNT = 3
