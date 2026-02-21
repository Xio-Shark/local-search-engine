package com.localengine.text;

import java.util.ArrayList;
import java.util.List;

public class CompositeTokenizer implements Tokenizer {

    private final EnglishTokenizer englishTokenizer;
    private final BigramTokenizer bigramTokenizer;
    private final boolean enableStopWords;

    /**
     * 创建组合分词器。
     */
    public CompositeTokenizer(boolean enableStopWords) {
        this.enableStopWords = enableStopWords;
        this.englishTokenizer = new EnglishTokenizer(enableStopWords);
        this.bigramTokenizer = new BigramTokenizer();
    }

    /**
     * 对混合文本分词并维护全局位置与原文偏移。
     */
    @Override
    public List<Token> tokenize(String text) {
        if (text == null || text.isEmpty()) {
            return List.of();
        }

        List<Token> mergedTokens = new ArrayList<>();
        int globalPosition = 0;
        int cursor = 0;

        while (cursor < text.length()) {
            boolean currentSegmentIsCjk = isCjk(text.charAt(cursor));
            int segmentStart = cursor;
            int segmentEnd = cursor + 1;

            while (segmentEnd < text.length() && isCjk(text.charAt(segmentEnd)) == currentSegmentIsCjk) {
                segmentEnd++;
            }

            String segmentText = text.substring(segmentStart, segmentEnd);
            List<Token> segmentTokens = currentSegmentIsCjk
                ? bigramTokenizer.tokenize(segmentText)
                : englishTokenizer.tokenize(segmentText);

            for (Token segmentToken : segmentTokens) {
                int adjustedStart = segmentStart + segmentToken.startOffset();
                int adjustedEnd = segmentStart + segmentToken.endOffset();
                mergedTokens.add(new Token(segmentToken.term(), globalPosition, adjustedStart, adjustedEnd));
                globalPosition++;
            }

            cursor = segmentEnd;
        }

        return List.copyOf(mergedTokens);
    }

    /**
     * 判断字符是否为CJK字符。
     */
    private boolean isCjk(char ch) {
        Character.UnicodeScript script = Character.UnicodeScript.of(ch);
        return script == Character.UnicodeScript.HAN
            || script == Character.UnicodeScript.HIRAGANA
            || script == Character.UnicodeScript.KATAKANA
            || script == Character.UnicodeScript.HANGUL;
    }
}
