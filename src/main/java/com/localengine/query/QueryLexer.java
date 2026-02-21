package com.localengine.query;

import java.util.ArrayList;
import java.util.List;

public class QueryLexer {
    /**
     * 将原始查询字符串切分为词法 token 序列。
     */
    public List<LexToken> tokenize(String query) {
        if (query == null) {
            throw new QueryParseException("查询字符串不能为空", 0, "");
        }

        List<LexToken> tokens = new ArrayList<>();
        int index = 0;
        while (index < query.length()) {
            char currentChar = query.charAt(index);
            if (Character.isWhitespace(currentChar)) {
                index++;
                continue;
            }

            if (currentChar == '"') {
                index = readPhraseToken(query, index, tokens);
                continue;
            }

            if (currentChar == '(') {
                tokens.add(new LexToken(TokenType.LPAREN, "(", index));
                index++;
                continue;
            }
            if (currentChar == ')') {
                tokens.add(new LexToken(TokenType.RPAREN, ")", index));
                index++;
                continue;
            }
            if (currentChar == '*') {
                tokens.add(new LexToken(TokenType.STAR, "*", index));
                index++;
                continue;
            }
            if (currentChar == ':') {
                tokens.add(new LexToken(TokenType.COLON, ":", index));
                index++;
                continue;
            }
            if (currentChar == '-') {
                tokens.add(new LexToken(TokenType.MINUS, "-", index));
                index++;
                continue;
            }
            if (currentChar == '.' && index + 1 < query.length() && query.charAt(index + 1) == '.') {
                tokens.add(new LexToken(TokenType.RANGE_SEP, "..", index));
                index += 2;
                continue;
            }

            int tokenStart = index;
            while (index < query.length() && !Character.isWhitespace(query.charAt(index))
                    && query.charAt(index) != '('
                    && query.charAt(index) != ')'
                    && query.charAt(index) != '"'
                    && query.charAt(index) != ':'
                    && query.charAt(index) != '*') {
                if (query.charAt(index) == '.' && index + 1 < query.length() && query.charAt(index + 1) == '.') {
                    break;
                }
                index++;
            }

            if (tokenStart == index) {
                throw new QueryParseException("无法识别字符: " + currentChar, index, query);
            }

            String value = query.substring(tokenStart, index);
            String upper = value.toUpperCase();

            if ("AND".equals(upper)) {
                tokens.add(new LexToken(TokenType.AND, value, tokenStart));
                continue;
            }
            if ("OR".equals(upper)) {
                tokens.add(new LexToken(TokenType.OR, value, tokenStart));
                continue;
            }
            if ("NOT".equals(upper)) {
                tokens.add(new LexToken(TokenType.NOT, value, tokenStart));
                continue;
            }

            if (isSortField(value, query, index)) {
                tokens.add(new LexToken(TokenType.SORT, value, tokenStart));
                continue;
            }

            if (isFieldName(value, query, index)) {
                tokens.add(new LexToken(TokenType.FIELD, value, tokenStart));
                continue;
            }

            tokens.add(new LexToken(TokenType.TERM, value, tokenStart));
        }

        tokens.add(new LexToken(TokenType.EOF, "", query.length()));
        return tokens;
    }

    /**
     * 读取带转义的双引号短语并追加 PHRASE token。
     */
    private int readPhraseToken(String query, int quoteIndex, List<LexToken> tokens) {
        int index = quoteIndex + 1;
        StringBuilder phraseBuilder = new StringBuilder();
        boolean closed = false;
        while (index < query.length()) {
            char currentChar = query.charAt(index);
            if (currentChar == '\\' && index + 1 < query.length()) {
                char escaped = query.charAt(index + 1);
                if (escaped == '"' || escaped == '\\') {
                    phraseBuilder.append(escaped);
                    index += 2;
                    continue;
                }
            }
            if (currentChar == '"') {
                closed = true;
                index++;
                break;
            }
            phraseBuilder.append(currentChar);
            index++;
        }
        if (!closed) {
            throw new QueryParseException("未闭合引号", quoteIndex, query);
        }
        tokens.add(new LexToken(TokenType.PHRASE, phraseBuilder.toString(), quoteIndex));
        return index;
    }

    /**
     * 判断当前词项是否为 sort 字段前缀。
     */
    private boolean isSortField(String value, String query, int index) {
        return "sort".equalsIgnoreCase(value) && index < query.length() && query.charAt(index) == ':';
    }

    /**
     * 判断当前词项是否应被识别为字段名。
     */
    private boolean isFieldName(String value, String query, int index) {
        if (value.isEmpty() || !Character.isLetter(value.charAt(0))) {
            return false;
        }
        return index < query.length() && query.charAt(index) == ':';
    }
}
