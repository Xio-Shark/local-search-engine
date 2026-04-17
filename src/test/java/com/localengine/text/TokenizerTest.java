package com.localengine.text;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class TokenizerTest {

    @Test
    @DisplayName("EnglishTokenizer: 简单英文分词")
    void testEnglishTokenizerSimple() {
        EnglishTokenizer tokenizer = new EnglishTokenizer(false);

        List<Token> tokens = tokenizer.tokenize("Hello world");

        assertEquals(2, tokens.size());
        assertToken(tokens.get(0), "hello", 0, 0, 5);
        assertToken(tokens.get(1), "world", 1, 6, 11);
    }

    @Test
    @DisplayName("EnglishTokenizer: 停用词过滤")
    void testEnglishTokenizerWithStopWords() {
        EnglishTokenizer tokenizer = new EnglishTokenizer(true);

        List<Token> tokens = tokenizer.tokenize("The quick brown fox");

        assertEquals(3, tokens.size());
        assertToken(tokens.get(0), "quick", 0, 4, 9);
        assertToken(tokens.get(1), "brown", 1, 10, 15);
        assertToken(tokens.get(2), "fox", 2, 16, 19);
    }

    @Test
    @DisplayName("EnglishTokenizer: 位置与偏移正确")
    void testEnglishTokenizerOffsets() {
        EnglishTokenizer tokenizer = new EnglishTokenizer(false);

        List<Token> tokens = tokenizer.tokenize("A-1 bb, Ccc!");

        assertEquals(2, tokens.size());
        assertToken(tokens.get(0), "bb", 0, 4, 6);
        assertToken(tokens.get(1), "ccc", 1, 8, 11);
    }

    @Test
    @DisplayName("BigramTokenizer: 纯中文分词")
    void testBigramTokenizerChinese() {
        BigramTokenizer tokenizer = new BigramTokenizer();

        List<Token> tokens = tokenizer.tokenize("搜索引擎");

        assertEquals(3, tokens.size());
        assertToken(tokens.get(0), "搜索", 0, 0, 2);
        assertToken(tokens.get(1), "索引", 1, 1, 3);
        assertToken(tokens.get(2), "引擎", 2, 2, 4);
    }

    @Test
    @DisplayName("BigramTokenizer: 纯日文分词")
    void testBigramTokenizerJapanese() {
        BigramTokenizer tokenizer = new BigramTokenizer();

        List<Token> tokens = tokenizer.tokenize("こんにちは");

        assertEquals(4, tokens.size());
        assertToken(tokens.get(0), "こん", 0, 0, 2);
        assertToken(tokens.get(1), "んに", 1, 1, 3);
        assertToken(tokens.get(2), "にち", 2, 2, 4);
        assertToken(tokens.get(3), "ちは", 3, 3, 5);
    }

    @Test
    @DisplayName("BigramTokenizer: 混合文本只处理CJK")
    void testBigramTokenizerMixedText() {
        BigramTokenizer tokenizer = new BigramTokenizer();

        List<Token> tokens = tokenizer.tokenize("A中B文C");

        assertEquals(2, tokens.size());
        assertToken(tokens.get(0), "中", 0, 1, 2);
        assertToken(tokens.get(1), "文", 1, 3, 4);
    }

    @Test
    @DisplayName("CompositeTokenizer: 中英混合分词")
    void testCompositeTokenizerMixedLanguage() {
        CompositeTokenizer tokenizer = new CompositeTokenizer(false);

        List<Token> tokens = tokenizer.tokenize("Hello 世界");

        assertEquals(2, tokens.size());
        assertToken(tokens.get(0), "hello", 0, 0, 5);
        assertToken(tokens.get(1), "世界", 1, 6, 8);
    }

    @Test
    @DisplayName("CompositeTokenizer: 全局位置连续")
    void testCompositeTokenizerGlobalPosition() {
        CompositeTokenizer tokenizer = new CompositeTokenizer(false);

        List<Token> tokens = tokenizer.tokenize("Go 搜索 engine 引擎");

        assertEquals(4, tokens.size());
        assertToken(tokens.get(0), "go", 0, 0, 2);
        assertToken(tokens.get(1), "搜索", 1, 3, 5);
        assertToken(tokens.get(2), "engine", 2, 6, 12);
        assertToken(tokens.get(3), "引擎", 3, 13, 15);
    }

    @Test
    @DisplayName("CompositeTokenizer: 偏移正确")
    void testCompositeTokenizerOffsets() {
        CompositeTokenizer tokenizer = new CompositeTokenizer(true);

        List<Token> tokens = tokenizer.tokenize("The, A! 搜索-Engine");

        assertEquals(2, tokens.size());
        assertToken(tokens.get(0), "搜索", 0, 8, 10);
        assertToken(tokens.get(1), "engine", 1, 11, 17);
    }

    @Test
    @DisplayName("CompositeTokenizer: 边界情况")
    void testCompositeTokenizerEdgeCases() {
        CompositeTokenizer tokenizer = new CompositeTokenizer(true);

        assertTrue(tokenizer.tokenize(null).isEmpty());
        assertTrue(tokenizer.tokenize("").isEmpty());
        assertTrue(tokenizer.tokenize("...,,,!!!").isEmpty());

        List<Token> tokens = tokenizer.tokenize("123, 中文, 45");
        assertEquals(3, tokens.size());
        assertToken(tokens.get(0), "123", 0, 0, 3);
        assertToken(tokens.get(1), "中文", 1, 5, 7);
        assertToken(tokens.get(2), "45", 2, 9, 11);
    }

    private void assertToken(Token token, String term, int position, int startOffset, int endOffset) {
        assertEquals(term, token.term());
        assertEquals(position, token.position());
        assertEquals(startOffset, token.startOffset());
        assertEquals(endOffset, token.endOffset());
    }
}
