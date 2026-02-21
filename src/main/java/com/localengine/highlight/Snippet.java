package com.localengine.highlight;

import java.util.List;

public record Snippet(
        String text,
        int lineNumber,
        int offset,
        List<HighlightSpan> highlights
) {
}
