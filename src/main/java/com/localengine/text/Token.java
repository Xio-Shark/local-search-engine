package com.localengine.text;

public record Token(
    String term,
    int position,
    int startOffset,
    int endOffset
) {
}
