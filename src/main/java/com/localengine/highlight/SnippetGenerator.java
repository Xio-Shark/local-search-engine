package com.localengine.highlight;

import com.localengine.config.Constants;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;

public class SnippetGenerator {
    private static final String ANSI_HIGHLIGHT = "\u001B[1;33m";
    private static final String ANSI_RESET = "\u001B[0m";

    private final int contextChars;
    private final int maxSnippets;

    public SnippetGenerator() {
        this(Constants.SNIPPET_CONTEXT_CHARS, Constants.MAX_SNIPPETS);
    }

    public SnippetGenerator(int contextChars, int maxSnippets) {
        this.contextChars = Math.max(0, contextChars);
        this.maxSnippets = Math.max(1, maxSnippets);
    }

    public List<Snippet> generate(String content, Set<String> queryTerms, List<int[]> hitOffsets) {
        if (content == null || content.isEmpty()) {
            return List.of();
        }

        List<HighlightSpan> allHits = collectHits(content, queryTerms, hitOffsets);
        if (allHits.isEmpty()) {
            return List.of();
        }

        List<Window> windows = buildMergedWindows(content, allHits);
        windows.sort(Comparator.comparingInt((Window window) -> -window.hitCount).thenComparingInt(window -> window.start));

        List<Snippet> snippets = new ArrayList<>();
        int limit = Math.min(maxSnippets, windows.size());
        for (int index = 0; index < limit; index++) {
            Window window = windows.get(index);
            String snippetText = content.substring(window.start, window.end);
            List<HighlightSpan> relativeHits = toRelativeHighlights(window.start, window.end, allHits);
            String highlightedText = applyHighlight(snippetText, relativeHits);
            int anchorOffset = relativeHits.isEmpty()
                ? window.start
                : window.start + relativeHits.getFirst().start();
            snippets.add(new Snippet(highlightedText, countLineNumber(content, anchorOffset), window.start, relativeHits));
        }
        return snippets;
    }

    private List<HighlightSpan> collectHits(String content, Set<String> queryTerms, List<int[]> hitOffsets) {
        List<HighlightSpan> spans = new ArrayList<>();
        if (hitOffsets != null) {
            for (int[] hitOffset : hitOffsets) {
                if (hitOffset == null || hitOffset.length < 2) {
                    continue;
                }
                int start = Math.max(0, hitOffset[0]);
                int end = Math.min(content.length(), hitOffset[1]);
                if (start < end) {
                    spans.add(new HighlightSpan(start, end));
                }
            }
        }

        if (queryTerms != null && !queryTerms.isEmpty()) {
            String lowerContent = content.toLowerCase(Locale.ROOT);
            Set<String> uniqueTerms = new HashSet<>();
            for (String queryTerm : queryTerms) {
                if (queryTerm != null && !queryTerm.isBlank()) {
                    uniqueTerms.add(queryTerm.toLowerCase(Locale.ROOT));
                }
            }
            for (String term : uniqueTerms) {
                int fromIndex = 0;
                while (fromIndex < lowerContent.length()) {
                    int foundIndex = lowerContent.indexOf(term, fromIndex);
                    if (foundIndex < 0) {
                        break;
                    }
                    spans.add(new HighlightSpan(foundIndex, foundIndex + term.length()));
                    fromIndex = foundIndex + term.length();
                }
            }
        }
        return mergeOverlappingSpans(spans);
    }

    private List<Window> buildMergedWindows(String content, List<HighlightSpan> spans) {
        List<Window> windows = new ArrayList<>();
        for (HighlightSpan span : spans) {
            int rawStart = Math.max(0, span.start() - contextChars);
            int rawEnd = Math.min(content.length(), span.end() + contextChars);
            int alignedStart = alignStart(content, rawStart);
            int alignedEnd = alignEnd(content, rawEnd);
            windows.add(new Window(alignedStart, alignedEnd, 1));
        }

        windows.sort(Comparator.comparingInt(window -> window.start));
        List<Window> merged = new ArrayList<>();
        for (Window window : windows) {
            if (merged.isEmpty()) {
                merged.add(window);
                continue;
            }
            Window previous = merged.getLast();
            if (window.start <= previous.end) {
                merged.set(merged.size() - 1, new Window(previous.start, Math.max(previous.end, window.end), previous.hitCount + 1));
            } else {
                merged.add(window);
            }
        }
        return merged;
    }

    private List<HighlightSpan> toRelativeHighlights(int windowStart, int windowEnd, List<HighlightSpan> allHits) {
        List<HighlightSpan> relative = new ArrayList<>();
        for (HighlightSpan span : allHits) {
            if (span.end() <= windowStart || span.start() >= windowEnd) {
                continue;
            }
            int start = Math.max(span.start(), windowStart) - windowStart;
            int end = Math.min(span.end(), windowEnd) - windowStart;
            if (start < end) {
                relative.add(new HighlightSpan(start, end));
            }
        }
        return mergeOverlappingSpans(relative);
    }

    private int alignStart(String text, int index) {
        int aligned = index;
        while (aligned > 0 && isWordChar(text.charAt(aligned - 1))) {
            aligned--;
        }
        return aligned;
    }

    private int alignEnd(String text, int index) {
        int aligned = index;
        while (aligned < text.length() && isWordChar(text.charAt(aligned))) {
            aligned++;
        }
        return aligned;
    }

    private boolean isWordChar(char value) {
        return Character.isLetterOrDigit(value) || value == '_';
    }

    private int countLineNumber(String content, int offset) {
        int lineNumber = 1;
        for (int index = 0; index < offset && index < content.length(); index++) {
            if (content.charAt(index) == '\n') {
                lineNumber++;
            }
        }
        return lineNumber;
    }

    private List<HighlightSpan> mergeOverlappingSpans(List<HighlightSpan> spans) {
        if (spans.isEmpty()) {
            return List.of();
        }

        List<HighlightSpan> sorted = new ArrayList<>(spans);
        sorted.sort(Comparator.comparingInt(HighlightSpan::start));

        List<HighlightSpan> merged = new ArrayList<>();
        HighlightSpan current = sorted.getFirst();
        for (int index = 1; index < sorted.size(); index++) {
            HighlightSpan next = sorted.get(index);
            if (next.start() <= current.end()) {
                current = new HighlightSpan(current.start(), Math.max(current.end(), next.end()));
            } else {
                merged.add(current);
                current = next;
            }
        }
        merged.add(current);
        return merged;
    }

    private String applyHighlight(String text, List<HighlightSpan> spans) {
        if (spans.isEmpty()) {
            return text;
        }

        StringBuilder builder = new StringBuilder();
        int cursor = 0;
        for (HighlightSpan span : spans) {
            if (span.start() > cursor) {
                builder.append(text, cursor, span.start());
            }
            builder.append(ANSI_HIGHLIGHT);
            builder.append(text, span.start(), span.end());
            builder.append(ANSI_RESET);
            cursor = span.end();
        }
        if (cursor < text.length()) {
            builder.append(text, cursor, text.length());
        }
        return builder.toString();
    }

    private record Window(int start, int end, int hitCount) {
    }
}
