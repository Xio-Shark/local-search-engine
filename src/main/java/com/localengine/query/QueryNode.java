package com.localengine.query;

import java.util.List;

public sealed interface QueryNode permits QueryNode.TermQuery, QueryNode.PrefixQuery,
        QueryNode.PhraseQuery, QueryNode.BooleanQuery, QueryNode.NotQuery,
        QueryNode.FieldQuery, QueryNode.RangeQuery, QueryNode.SortDirective {

    /** 布尔操作类型 */
    enum BoolOp {
        AND,
        OR
    }

    record TermQuery(String term) implements QueryNode {
    }

    record PrefixQuery(String prefix) implements QueryNode {
    }

    record PhraseQuery(List<String> terms) implements QueryNode {
    }

    record BooleanQuery(BoolOp op, QueryNode left, QueryNode right) implements QueryNode {
    }

    record NotQuery(QueryNode child) implements QueryNode {
    }

    record FieldQuery(String field, String value) implements QueryNode {
    }

    record RangeQuery(String field, String from, String to) implements QueryNode {
    }

    record SortDirective(String field) implements QueryNode {
    }
}
