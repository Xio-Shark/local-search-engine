package com.localengine.query;

import com.localengine.document.Document;
import com.localengine.highlight.Snippet;

import java.util.List;

public record SearchHit(
        Document document,
        double score,
        List<Snippet> snippets
) {
}
