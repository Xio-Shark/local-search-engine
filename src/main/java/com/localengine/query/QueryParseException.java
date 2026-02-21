package com.localengine.query;

public class QueryParseException extends RuntimeException {
    private final int position;
    private final String queryString;
    private final String suggestion;

    public QueryParseException(String message, int position, String queryString) {
        super(buildMessage(message, position, queryString));
        this.position = position;
        this.queryString = queryString;
        this.suggestion = suggestFix(position, queryString);
    }

    public int getPosition() {
        return position;
    }

    public String getQueryString() {
        return queryString;
    }

    public String getSuggestion() {
        return suggestion;
    }

    private static String buildMessage(String message, int pos, String query) {
        int caretPos = Math.max(0, Math.min(pos, query.length()));
        String pointer = " ".repeat(caretPos) + "^";
        return "Parse error at position " + pos + ": " + message + System.lineSeparator()
                + query + System.lineSeparator() + pointer;
    }

    private static String suggestFix(int pos, String query) {
        if (query == null || query.isBlank()) {
            return "请输入非空查询";
        }
        if (pos >= query.length() && query.chars().filter(ch -> ch == '"').count() % 2 != 0) {
            return "检测到未闭合引号，请补全右引号";
        }
        return "请检查该位置附近的语法，例如括号、引号或布尔运算符";
    }
}
