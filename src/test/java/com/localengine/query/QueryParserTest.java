package com.localengine.query;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import org.junit.jupiter.api.Test;

class QueryParserTest {
    @Test
    void testSimpleTerm() {
        assertParse("hello", QueryNode.TermQuery.class);
    }

    @Test
    void testPhrase() {
        assertParse("\"distributed system\"", QueryNode.PhraseQuery.class);
    }

    @Test
    void testPrefix() {
        assertParse("config*", QueryNode.PrefixQuery.class);
    }

    @Test
    void testImplicitAnd() {
        QueryNode node = parse("hello world");
        QueryNode.BooleanQuery booleanQuery = assertInstanceOf(QueryNode.BooleanQuery.class, node);
        assertEquals(QueryNode.BoolOp.AND, booleanQuery.op());
    }

    @Test
    void testExplicitAnd() {
        assertParse("error AND timeout", QueryNode.BooleanQuery.class);
    }

    @Test
    void testOrInGroup() {
        assertParse("error AND (timeout OR retry)", QueryNode.BooleanQuery.class);
    }

    @Test
    void testNot() {
        assertParse("-draft", QueryNode.NotQuery.class);
    }

    @Test
    void testFieldFilter() {
        assertParse("ext:md", QueryNode.FieldQuery.class);
    }

    @Test
    void testFileNameFieldFilter() {
        assertParse("filename:readme.md", QueryNode.FieldQuery.class);
    }

    @Test
    void testRangeQuery() {
        assertParse("mtime:2025-01-01..2025-12-31", QueryNode.RangeQuery.class);
    }

    @Test
    void testComplex() {
        QueryNode node = parse("error AND (timeout OR retry) -draft ext:md");
        QueryNode.BooleanQuery root = assertInstanceOf(QueryNode.BooleanQuery.class, node);
        assertEquals(QueryNode.BoolOp.AND, root.op());
    }

    @Test
    void testUnclosedQuoteError() {
        assertThrows(QueryParseException.class, () -> parse("\"unclosed"));
    }

    private QueryNode parse(String query) {
        return new QueryParser().parse(query).ast();
    }

    private void assertParse(String query, Class<? extends QueryNode> expectedType) {
        assertTrue(expectedType.isInstance(parse(query)));
    }
}
