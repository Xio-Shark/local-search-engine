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
            exclude_spans: dict[str, list[tuple[int, int]]] = {}
            for a in anchors:
                exclude_spans.setdefault(a.file_path, []).append((a.start_line, a.end_line))
            dependencies = self._resolve_dependencies(
                candidate_symbols,
                anchors=anchors,
                exclude_spans=exclude_spans,
                exclude_paths=set(),
            )

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
        self,
        symbols: set[str],
        anchors: list[AnchorBlock] | None = None,
        exclude_paths: set[str] | None = None,
        exclude_spans: dict[str, list[tuple[int, int]]] | None = None,
        max_deps: int = 5,
    ) -> list[DependencyBlock]:
        """按优先级解析依赖符号定义：
        Phase 1: 静态导入直达 (从锚点文件的 import 语句中精确提取依赖目标)
        Phase 2: 同文件就地定义解析 (Intra-file Definition outside anchor spans)
        Phase 3: 全局 Tantivy 批量检索引擎兜底
        Phase 4: 极少数冷僻符号单次点查容错补漏
        """
        if not symbols:
            return []

        exclude_paths = exclude_paths or set()
        exclude_spans = exclude_spans or {}
        deps: list[DependencyBlock] = []
        seen_syms: set[str] = set()
        seen_defs: set[tuple[str, int]] = set()

        # 最多处理前 10 个候选符号，按符号长度倒序
        sorted_syms = [s for s in sorted(symbols, key=len, reverse=True) if len(s) >= 3][:10]
        if not sorted_syms:
            return []

        # 缓存已读取并解析的文件内容，避免重复读盘
        file_content_cache: dict[str, str] = {}

        def get_file_content(path: str) -> str:
            if path not in file_content_cache:
                file_content_cache[path] = _read_disk_file(path) or ""
            return file_content_cache[path]

        def try_add_dep(found: DependencyBlock | None, sym: str) -> bool:
            if not found:
                return False
            spans = exclude_spans.get(found.file_path, [])
            if any(start <= found.line_no <= end for start, end in spans):
                return False
            key = (found.file_path, found.line_no)
            if key in seen_defs:
                seen_syms.add(sym)
                return True
            seen_defs.add(key)
            seen_syms.add(sym)
            deps.append(found)
            return True

        # Phase 1: 静态导入直达 (JIT Static Import Resolution)
        if anchors:
            for anchor in anchors:
                if len(deps) >= max_deps:
                    break
                anchor_content = get_file_content(anchor.file_path)
                if not anchor_content:
                    continue
                sym_to_file, imported_files = _resolve_file_imports(anchor.file_path, anchor_content)

                # 1. 精确导入符号直达
                for sym in sorted_syms:
                    if sym in seen_syms or len(deps) >= max_deps:
                        continue
                    if sym in sym_to_file:
                        target_file = sym_to_file[sym]
                        if target_file in exclude_paths:
                            continue
                        target_content = get_file_content(target_file)
                        found = _find_symbol_definition(target_content, sym, target_file)
                        try_add_dep(found, sym)

                # 2. 导入模块内部符号/方法推导 (如通过 Class 实例调用的成员方法)
                for sym in sorted_syms:
                    if sym in seen_syms or len(deps) >= max_deps:
                        continue
                    for imp_file in imported_files:
                        if imp_file in exclude_paths:
                            continue
                        imp_content = get_file_content(imp_file)
                        if sym not in imp_content:
                            continue
                        found = _find_symbol_definition(imp_content, sym, imp_file)
                        if try_add_dep(found, sym):
                            break

        # Phase 2: 同文件就地定义解析 (Intra-file Definition outside anchor spans)
        if anchors and len(deps) < max_deps:
            for anchor in anchors:
                if anchor.file_path in exclude_paths or len(deps) >= max_deps:
                    continue
                anchor_content = get_file_content(anchor.file_path)
                for sym in sorted_syms:
                    if sym in seen_syms or len(deps) >= max_deps:
                        continue
                    if sym not in anchor_content:
                        continue
                    found = _find_symbol_definition(anchor_content, sym, anchor.file_path)
                    try_add_dep(found, sym)

        # Phase 3: 全局 Tantivy 批量检索引擎兜底
        if len(deps) < max_deps:
            remaining_syms = [s for s in sorted_syms if s not in seen_syms]
            if remaining_syms:
                batch_query = " OR ".join(f'"{s}"' for s in remaining_syms)
                candidate_files: list[str] = []
                try:
                    res = self.searcher.search(batch_query, limit=20)
                    for h in res.hits:
                        if h.path not in candidate_files:
                            candidate_files.append(h.path)
                except Exception:
                    pass

                for sym in remaining_syms:
                    if sym in seen_syms or len(deps) >= max_deps:
                        break
                    for file_path in candidate_files:
                        if file_path in exclude_paths:
                            continue
                        content = get_file_content(file_path)
                        if not content or sym not in content:
                            continue
                        found = _find_symbol_definition(content, sym, file_path)
                        if try_add_dep(found, sym):
                            break

        # Phase 4: 极少数冷僻符号单次点查容错补漏
        if len(deps) < max_deps:
            final_syms = [s for s in sorted_syms if s not in seen_syms]
            for sym in final_syms:
                if len(deps) >= max_deps:
                    break
                try:
                    res_single = self.searcher.search(f'"{sym}"', limit=3)
                except Exception:
                    continue
                for hit in res_single.hits:
                    if hit.path in exclude_paths:
                        continue
                    content = get_file_content(hit.path)
                    if not content or sym not in content:
                        continue
                    found = _find_symbol_definition(content, sym, hit.path)
                    if try_add_dep(found, sym):
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


def _resolve_file_imports(file_path: str, content: str) -> tuple[dict[str, str], list[str]]:
    """解析源文件中的 import 依赖关系（支持 Python AST 与 JS/TS 正则）。

    返回：
    - symbol_to_file: {imported_symbol: target_file_path}
    - imported_files: [target_file_path, ...]
    """
    symbol_to_file: dict[str, str] = {}
    imported_files: list[str] = []

    try:
        cur_path = Path(file_path).resolve()
        cur_dir = cur_path.parent
    except Exception:
        return symbol_to_file, imported_files

    # 向上寻找可能的项目根目录（最多 5 层）
    candidate_roots = [cur_dir]
    p = cur_dir
    for _ in range(5):
        p = p.parent
        if p == p.parent:
            break
        candidate_roots.append(p)

    # 1. Python 文件处理
    if file_path.endswith(".py"):
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return symbol_to_file, imported_files

        def _find_py_module(module_name: str | None, level: int) -> Path | None:
            if level > 0:
                base = cur_dir
                for _ in range(level - 1):
                    base = base.parent
                if module_name:
                    target = base.joinpath(*module_name.split("."))
                else:
                    target = base
                for ext in [".py", ".pyi"]:
                    f = target.with_suffix(ext)
                    if f.is_file():
                        return f
                init_f = target / "__init__.py"
                if init_f.is_file():
                    return init_f
                return None
            else:
                if not module_name:
                    return None
                parts = module_name.split(".")
                for root in candidate_roots:
                    target = root.joinpath(*parts)
                    for ext in [".py", ".pyi"]:
                        f = target.with_suffix(ext)
                        if f.is_file():
                            return f
                    init_f = target / "__init__.py"
                    if init_f.is_file():
                        return init_f
                return None

        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    mod_f = _find_py_module(alias.name, level=0)
                    if mod_f:
                        mod_str = str(mod_f)
                        name = alias.asname or alias.name.split(".")[-1]
                        symbol_to_file[name] = mod_str
                        if mod_str not in imported_files:
                            imported_files.append(mod_str)
            elif isinstance(node, ast.ImportFrom):
                mod_f = _find_py_module(node.module, level=node.level)
                if mod_f:
                    mod_str = str(mod_f)
                    if mod_str not in imported_files:
                        imported_files.append(mod_str)
                    for alias in node.names:
                        name = alias.asname or alias.name
                        symbol_to_file[name] = mod_str
                elif node.module is None and node.level > 0:
                    for alias in node.names:
                        sub_f = _find_py_module(alias.name, level=node.level)
                        if sub_f:
                            sub_str = str(sub_f)
                            name = alias.asname or alias.name
                            symbol_to_file[name] = sub_str
                            if sub_str not in imported_files:
                                imported_files.append(sub_str)

        return symbol_to_file, imported_files

    # 2. JavaScript / TypeScript 文件处理
    if any(file_path.endswith(ext) for ext in [".js", ".jsx", ".ts", ".tsx", ".mjs"]):
        js_import_pattern = re.compile(
            r"""import\s+(?:(?:\*\s+as\s+(\w+))|(?:\{([^}]+)\})|(\w+))\s+from\s+['"]([^'"]+)['"]"""
        )
        for m in js_import_pattern.finditer(content):
            star_alias, bracket_items, default_alias, mod_rel = m.groups()
            if mod_rel.startswith("."):
                target = (cur_dir / mod_rel).resolve()
                target_f = None
                for ext in [".ts", ".tsx", ".js", ".jsx"]:
                    cand = target.with_suffix(ext)
                    if cand.is_file():
                        target_f = cand
                        break
                if not target_f and target.is_dir():
                    for index_name in ["index.ts", "index.tsx", "index.js", "index.jsx"]:
                        cand = target / index_name
                        if cand.is_file():
                            target_f = cand
                            break
                if target_f:
                    target_str = str(target_f)
                    if target_str not in imported_files:
                        imported_files.append(target_str)
                    if star_alias:
                        symbol_to_file[star_alias] = target_str
                    if default_alias:
                        symbol_to_file[default_alias] = target_str
                    if bracket_items:
                        for item in bracket_items.split(","):
                            parts = item.strip().split()
                            if len(parts) == 3 and parts[1] == "as":
                                symbol_to_file[parts[2]] = target_str
                            elif parts:
                                symbol_to_file[parts[0]] = target_str

        return symbol_to_file, imported_files

    return symbol_to_file, imported_files


def _find_symbol_definition(content: str, symbol: str, file_path: str) -> DependencyBlock | None:
    """从文件源码中定位符号的类/函数/方法/常量定义，并提取简要签名或短实现。"""
    lines = content.splitlines()
    is_py = file_path.endswith(".py")

    if is_py:
        try:
            tree = ast.parse(content)
            target_node = None
            target_parent = None

            # 1. 优先在顶层语句及顶层类的方法中查找
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    if node.name == symbol:
                        target_node = node
                        break
                    if isinstance(node, ast.ClassDef):
                        for sub in node.body:
                            if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                                if sub.name == symbol:
                                    target_node = sub
                                    target_parent = node
                                    break
                        if target_node:
                            break

            # 2. 若未命中，通过递归遍历语法树查找所有嵌套定义
            if not target_node:
                for parent in ast.walk(tree):
                    for child in ast.iter_child_nodes(parent):
                        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                            if child.name == symbol:
                                target_node = child
                                target_parent = parent if isinstance(parent, ast.ClassDef) else None
                                break
                    if target_node:
                        break

            if target_node:
                start_l = target_node.lineno - 1
                end_l = getattr(target_node, "end_lineno", len(lines))
                kind = "class" if isinstance(target_node, ast.ClassDef) else (
                    "method" if target_parent else "def"
                )
                indent_str = " " * getattr(target_node, "col_offset", 0)
                if end_l - start_l <= 18:
                    code_slice = "\n".join(lines[start_l:end_l])
                else:
                    cut_end = min(start_l + 8, len(lines))
                    code_slice = "\n".join(lines[start_l:cut_end]) + f"\n{indent_str}    # ... [implementation omitted]"
                return DependencyBlock(
                    symbol=symbol,
                    file_path=file_path,
                    line_no=target_node.lineno,
                    kind=kind,
                    code=code_slice,
                )
        except SyntaxError:
            pass

    # 正则降级匹配 (支持 Python, Go, Rust, TS/JS, Java, C/C++ 等)
    pattern = re.compile(
        rf"^\s*(?:(?:export|pub|public|private|protected|async|static|const|final)\s+)*"
        rf"(class|def|fn|func|function|interface|type|struct|trait|enum)\s+{re.escape(symbol)}\b",
        re.MULTILINE,
    )
    for idx, line in enumerate(lines):
        m = pattern.search(line)
        if m:
            kind = m.group(1)
            # 智能闭合探测：支持大括号或缩进语法闭包
            def_indent = len(line) - len(line.lstrip())
            brace_count = line.count("{") - line.count("}")
            end_idx = idx
            if "{" in line:
                for j in range(idx + 1, min(idx + 50, len(lines))):
                    brace_count += lines[j].count("{") - lines[j].count("}")
                    end_idx = j
                    if brace_count <= 0:
                        break
            else:
                for j in range(idx + 1, min(idx + 50, len(lines))):
                    cur_line = lines[j]
                    if not cur_line.strip():
                        end_idx = j
                        continue
                    cur_indent = len(cur_line) - len(cur_line.lstrip())
                    if cur_indent <= def_indent and not cur_line.strip().startswith(("#", "//")):
                        break
                    end_idx = j

            span_len = end_idx - idx + 1
            if span_len <= 18:
                snippet = "\n".join(lines[idx : end_idx + 1])
            else:
                cut_end = min(idx + 8, len(lines))
                snippet = "\n".join(lines[idx:cut_end]) + "\n    // ... [implementation omitted]"

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
