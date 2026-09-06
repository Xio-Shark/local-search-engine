"""意图到代码上下文胶囊打包器 (Intent-to-Context Capsule Packer)。

核心理念：
搜索的本质是“意图到行动的最小上下文生成”。
给定自然语言查询或符号名，在毫秒级内定位核心 AST 自闭合代码块，
就地自动吸附其内部调用的 1-hop 外部依赖符号定义（类/函数签名），
在严格的 Token 预算内压缩打包为可直接喂给 AI 的 Markdown 提示词胶囊，
并支持一键写入系统剪贴板。
"""

from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .config import DEFAULT_INDEX_DIR
from .searcher import SearchEngine, _read_disk_file


@dataclass(frozen=True)
class AnchorBlock:
    """核心命中的代码块锚点。"""

    file_path: str
    breadcrumbs: str
    start_line: int
    end_line: int
    code: str
    score: float


@dataclass(frozen=True)
class DependencyBlock:
    """1-hop 关联依赖符号的定义摘要。"""

    symbol: str
    file_path: str
    line_no: int
    kind: str  # class / def / const / type
    code: str  # 签名或简短自闭合实现


@dataclass(frozen=True)
class ContextCapsule:
    """打包完成的上下文胶囊数据结构。"""

    query: str
    budget_tokens: int
    estimated_tokens: int
    anchors: list[AnchorBlock]
    dependencies: list[DependencyBlock]
    files_involved: list[str]

    def to_markdown(self) -> str:
        """生成面向 LLM 提示词的 Markdown 格式。"""
        lines: list[str] = [
            f"# Context Capsule: `{self.query}`",
            f"> 📦 Tokens: ~{self.estimated_tokens}/{self.budget_tokens} | Files: {len(self.files_involved)}",
            "",
        ]

        # 1. 核心代码锚点
        lines.append("## 🎯 Core Implementations (Anchors)")
        for idx, anchor in enumerate(self.anchors, 1):
            path_obj = Path(anchor.file_path)
            lang = _detect_lang(path_obj.suffix)
            bc_str = f" ({anchor.breadcrumbs})" if anchor.breadcrumbs else ""
            lines.append(
                f"### [{idx}] `{path_obj.name}` (L{anchor.start_line}-L{anchor.end_line}){bc_str}"
            )
            lines.append(f"<!-- Path: {anchor.file_path} -->")
            lines.append(f"```{lang}\n{anchor.code}\n```")
            lines.append("")

        # 2. 1-hop 依赖符号声明
        if self.dependencies:
            lines.append("## 🔗 1-Hop Referenced Dependencies")
            for dep in self.dependencies:
                path_obj = Path(dep.file_path)
                lang = _detect_lang(path_obj.suffix)
                lines.append(f"### `{dep.symbol}` ({dep.kind}) in `{path_obj.name}:{dep.line_no}`")
                lines.append(f"```{lang}\n{dep.code}\n```")
                lines.append("")

        return "\n".join(lines).strip()

    def to_json(self) -> str:
        """生成面向 Agent 工具调用的结构化 JSON。"""
        data = {
            "query": self.query,
            "budget_tokens": self.budget_tokens,
            "estimated_tokens": self.estimated_tokens,
            "files_involved": self.files_involved,
            "anchors": [asdict(a) for a in self.anchors],
            "dependencies": [asdict(d) for d in self.dependencies],
        }
        return json.dumps(data, ensure_ascii=False, indent=2)


# 常见编程语言扩展名映射
_LANG_MAP = {
    ".py": "python",
    ".go": "go",
    ".rs": "rust",
    ".js": "javascript",
    ".ts": "typescript",
    ".jsx": "jsx",
    ".tsx": "tsx",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".java": "java",
    ".md": "markdown",
    ".json": "json",
    ".toml": "toml",
    ".yaml": "yaml",
    ".yml": "yaml",
}

# Python 内置保留字与全局函数（不作为外部依赖反查）
_PY_BUILTINS = {
    "print", "len", "range", "enumerate", "isinstance", "issubclass", "getattr", "setattr",
    "hasattr", "str", "int", "float", "bool", "list", "dict", "set", "tuple", "bytes",
    "open", "super", "min", "max", "sum", "any", "all", "zip", "map", "filter", "reversed",
    "sorted", "id", "type", "repr", "iter", "next", "round", "abs", "divmod", "hash",
    "callable", "classmethod", "staticmethod", "property", "object", "Exception",
    "ValueError", "TypeError", "KeyError", "IndexError", "RuntimeError", "AttributeError",
    "StopIteration", "True", "False", "None", "self", "cls",
}


def _detect_lang(suffix: str) -> str:
    return _LANG_MAP.get(suffix.lower(), "")


def estimate_tokens(text: str) -> int:
    """快速保守估算代码与中英混合文本的 Token 消耗量。"""
    if not text:
        return 0
    # 英文代码平均约 3.5~4 字符 1 token，中文字符约 1.5 字符 1 token
    cjk_count = len(re.findall(r"[\u4e00-\u9fff]", text))
    other_count = len(text) - cjk_count
    return int(cjk_count / 1.5 + other_count / 3.6) + 1


class ContextPacker:
    """上下文胶囊打包器。"""

    def __init__(self, index_dir: Path = DEFAULT_INDEX_DIR) -> None:
        self.index_dir = Path(index_dir)
        self.searcher = SearchEngine(self.index_dir)

    def pack(
        self,
        query: str,
        budget_tokens: int = 1500,
        max_anchors: int = 2,
        include_deps: bool = True,
        copy_to_clipboard: bool = False,
    ) -> tuple[ContextCapsule, bool]:
        """执行意图到上下文胶囊的生成。

        返回：(capsule, copied_successfully)
        """
        # 1. 检索核心代码块
        search_res = self.searcher.search(query, limit=max_anchors * 2)
        anchors = self._extract_anchors(search_res, max_anchors)

        # 2. 若启用依赖吸附，抽取 1-hop 符号并反查定义
        dependencies: list[DependencyBlock] = []
        if include_deps and anchors:
            candidate_symbols = self._extract_referenced_symbols(anchors)
            dependencies = self._resolve_dependencies(candidate_symbols, exclude_paths={a.file_path for a in anchors})

        # 3. 在 Token 预算内进行压包裁剪
        anchors, dependencies, est_tokens = self._fit_budget(
            query, anchors, dependencies, budget_tokens
        )

        files_involved = sorted(
            list({a.file_path for a in anchors} | {d.file_path for d in dependencies})
        )

        capsule = ContextCapsule(
            query=query,
            budget_tokens=budget_tokens,
            estimated_tokens=est_tokens,
            anchors=anchors,
            dependencies=dependencies,
            files_involved=files_involved,
        )

        copied = False
        if copy_to_clipboard:
            copied = copy_text_to_clipboard(capsule.to_markdown())

        return capsule, copied

    def _extract_anchors(self, search_res: Any, max_anchors: int) -> list[AnchorBlock]:
        """从搜索结果提取高质量自闭合代码块。"""
        anchors: list[AnchorBlock] = []
        for hit in search_res.hits:
            if not hit.spans:
                continue
            for span in hit.spans:
                # 仅收纳长度适中且有效的语法块
                anchors.append(
                    AnchorBlock(
                        file_path=hit.path,
                        breadcrumbs=span.breadcrumbs,
                        start_line=span.start_line,
                        end_line=span.end_line,
                        code=span.text,
                        score=hit.score,
                    )
                )
                if len(anchors) >= max_anchors:
                    break
            if len(anchors) >= max_anchors:
                break
        return anchors

    def _extract_referenced_symbols(self, anchors: list[AnchorBlock]) -> set[str]:
        """从锚点代码块中提取被引用的自定义外部标识符。"""
        symbols: set[str] = set()

        for anchor in anchors:
            code = anchor.code
            is_py = anchor.file_path.endswith(".py")

            if is_py:
                # 针对 Python 采用标准库 AST 解析
                try:
                    tree = ast.parse(code)
                    for node in ast.walk(tree):
                        # 1. 函数调用
                        if isinstance(node, ast.Call):
                            if isinstance(node.func, ast.Name):
                                symbols.add(node.func.id)
                            elif isinstance(node.func, ast.Attribute):
                                symbols.add(node.func.attr)
                        # 2. 类型注记与类继承
                        elif isinstance(node, ast.Name):
                            symbols.add(node.id)
                        elif isinstance(node, ast.Attribute):
                            symbols.add(node.attr)
                except SyntaxError:
                    # 片段不自闭合时降级为通用正则提取
                    is_py = False

            if not is_py:
                # 通用语言：提取驼峰标识符与调用模式
                # 1. 驼峰命名 (如 TokenValidator, AuthService)
                for m in re.finditer(r"\b([A-Z][a-zA-Z0-9_]{2,})\b", code):
                    symbols.add(m.group(1))
                # 2. 调用表达式 (如 verify_token(...))
                for m in re.finditer(r"\b([a-z_][a-zA-Z0-9_]{3,})\s*\(", code):
                    symbols.add(m.group(1))

        # 过滤内置关键字和极短变量
        valid_symbols = {
            s for s in symbols
            if len(s) >= 3 and s not in _PY_BUILTINS and not s.startswith("__")
        }
        return valid_symbols

    def _resolve_dependencies(
        self, symbols: set[str], exclude_paths: set[str], max_deps: int = 5
    ) -> list[DependencyBlock]:
        """在仓库现有索引中秒级反查符号定义并提取声明。"""
        if not symbols:
            return []

        deps: list[DependencyBlock] = []
        seen_syms: set[str] = set()

        # 最多处理前 10 个候选符号，避免开销
        sorted_syms = sorted(symbols, key=len, reverse=True)[:10]

        for sym in sorted_syms:
            if sym in seen_syms:
                continue

            # 使用 Tantivy 短语查询精准反查符号
            query_str = f'"{sym}"'
            try:
                res = self.searcher.search(query_str, limit=3)
            except Exception:
                continue

            for hit in res.hits:
                if hit.path in exclude_paths:
                    continue

                content = _read_disk_file(hit.path)
                if not content:
                    continue

                found = _find_symbol_definition(content, sym, hit.path)
                if found:
                    deps.append(found)
                    seen_syms.add(sym)
                    break

            if len(deps) >= max_deps:
                break

        return deps

    def _fit_budget(
        self,
        query: str,
        anchors: list[AnchorBlock],
        dependencies: list[DependencyBlock],
        budget_tokens: int,
    ) -> tuple[list[AnchorBlock], list[DependencyBlock], int]:
        """按优先级分配 Token 预算：保留 Anchor > 保留 Deps 签名 > 适度截断。"""
        # 先以空骨架试算
        base_overhead = estimate_tokens(f"# Context Capsule: `{query}`\n> Tokens...\n")
        remaining = budget_tokens - base_overhead

        accepted_anchors: list[AnchorBlock] = []
        for anchor in anchors:
            cost = estimate_tokens(anchor.code) + 50
            if remaining - cost >= 0 or not accepted_anchors:
                accepted_anchors.append(anchor)
                remaining -= cost
            else:
                break

        accepted_deps: list[DependencyBlock] = []
        for dep in dependencies:
            cost = estimate_tokens(dep.code) + 30
            if remaining - cost >= 0:
                accepted_deps.append(dep)
                remaining -= cost
            else:
                # 预算吃紧时，尝试缩短为单行签名
                first_line = dep.code.splitlines()[0] if dep.code else ""
                short_cost = estimate_tokens(first_line) + 20
                if remaining - short_cost >= 0:
                    accepted_deps.append(
                        DependencyBlock(
                            symbol=dep.symbol,
                            file_path=dep.file_path,
                            line_no=dep.line_no,
                            kind=dep.kind,
                            code=first_line + "  # ... [truncated for token budget]",
                        )
                    )
                    remaining -= short_cost
                break

        # 计算实际估算的最终总 Tokens
        dummy_capsule = ContextCapsule(
            query=query,
            budget_tokens=budget_tokens,
            estimated_tokens=0,
            anchors=accepted_anchors,
            dependencies=accepted_deps,
            files_involved=[],
        )
        total_tokens = estimate_tokens(dummy_capsule.to_markdown())
        return accepted_anchors, accepted_deps, total_tokens


def _find_symbol_definition(content: str, symbol: str, file_path: str) -> DependencyBlock | None:
    """从文件源码中定位符号的类/函数/常量定义，并提取简要签名或短实现。"""
    lines = content.splitlines()
    is_py = file_path.endswith(".py")

    if is_py:
        try:
            tree = ast.parse(content)
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    if node.name == symbol:
                        start_l = node.lineno - 1
                        end_l = getattr(node, "end_lineno", start_l + 1)
                        # 如果函数或类很短（<= 18 行），整段包含；否则仅截取签名和 docstring
                        kind = "class" if isinstance(node, ast.ClassDef) else "def"
                        if end_l - start_l <= 18:
                            code_slice = "\n".join(lines[start_l:end_l])
                        else:
                            # 提取前 8 行并打断
                            cut_end = min(start_l + 8, len(lines))
                            code_slice = "\n".join(lines[start_l:cut_end]) + "\n    # ... [implementation omitted]"
                        return DependencyBlock(
                            symbol=symbol,
                            file_path=file_path,
                            line_no=node.lineno,
                            kind=kind,
                            code=code_slice,
                        )
        except SyntaxError:
            pass

    # 正则降级匹配 (支持 Python, Go, Rust, TS/JS, Java 等)
    pattern = re.compile(
        rf"^\s*(?:(?:export|pub|public|private|async|const|final)\s+)*"
        rf"(class|def|fn|func|function|interface|type|struct)\s+{re.escape(symbol)}\b",
        re.MULTILINE,
    )
    for idx, line in enumerate(lines):
        m = pattern.search(line)
        if m:
            kind = m.group(1)
            # 取后 6 行作为签名展示
            snippet = "\n".join(lines[idx : min(idx + 6, len(lines))])
            return DependencyBlock(
                symbol=symbol,
                file_path=file_path,
                line_no=idx + 1,
                kind=kind,
                code=snippet,
            )

    return None


def copy_text_to_clipboard(text: str) -> bool:
    """跨平台写入系统剪贴板（macOS: pbcopy, Linux: xclip/wl-copy, Windows: clip）。"""
    if not text:
        return False

    # 1. macOS
    if shutil.which("pbcopy"):
        try:
            p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE, close_fds=True)
            p.communicate(input=text.encode("utf-8"))
            return p.returncode == 0
        except OSError:
            pass

    # 2. Linux Wayland
    if shutil.which("wl-copy"):
        try:
            p = subprocess.Popen(["wl-copy"], stdin=subprocess.PIPE, close_fds=True)
            p.communicate(input=text.encode("utf-8"))
            return p.returncode == 0
        except OSError:
            pass

    # 3. Linux X11
    if shutil.which("xclip"):
        try:
            p = subprocess.Popen(["xclip", "-selection", "clipboard"], stdin=subprocess.PIPE, close_fds=True)
            p.communicate(input=text.encode("utf-8"))
            return p.returncode == 0
        except OSError:
            pass

    # 4. Windows
    if shutil.which("clip"):
        try:
            p = subprocess.Popen(["clip"], stdin=subprocess.PIPE, close_fds=True)
            p.communicate(input=text.encode("utf-8"))
            return p.returncode == 0
        except OSError:
            pass

    return False
