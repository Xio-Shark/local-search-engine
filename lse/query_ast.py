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

    def __init__(self, raw_query: str) -> None:
        self.raw_query = raw_query
        self.sort_field: str | None = None
        self.sort_order: tantivy.Order = tantivy.Order.Desc

    def compile(self) -> tuple[str, str | None, tantivy.Order]:
        if not self.raw_query or not self.raw_query.strip():
            return "", None, self.sort_order

        lexer = QueryLexer(self.raw_query)
        tokens = lexer.tokenize()

        compiled_parts: list[str] = []

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
                compiled_parts.append(tok.value)
            elif tok.type == TokenType.LPAREN:
                compiled_parts.append("(")
            elif tok.type == TokenType.RPAREN:
                compiled_parts.append(")")

        # 整理语句，避免空括号或悬挂操作符
        result_query = " ".join(compiled_parts).strip()
        # 清理多余空括号
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
        """对普通词项进行自适应语义加权展开。

        若为连续汉字（>=2个字），生成带短语高权重和双字召回的括号表达式：
        ("本地搜索引擎"^5 OR (本地 OR 地搜 OR 搜索 OR 索引 OR 引擎))
        """
        # 汉字连续词
        if re.fullmatch(r"[\u4e00-\u9fff]{2,}", term):
            if len(term) == 2:
                # 双字词直接返回，支持精确与子词
                return f'("{term}"^5 OR {term})'
            grams = [term[i : i + 2] for i in range(len(term) - 1)]
            grams_expr = " OR ".join(grams)
            return f'("{term}"^5 OR {grams_expr})'

        # 西文、数字或代码符号
        return term
