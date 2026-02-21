package com.localengine.query;

import java.util.ArrayList;
import java.util.List;
import java.util.Set;

public class QueryParser {
    private static final Set<String> SUPPORTED_FIELDS = Set.of("path", "ext", "size", "mtime", "type", "filename", "name");

    private List<LexToken> tokens;
    private int pos;
    private String queryString;

    /**
     * 将查询字符串解析为 AST 与排序指令。
     */
    public ParseResult parse(String query) {
        this.tokens = new QueryLexer().tokenize(query);
        this.pos = 0;
        this.queryString = query == null ? "" : query;

        QueryNode ast = parseQuery();
        QueryNode.SortDirective sort = extractSortDirective();

        if (current().type() != TokenType.EOF) {
            throw new QueryParseException("意外token: " + current().value(), current().position(), queryString);
        }

        return new ParseResult(ast, sort);
    }

    /**
     * 解析查询入口，按 OR 层级组合子表达式。
     */
    private QueryNode parseQuery() {
        QueryNode left = parseOrExpression();
        if (left == null) {
            throw new QueryParseException("查询不能为空", current().position(), queryString);
        }
        return left;
    }

    /**
     * 解析 OR 层级，优先级低于 AND。
     */
    private QueryNode parseOrExpression() {
        QueryNode left = parseAndExpression();
        while (match(TokenType.OR)) {
            QueryNode right = parseAndExpression();
            left = new QueryNode.BooleanQuery(QueryNode.BoolOp.OR, left, right);
        }
        return left;
    }

    /**
     * 解析 AND 层级，并支持相邻子句的隐式 AND。
     */
    private QueryNode parseAndExpression() {
        QueryNode left = parseClause();
        while (true) {
            if (match(TokenType.AND)) {
                QueryNode right = parseClause();
                left = new QueryNode.BooleanQuery(QueryNode.BoolOp.AND, left, right);
                continue;
            }
            if (isImplicitAndStart(current().type())) {
                QueryNode right = parseClause();
                left = new QueryNode.BooleanQuery(QueryNode.BoolOp.AND, left, right);
                continue;
            }
            break;
        }
        return left;
    }

    /**
     * 解析可选前缀操作符后的子句。
     */
    private QueryNode parseClause() {
        if (match(TokenType.AND) || match(TokenType.OR)) {
            return parseClause();
        }
        if (match(TokenType.NOT) || match(TokenType.MINUS)) {
            return new QueryNode.NotQuery(parseClause());
        }
        return parseExpression();
    }

    /**
     * 解析基础表达式：分组、字段、短语、前缀、词项。
     */
    private QueryNode parseExpression() {
        if (current().type() == TokenType.LPAREN) {
            return parseGroup();
        }

        if (current().type() == TokenType.FIELD) {
            return parseFieldExpr();
        }

        if (current().type() == TokenType.PHRASE) {
            return parsePhrase();
        }

        if (current().type() == TokenType.TERM) {
            return parseTermOrPrefix();
        }

        throw new QueryParseException("无法解析表达式: " + current().value(), current().position(), queryString);
    }

    /**
     * 解析分组表达式，括号内继续按完整优先级解析。
     */
    private QueryNode parseGroup() {
        expect(TokenType.LPAREN, "缺少左括号");
        QueryNode grouped = parseQuery();
        expect(TokenType.RPAREN, "缺少右括号");
        return grouped;
    }

    /**
     * 解析字段表达式，支持普通值与范围值。
     */
    private QueryNode parseFieldExpr() {
        LexToken fieldToken = advance();
        String field = fieldToken.value().toLowerCase();
        if (!SUPPORTED_FIELDS.contains(field)) {
            throw new QueryParseException("不支持字段: " + field, fieldToken.position(), queryString);
        }

        expect(TokenType.COLON, "字段查询缺少冒号");
        LexToken valueToken = current();
        if (!isValueToken(valueToken.type())) {
            throw new QueryParseException("字段查询缺少值", valueToken.position(), queryString);
        }
        advance();

        if (match(TokenType.RANGE_SEP)) {
            LexToken toToken = current();
            if (!isValueToken(toToken.type())) {
                throw new QueryParseException("范围查询缺少结束值", toToken.position(), queryString);
            }
            advance();
            return new QueryNode.RangeQuery(field, valueToken.value(), toToken.value());
        }

        return new QueryNode.FieldQuery(field, valueToken.value());
    }

    /**
     * 解析短语表达式并拆分为词项序列。
     */
    private QueryNode parsePhrase() {
        String phrase = advance().value();
        List<String> terms = new ArrayList<>();
        for (String token : phrase.split("\\s+")) {
            if (!token.isBlank()) {
                terms.add(token);
            }
        }
        if (terms.isEmpty()) {
            throw new QueryParseException("短语不能为空", current().position(), queryString);
        }
        return new QueryNode.PhraseQuery(List.copyOf(terms));
    }

    /**
     * 解析词项或前缀查询（term*）。
     */
    private QueryNode parseTermOrPrefix() {
        LexToken termToken = advance();
        if (match(TokenType.STAR)) {
            return new QueryNode.PrefixQuery(termToken.value());
        }
        return new QueryNode.TermQuery(termToken.value());
    }

    /**
     * 提取末尾 sort 指令，不参与检索 AST。
     */
    private QueryNode.SortDirective extractSortDirective() {
        if (!match(TokenType.SORT)) {
            return null;
        }
        LexToken fieldToken = current();
        if (fieldToken.type() != TokenType.TERM && fieldToken.type() != TokenType.FIELD) {
            throw new QueryParseException("sort 指令缺少字段", fieldToken.position(), queryString);
        }
        advance();
        return new QueryNode.SortDirective(fieldToken.value());
    }

    /**
     * 断言当前 token 类型符合预期，否则抛出带位置的语法错误。
     */
    private void expect(TokenType type, String message) {
        if (!match(type)) {
            throw new QueryParseException(message, current().position(), queryString);
        }
    }

    /**
     * 判断 token 是否可作为字段值。
     */
    private boolean isValueToken(TokenType type) {
        return type == TokenType.TERM || type == TokenType.PHRASE || type == TokenType.FIELD;
    }

    /**
     * 判断当前 token 是否可触发隐式 AND。
     */
    private boolean isImplicitAndStart(TokenType type) {
        return type == TokenType.TERM
                || type == TokenType.PHRASE
                || type == TokenType.FIELD
                || type == TokenType.LPAREN
                || type == TokenType.NOT
                || type == TokenType.MINUS;
    }

    /**
     * 返回当前位置 token。
     */
    private LexToken current() {
        return tokens.get(pos);
    }

    /**
     * 消费并返回当前位置 token。
     */
    private LexToken advance() {
        return tokens.get(pos++);
    }

    /**
     * 若当前位置匹配指定类型则消费并返回 true。
     */
    private boolean match(TokenType type) {
        if (current().type() == type) {
            pos++;
            return true;
        }
        return false;
    }

    public record ParseResult(QueryNode ast, QueryNode.SortDirective sort) {
    }
}
