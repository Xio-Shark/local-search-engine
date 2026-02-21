package com.localengine.text;

import java.util.Set;

public final class StopWords {

    public static final Set<String> ENGLISH = Set.of(
        "the", "a", "an", "is", "are", "was", "were", "be", "been",
        "has", "have", "had", "do", "does", "did", "will", "would",
        "could", "should", "may", "might", "can", "and", "or", "but",
        "not", "in", "on", "at", "to", "for", "of", "with", "by",
        "from", "as", "into", "it", "its", "this", "that", "which",
        "if", "so", "no", "up", "out", "all", "just", "also", "very"
    );

    private StopWords() {
    }

    /**
     * 判断词项是否为英文停用词。
     */
    public static boolean isStopWord(String term) {
        if (term == null || term.isEmpty()) {
            return false;
        }
        return ENGLISH.contains(term.toLowerCase());
    }
}
