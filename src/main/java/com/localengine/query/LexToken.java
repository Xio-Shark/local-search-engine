package com.localengine.query;

public record LexToken(TokenType type, String value, int position) {
}

enum TokenType {
    TERM,
    PHRASE,
    FIELD,
    RANGE_SEP,
    LPAREN,
    RPAREN,
    AND,
    OR,
    NOT,
    MINUS,
    SORT,
    STAR,
    COLON,
    EOF
}
