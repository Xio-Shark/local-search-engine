package com.localengine.text;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class EnglishTokenizer implements Tokenizer {

    private static final Pattern SPLIT_PATTERN = Pattern.compile("[^a-zA-Z0-9]+");

    private final boolean enableStopWords;

    /**
     * 创建英文分词器。
     */
    public EnglishTokenizer(boolean enableStopWords) {
        this.enableStopWords = enableStopWords;
    }

    /**
     * 对英文与数字文本分词，并输出原文偏移。
     */
    @Override
    public List<Token> tokenize(String text) {
        if (text == null || text.isEmpty()) {
            return List.of();
        }

        List<Token> tokens = new ArrayList<>();
        Matcher delimiterMatcher = SPLIT_PATTERN.matcher(text);
        int nextPosition = 0;
        int segmentStart = 0;

        while (delimiterMatcher.find()) {
            nextPosition = appendTokenIfValid(text, segmentStart, delimiterMatcher.start(), nextPosition, tokens);
            segmentStart = delimiterMatcher.end();
        }
        appendTokenIfValid(text, segmentStart, text.length(), nextPosition, tokens);

        return List.copyOf(tokens);
    }

    /**
     * 校验并追加有效词项，返回更新后的下一个位置序号。
     */
    private int appendTokenIfValid(String sourceText, int startOffset, int endOffset, int position, List<Token> tokens) {
        if (startOffset >= endOffset) {
            return position;
        }

        String normalizedTerm = sourceText.substring(startOffset, endOffset).toLowerCase(Locale.ROOT);
        if (normalizedTerm.length() <= 1) {
            return position;
        }
        if (enableStopWords && StopWords.isStopWord(normalizedTerm)) {
            return position;
        }

        tokens.add(new Token(normalizedTerm, position, startOffset, endOffset));
        return position + 1;
    }
}
