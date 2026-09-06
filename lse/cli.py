"""lse 命令行入口。

子命令：index / update / search / status / rebuild。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .config import DEFAULT_INDEX_DIR, DEFAULT_SEARCH_LIMIT, MAX_SEARCH_LIMIT
from .indexer import IndexEngine
from .model import SearchResult
from .searcher import SearchEngine


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    try:
        return args.func(args)
    except RuntimeError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lse",
        description="🔍 现代本地全文搜索引擎（动态共振证据区间 + 代码/CJK双轨分词 + 形式化AST）",
    )
    parser.add_argument("--version", action="version", version=f"lse {__version__}")
    parser.add_argument(
        "--index-dir",
        type=Path,
        default=DEFAULT_INDEX_DIR,
        help=f"索引目录（默认: {DEFAULT_INDEX_DIR}）",
    )
    sub = parser.add_subparsers(dest="command")

    index_p = sub.add_parser("index", help="全量构建索引")
    index_p.add_argument("paths", nargs="+", type=Path, help="要索引的目录或文件")
    _add_common_index_args(index_p)
    index_p.set_defaults(func=_cmd_index)

    update_p = sub.add_parser("update", help="增量更新索引")
    update_p.add_argument("paths", nargs="*", type=Path, help="要扫描的目录（默认沿用上次）")
    _add_common_index_args(update_p)
    update_p.set_defaults(func=_cmd_update)

    search_p = sub.add_parser("search", help="执行搜索")
    search_p.add_argument("query", help="查询语句")
    search_p.add_argument("-l", "--limit", type=int, default=DEFAULT_SEARCH_LIMIT)
    search_p.add_argument("-f", "--format", choices=["text", "json"], default="text")
    search_p.set_defaults(func=_cmd_search)

    pack_p = sub.add_parser("pack", help="🎯 意图到上下文胶囊：搜索并一键打包自闭合代码块与依赖供 AI 消费")
    pack_p.add_argument("query", help="查询意图或符号")
    pack_p.add_argument("-b", "--budget", type=int, default=1500, help="Token 预算（默认: 1500）")
    pack_p.add_argument("-c", "--copy", action="store_true", help="自动拷贝到系统剪贴板")
    pack_p.add_argument("-f", "--format", choices=["markdown", "json"], default="markdown", help="输出格式")
    pack_p.add_argument("--no-deps", action="store_true", help="不提取 1-hop 依赖定义")
    pack_p.set_defaults(func=_cmd_pack)

    status_p = sub.add_parser("status", help="查看索引状态")
    status_p.set_defaults(func=_cmd_status)

    rebuild_p = sub.add_parser("rebuild", help="全量重建索引")
    rebuild_p.add_argument("paths", nargs="+", type=Path, help="要索引的目录或文件")
    rebuild_p.add_argument("--yes", action="store_true", help="确认删除现有索引")
    _add_common_index_args(rebuild_p)
    rebuild_p.set_defaults(func=_cmd_rebuild)

    watch_p = sub.add_parser("watch", help="实时监听文件系统变动并自动增量更新索引")
    watch_p.add_argument("paths", nargs="*", type=Path, help="要监听的目录（默认沿用上次）")
    watch_p.add_argument("--debounce", type=float, default=1.0, help="防抖延迟秒数（默认: 1.0s）")
    _add_common_index_args(watch_p)
    watch_p.set_defaults(func=_cmd_watch)

    return parser


def _add_common_index_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--exclude", nargs="*", default=[], help="额外排除的目录名")


def _cmd_index(args) -> int:
    engine = IndexEngine(args.index_dir)
    count = _collect_count(engine, args.paths, getattr(args, "exclude", None))
    print(f"🚀 开始全量索引: {count} 个文件 → {args.index_dir}")
    status = engine.build(args.paths, extra_exclude=getattr(args, "exclude", None))
    _print_status(status)
    return 0


def _cmd_update(args) -> int:
    engine = IndexEngine(args.index_dir)
    roots = args.paths or _last_indexed_roots(args.index_dir)
    if not roots:
        print("⚠️ 未提供路径且无上次索引记录，请指定目录")
        return 1
    print(f"🔄 增量更新: {roots}")
    status = engine.update(roots, extra_exclude=getattr(args, "exclude", None))
    _print_status(status)
    return 0


def _cmd_search(args) -> int:
    if len(args.query) > 4096:
        print("❌ 查询过长", file=sys.stderr)
        return 1
    limit = min(max(args.limit, 0), MAX_SEARCH_LIMIT)
    engine = SearchEngine(args.index_dir)
    result = engine.search(args.query, limit)

    if args.format == "json":
        print(_result_to_json(result))
    else:
        _print_text_result(result)
    return 0


def _cmd_pack(args) -> int:
    if len(args.query) > 4096:
        print("❌ 查询过长", file=sys.stderr)
        return 1
    from .packer import ContextPacker

    packer = ContextPacker(args.index_dir)
    capsule, copied = packer.pack(
        query=args.query,
        budget_tokens=max(args.budget, 100),
        include_deps=not args.no_deps,
        copy_to_clipboard=args.copy,
    )

    if args.format == "json":
        print(capsule.to_json())
    else:
        print(capsule.to_markdown())

    if args.copy:
        if copied:
            print("\n📋 \033[32m已成功拷贝上下文胶囊到系统剪贴板！可以直接 Cmd+V 粘贴给 AI。\033[0m", file=sys.stderr)
        else:
            print("\n⚠️ 未检测到系统剪贴板工具（pbcopy/xclip/wl-copy/clip），未能自动拷贝。", file=sys.stderr)
    return 0


def _cmd_status(args) -> int:
    engine = IndexEngine(args.index_dir)
    _print_status(engine.status())
    return 0


def _cmd_rebuild(args) -> int:
    if not args.yes:
        print("⚠️ 这将删除现有索引并重建，请加 --yes 确认")
        return 1
    import shutil

    shutil.rmtree(args.index_dir, ignore_errors=True)
    engine = IndexEngine(args.index_dir)
    print(f"🔄 重建索引: {args.paths}")
    status = engine.rebuild(args.paths, extra_exclude=getattr(args, "exclude", None))
    _print_status(status)
    return 0


def _cmd_watch(args) -> int:
    engine = IndexEngine(args.index_dir)
    roots = args.paths or _last_indexed_roots(args.index_dir)
    if not roots:
        print("⚠️ 未提供路径且无上次索引记录，请指定目录", file=sys.stderr)
        return 1

    resolved_roots = [p.resolve() for p in roots if p.exists()]
    if not resolved_roots:
        print("❌ 监听路径均不存在", file=sys.stderr)
        return 1

    print(f"👀 开始实时监听目录变动: {[str(r) for r in resolved_roots]}")
    print("   (按 Ctrl+C 停止监听)")

    extra_exclude = getattr(args, "exclude", None)

    try:
        import watchfiles
        from watchfiles import Change, DefaultFilter

        exclude_dirs = set(extra_exclude or [])
        exclude_dirs.update({".git", ".lse", "node_modules", "__pycache__", ".venv", ".pytest_cache"})

        class CustomFilter(DefaultFilter):
            def __call__(self, change: Change, path: str) -> bool:
                p = Path(path)
                if any(part in exclude_dirs for part in p.parts):
                    return False
                return super().__call__(change, path)

        for changes in watchfiles.watch(
            *resolved_roots,
            watch_filter=CustomFilter(),
            debounce=int(getattr(args, "debounce", 1.0) * 1000),
            step=50,
        ):
            print(f"\n⚡ 检测到 {len(changes)} 处文件变动，正在同步增量索引...")
            status = engine.update(resolved_roots, extra_exclude=extra_exclude)
            print(f"   已更新: {status.doc_count} 篇文档 ({status.index_bytes / 1024:.1f} KB)")
    except ImportError:
        import time
        print("ℹ️ 未检测到 watchfiles，使用轻量轮询监听模式 (每 2 秒一次)...")
        while True:
            time.sleep(max(getattr(args, "debounce", 2.0), 1.0))
            engine.update(resolved_roots, extra_exclude=extra_exclude)
    except KeyboardInterrupt:
        print("\n🛑 已停止监听。")
        return 0
    return 0



def _collect_count(engine: IndexEngine, paths: list[Path], extra_exclude: list[str] | None = None) -> int:
    from .discovery import discover_files, is_text_file

    count = 0
    exclude_set = set(extra_exclude) if extra_exclude else None
    for path in paths:
        path = Path(path)
        if path.is_file():
            count += 1 if is_text_file(path, exclude_set) else 0
        elif path.is_dir():
            count += len(discover_files(path, extra_exclude))
    return count


def _last_indexed_roots(index_dir: Path) -> list[Path]:
    import json

    meta = Path(index_dir) / "state.json"
    if not meta.exists():
        return []
    try:
        data = json.loads(meta.read_text())
        roots = data.get("roots", [])
        if roots:
            return [Path(p) for p in roots]
        files = data.get("files", [])
        if files:
            # Fallback for legacy state format
            return list({Path(f["path"]).parent for f in files if isinstance(f, dict) and "path" in f})
        return []
    except (ValueError, OSError):
        return []


def _print_status(status) -> None:
    print("📊 索引状态")
    print(f"   文档数: {status.doc_count:,}")
    print(f"   索引大小: {_format_bytes(status.index_bytes)}")
    print(f"   索引目录: {status.index_dir}")
    if status.last_updated:
        print(f"   最后更新: {status.last_updated.isoformat()}")


def _highlight_snippet(snippet: str, query: str) -> str:
    import re
    from .searcher import _query_terms

    terms = _query_terms(query)
    if not terms:
        return snippet
    sorted_terms = sorted(set(terms), key=len, reverse=True)
    pattern = re.compile("(" + "|".join(re.escape(t) for t in sorted_terms if t) + ")", re.IGNORECASE)
    return pattern.sub(r"\033[1;33m\1\033[0m", snippet)


def _print_text_result(result: SearchResult) -> None:
    print(f"🔍 查询: \"{result.query}\"")
    print()
    if not result.hits:
        print("⚠️ 未找到匹配结果")
        print(f"\n📊 共 0 条匹配，用时 {result.elapsed_ms}ms")
        return
    for i, hit in enumerate(result.hits, 1):
        print("─────────────────────────────────")
        print(f"{i}. {hit.path} (score: {hit.score:.4f})")
        if getattr(hit, "spans", None):
            for span in hit.spans:
                loc_info = f"L{span.start_line}-L{span.end_line}"
                meta_parts = [loc_info]
                if span.breadcrumbs:
                    meta_parts.append(span.breadcrumbs)
                meta_parts.append(f"{int(span.confidence * 100)}% 证据共振")
                print(f"   \033[2m[{ ' | '.join(meta_parts) }]\033[0m")
                for line in span.highlighted_text.splitlines():
                    print(f"   {line}")
                print()
        else:
            for snippet in hit.snippets:
                print(f"   {_highlight_snippet(snippet, result.query)}")
            print()
    print(f"📊 共 {result.total_matches} 条匹配，用时 {result.elapsed_ms}ms")


def _result_to_json(result: SearchResult) -> str:
    return json.dumps(
        {
            "query": result.query,
            "total_matches": result.total_matches,
            "elapsed_ms": result.elapsed_ms,
            "hits": [
                {
                    "path": h.path,
                    "filename": h.filename,
                    "extension": h.extension,
                    "doc_type": h.doc_type,
                    "size": h.size,
                    "mtime": h.mtime.isoformat(),
                    "score": h.score,
                    "snippets": h.snippets,
                    "spans": [
                        {
                            "start_line": s.start_line,
                            "end_line": s.end_line,
                            "breadcrumbs": s.breadcrumbs,
                            "confidence": s.confidence,
                            "text": s.text,
                        }
                        for s in getattr(h, "spans", [])
                    ],
                }
                for h in result.hits
            ],
        },
        ensure_ascii=False,
        indent=2,
    )


def _format_bytes(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.2f} KB"
    if size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.2f} MB"
    return f"{size / (1024 * 1024 * 1024):.2f} GB"


if __name__ == "__main__":
    sys.exit(main())
