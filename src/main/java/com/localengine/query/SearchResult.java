package com.localengine.query;

import java.util.List;

public record SearchResult(
        List<SearchHit> hits,
        int totalMatches,
        long elapsedMs,
        String query
) {
}
