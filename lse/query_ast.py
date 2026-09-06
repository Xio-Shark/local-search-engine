"""形式化查询语法分析器与 AST 编译器。

支持：
1. 字段别名安全映射 (ext -> extension, type -> doc_type 等)
2. 数值与日期范围编译 (size:10KB..5MB -> size:[10240 TO 5242880], mtime:2025-01-01..2025-12-31)
3. 提取原生排序指令 (sort:mtime:asc / sort:size:desc)
4. 多语言与混合词项自适应短语加权展开 (消除正则拼接缺陷，严格括号隔离)
5. 语法容错 (未闭合引号/非法布尔符号自愈，杜绝语法崩溃)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum, auto

import tantivy


class TokenType(Enum):
    TERM = auto()
    PHRASE = auto()
    FIELD_EXPR = auto()
    SORT = auto()
    AND = auto()
    OR = auto()
    NOT = auto()
    LPAREN = auto()
    RPAREN = auto()


@dataclass
class Token:
    type: TokenType
    value: str


# 字段别名表
FIELD_ALIASES: dict[str, str] = {
    "ext": "extension",
    "type": "doc_type",
    "name": "filename",
    "filename": "filename",
    "path": "path",
    "size": "size",
    "mtime": "mtime",
    "content": "content",
}

from .concepts import BASE_TECHNICAL_CONCEPTS

# 双向技术概念投影表（弥补纯 BM25 面对自然语言与纯代码库的词汇鸿沟，支持动态扩展）
TECHNICAL_CONCEPT_MAP: dict[str, list[str]] = BASE_TECHNICAL_CONCEPTS


def parse_bytes(val: str) -> int:
    """解析带单位的大小字符串为字节数。"""
    val = val.strip().upper()
    if val.endswith("KB"):
        return int(float(val[:-2]) * 1024)
    if val.endswith("MB"):
        return int(float(val[:-2]) * 1024 * 1024)
    if val.endswith("GB"):
        return int(float(val[:-2]) * 1024 * 1024 * 1024)
    if val.endswith("B"):
        return int(val[:-1])
    return int(val)


class QueryLexer:
    """查询词法分析器。"""

    def __init__(self, raw_query: str) -> None:
        self.raw = raw_query.strip()
        self.pos = 0
        self.length = len(self.raw)

    def tokenize(self) -> list[Token]:
        tokens: list[Token] = []
        while self.pos < self.length:
            ch = self.raw[self.pos]
            if ch.isspace():
                self.pos += 1
                continue

            if ch == "(":
                tokens.append(Token(TokenType.LPAREN, "("))
                self.pos += 1
                continue
            if ch == ")":
                tokens.append(Token(TokenType.RPAREN, ")"))
                self.pos += 1
                continue

            # 引号包裹短语
            if ch == '"':
                phrase_val = self._consume_quoted()
                tokens.append(Token(TokenType.PHRASE, phrase_val))
                continue

            # 普通单词或 field:expr / sort:expr
            word = self._consume_word()
            upper_w = word.upper()

            if upper_w == "AND":
                tokens.append(Token(TokenType.AND, "AND"))
            elif upper_w == "OR":
                tokens.append(Token(TokenType.OR, "OR"))
            elif upper_w == "NOT":
                tokens.append(Token(TokenType.NOT, "NOT"))
            elif word.lower().startswith("sort:"):
                tokens.append(Token(TokenType.SORT, word))
            elif ":" in word and not word.startswith(":"):
                tokens.append(Token(TokenType.FIELD_EXPR, word))
            else:
                tokens.append(Token(TokenType.TERM, word))

        return tokens

    def _consume_quoted(self) -> str:
        self.pos += 1  # skip leading quote
        start = self.pos
        escaped = False
        while self.pos < self.length:
            ch = self.raw[self.pos]
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                val = self.raw[start : self.pos]
                self.pos += 1
                return val
            self.pos += 1
        # 未闭合引号，容错闭合
        return self.raw[start:]

    def _consume_word(self) -> str:
        start = self.pos
        in_bracket = False
        while self.pos < self.length:
            ch = self.raw[self.pos]
            if ch == "[":
                in_bracket = True
            elif ch == "]":
                in_bracket = False

            if not in_bracket and (ch.isspace() or ch in "()\""):
                break
            self.pos += 1
        return self.raw[start : self.pos]


class QueryCompiler:
    """AST 编译器：编译为健壮的 Tantivy Query 串并剥离排序指令。"""

    def __init__(self, raw_query: str, concept_map: dict[str, list[str]] | None = None) -> None:
        self.raw_query = raw_query
        self.concept_map = concept_map or TECHNICAL_CONCEPT_MAP
        self.sort_field: str | None = None
        self.sort_order: tantivy.Order = tantivy.Order.Desc

    def compile(self) -> tuple[str, str | None, tantivy.Order]:
        if not self.raw_query or not self.raw_query.strip():
            return "", None, self.sort_order

        lexer = QueryLexer(self.raw_query)
        tokens = lexer.tokenize()

        compiled_parts: list[str] = []
        open_parens = 0

        for tok in tokens:
            if tok.type == TokenType.SORT:
                self._handle_sort(tok.value)
            elif tok.type == TokenType.FIELD_EXPR:
                compiled_parts.append(self._compile_field_expr(tok.value))
            elif tok.type == TokenType.PHRASE:
                # 短语保持精确双引号
                compiled_parts.append(f'"{tok.value}"')
            elif tok.type == TokenType.TERM:
                compiled_parts.append(self._compile_term(tok.value))
            elif tok.type in (TokenType.AND, TokenType.OR, TokenType.NOT):
                # 避免连续重复操作符
                if compiled_parts and compiled_parts[-1] in ("AND", "OR", "NOT"):
                    compiled_parts[-1] = tok.value
                else:
                    compiled_parts.append(tok.value)
            elif tok.type == TokenType.LPAREN:
                open_parens += 1
                compiled_parts.append("(")
            elif tok.type == TokenType.RPAREN:
                if open_parens > 0:
                    open_parens -= 1
                    compiled_parts.append(")")
                # 忽略多余的未匹配闭合括号

        # 自愈：补齐所有未闭合的左括号
        while open_parens > 0:
            compiled_parts.append(")")
            open_parens -= 1

        # 清除开头和末尾悬挂的布尔运算符
        while compiled_parts and compiled_parts[0] in ("AND", "OR"):
            compiled_parts.pop(0)
        while compiled_parts and compiled_parts[-1] in ("AND", "OR", "NOT"):
            compiled_parts.pop()

        # 整理语句，清理多余空括号
        result_query = " ".join(compiled_parts).strip()
        result_query = re.sub(r"\(\s*\)", "", result_query).strip()
        # 清除类似 ( AND 或 OR ) 的非法嵌套运算符
        result_query = re.sub(r"\(\s*(?:AND|OR)\s+", "(", result_query)
        result_query = re.sub(r"\s+(?:AND|OR|NOT)\s*\)", ")", result_query)
        result_query = re.sub(r"\(\s*\)", "", result_query).strip()

        return result_query, self.sort_field, self.sort_order

    def _handle_sort(self, sort_expr: str) -> None:
        # e.g., sort:mtime, sort:size:asc, sort:mtime:desc
        m = re.match(r"^sort:([a-zA-Z_]+)(?::(asc|desc))?$", sort_expr, re.IGNORECASE)
        if m:
            field_name = m.group(1).lower()
            order_str = (m.group(2) or "desc").lower()
            if field_name in ("mtime", "size"):
                self.sort_field = field_name
                self.sort_order = tantivy.Order.Asc if order_str == "asc" else tantivy.Order.Desc

    def _compile_field_expr(self, expr: str) -> str:
        parts = expr.split(":", 1)
        if len(parts) != 2:
            return expr

        field_name, val = parts[0].lower(), parts[1]
        target_field = FIELD_ALIASES.get(field_name, field_name)

        # 1. size 范围处理 (例如 size:10KB..5MB 或 size:100..5000)
        size_range_match = re.match(
            r"^(\d+(?:\.\d+)?(?:[KMGT]?B)?)\.\.(\d+(?:\.\d+)?(?:[KMGT]?B)?)$",
            val,
            re.IGNORECASE,
        )
        if size_range_match and target_field == "size":
            start_str, end_str = size_range_match.groups()
            start_val = parse_bytes(start_str) if start_str else "*"
            end_val = parse_bytes(end_str) if end_str else "*"
            return f"size:[{start_val} TO {end_val}]"

        # 2. mtime 日期范围处理 (例如 mtime:2025-01-01..2025-12-31)
        date_range_match = re.match(
            r"^(\d{4}-\d{2}-\d{2})\.\.(\d{4}-\d{2}-\d{2})$", val
        )
        if date_range_match and target_field == "mtime":
            d_start, d_end = date_range_match.groups()
            return f"mtime:[{d_start}T00:00:00Z TO {d_end}T23:59:59Z]"

        # 3. 后缀名去除点号 (ext:.md -> extension:md)
        if target_field == "extension":
            val = val.lstrip(".")

        return f"{target_field}:{val}"

    def _compile_term(self, term: str) -> str:
        """对普通词项进行自适应语义加权展开与双向技术概念投影。

        若为连续汉字（>=2个字），生成带短语高权重和双字召回的括号表达式：
        ("本地搜索引擎"^5 OR (本地 OR 地搜 OR 搜索 OR 索引 OR 引擎))
        若匹配技术领域概念，则自适应吸附中英双向映射词项（^0.8加权）。
        """
        term_lower = term.lower()

        # 1. 汉字连续词
        if re.fullmatch(r"[\u4e00-\u9fff]{2,}", term):
            sub_words: list[str] = []
            try:
                import jieba
                sub_words = [w for w in jieba.cut_for_search(term) if w != term and len(w) >= 2]
            except Exception:
                sub_words = []

            if not sub_words and len(term) > 2:
                sub_words = [term[i : i + 2] for i in range(len(term) - 1)]

            # 收集概念投影词
            concept_additions: list[str] = []
            if term in self.concept_map:
                concept_additions.extend(self.concept_map[term][:3])
            for sw in sub_words:
                if sw in self.concept_map:
                    concept_additions.extend(self.concept_map[sw][:2])

            seen = set()
            clean_sub = []
            for w in sub_words:
                if w not in seen:
                    seen.add(w)
                    clean_sub.append(w)

            # 概念投影词去重与加权
            clean_concepts = []
            for c in concept_additions:
                if c not in seen and c != term and c not in clean_sub:
                    seen.add(c)
                    clean_concepts.append(f'"{c}"^0.8' if " " in c else f"{c}^0.8")

            all_sub_clauses = clean_sub + clean_concepts[:4]
            if len(term) == 2:
                if clean_concepts:
                    return f'("{term}"^5 OR {term} OR {" OR ".join(clean_concepts[:3])})'
                return f'("{term}"^5 OR {term})'

            sub_expr = " OR ".join(all_sub_clauses)
            return f'("{term}"^5 OR {sub_expr})' if sub_expr else f'"{term}"'

        # 2. 中英混排（如 目录A、C++多线程、GPT-4o架构）
        if re.search(r"[\u4e00-\u9fff]", term) and re.search(r"[a-zA-Z0-9]", term):
            from .tokenizer import tokenize_stream
            parts = [t for t in tokenize_stream(term) if t]
            seen = set()
            unique_parts = []
            for p in parts:
                if p not in seen:
                    seen.add(p)
                    unique_parts.append(p)
            if len(unique_parts) > 1:
                return f'({" AND ".join(unique_parts)})'

        # 3. 西文、数字或代码符号：概念投影展开
        if term_lower in self.concept_map:
            concepts = self.concept_map[term_lower][:3]
            c_clauses = [f'"{c}"^0.8' if " " in c else f"{c}^0.8" for c in concepts if c.lower() != term_lower]
            if c_clauses:
                return f'({term} OR {" OR ".join(c_clauses)})'

        return term
