package com.localengine.text;

import java.util.ArrayList;
import java.util.List;

public class BigramTokenizer implements Tokenizer {

    /**
     * 仅对CJK连续片段执行双字切分，单字符片段直接输出。
     */
    @Override
    public List<Token> tokenize(String text) {
        if (text == null || text.isEmpty()) {
            return List.of();
        }

        List<Token> tokens = new ArrayList<>();
        int nextPosition = 0;
        int cursor = 0;

        while (cursor < text.length()) {
            char currentChar = text.charAt(cursor);
            if (!isCjk(currentChar)) {
                cursor++;
                continue;
            }

            int segmentStart = cursor;
            int segmentEnd = cursor + 1;
            while (segmentEnd < text.length() && isCjk(text.charAt(segmentEnd))) {
                segmentEnd++;
            }

            int segmentLength = segmentEnd - segmentStart;
            if (segmentLength == 1) {
                String singleCharTerm = text.substring(segmentStart, segmentEnd);
                tokens.add(new Token(singleCharTerm, nextPosition, segmentStart, segmentEnd));
                nextPosition++;
            } else {
                for (int index = segmentStart; index < segmentEnd - 1; index++) {
                    String bigramTerm = text.substring(index, index + 2);
                    tokens.add(new Token(bigramTerm, nextPosition, index, index + 2));
                    nextPosition++;
                }
            }

            cursor = segmentEnd;
        }

        return List.copyOf(tokens);
    }

    /**
     * 判断字符是否属于CJK脚本。
     */
    private boolean isCjk(char ch) {
        Character.UnicodeScript script = Character.UnicodeScript.of(ch);
        return script == Character.UnicodeScript.HAN
            || script == Character.UnicodeScript.HIRAGANA
            || script == Character.UnicodeScript.KATAKANA
            || script == Character.UnicodeScript.HANGUL;
    }
}
