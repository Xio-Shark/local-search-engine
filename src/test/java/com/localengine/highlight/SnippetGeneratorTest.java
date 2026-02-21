package com.localengine.highlight;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.DisplayName;

import java.util.List;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Snippet生成器测试
 */
class SnippetGeneratorTest {

    @Test
    @DisplayName("基本snippet生成")
    void testBasicSnippetGeneration() {
        SnippetGenerator generator = new SnippetGenerator();
        String content = "This is a test document. It contains Java programming content. " +
                        "Java is a popular language. This document is for testing search.";
        
        List<Snippet> snippets = generator.generate(content, Set.of("java"), List.of());
        
        assertFalse(snippets.isEmpty(), "应该生成snippet");
        assertTrue(snippets.get(0).text().toLowerCase().contains("java"), 
            "Snippet应该包含查询词");
    }

    @Test
    @DisplayName("多个命中位置生成多个snippet")
    void testMultipleSnippets() {
        SnippetGenerator generator = new SnippetGenerator(10, 3);
        String content = "Java is great. " + "x".repeat(120) + "Java is also good. " + "y".repeat(120) + "Java again.";
        
        List<Snippet> snippets = generator.generate(content, Set.of("java"), List.of());
        
        assertTrue(snippets.size() > 1, "应该有多个snippet");
        assertTrue(snippets.size() <= 3, "不应该超过最大snippet数");
    }

    @Test
    @DisplayName("空内容返回空列表")
    void testEmptyContent() {
        SnippetGenerator generator = new SnippetGenerator();
        
        List<Snippet> snippets = generator.generate("", Set.of("test"), List.of());
        
        assertTrue(snippets.isEmpty(), "空内容应该返回空列表");
    }

    @Test
    @DisplayName("空查询词返回空列表")
    void testEmptyQueryTerms() {
        SnippetGenerator generator = new SnippetGenerator();
        String content = "This is some content.";
        
        List<Snippet> snippets = generator.generate(content, Set.of(), List.of());
        
        assertTrue(snippets.isEmpty(), "空查询词应该返回空列表");
    }

    @Test
    @DisplayName("未命中查询词返回空列表")
    void testNoMatch() {
        SnippetGenerator generator = new SnippetGenerator();
        String content = "This document is about Python programming.";
        
        List<Snippet> snippets = generator.generate(content, Set.of("java"), List.of());
        
        assertTrue(snippets.isEmpty(), "未命中应该返回空列表");
    }

    @Test
    @DisplayName("多个查询词命中")
    void testMultipleQueryTerms() {
        SnippetGenerator generator = new SnippetGenerator(100, 2);
        String content = "Java and Python are both popular programming languages. " +
                        "Many developers use Java for enterprise applications.";
        
        List<Snippet> snippets = generator.generate(content, Set.of("java", "python"), List.of());
        
        assertFalse(snippets.isEmpty(), "应该生成snippet");
        String snippetText = snippets.get(0).text().toLowerCase();
        assertTrue(snippetText.contains("java") || snippetText.contains("python"),
            "Snippet应该包含至少一个查询词");
    }

    @Test
    @DisplayName("Snippet包含高亮范围")
    void testHighlightSpans() {
        SnippetGenerator generator = new SnippetGenerator(80, 3);
        String content = "This is a long document about Java programming. " +
                        "Java is used everywhere. Let's talk more about Java.";
        
        List<Snippet> snippets = generator.generate(content, Set.of("java"), List.of());
        
        assertFalse(snippets.isEmpty(), "应该生成snippet");
        assertFalse(snippets.get(0).highlights().isEmpty(), "应该有高亮范围");
    }

    @Test
    @DisplayName("自定义上下文长度")
    void testCustomContextLength() {
        SnippetGenerator shortContext = new SnippetGenerator(20, 3);
        SnippetGenerator longContext = new SnippetGenerator(100, 3);
        
        String content = "Java is a programming language. " + "a ".repeat(50) + "Java is popular.";
        
        List<Snippet> shortSnippets = shortContext.generate(content, Set.of("java"), List.of());
        List<Snippet> longSnippets = longContext.generate(content, Set.of("java"), List.of());
        
        assertFalse(shortSnippets.isEmpty());
        assertFalse(longSnippets.isEmpty());
        
        // 短上下文的snippet应该比长上下文的短
        assertTrue(shortSnippets.get(0).text().length() < longSnippets.get(0).text().length(),
            "短上下文应该产生更短的snippet");
    }

    @Test
    @DisplayName("中文内容snippet生成")
    void testChineseContent() {
        SnippetGenerator generator = new SnippetGenerator();
        String content = "这是一个关于搜索引擎的文档。搜索引擎很重要。" +
                        "这是一个测试文档。";
        
        List<Snippet> snippets = generator.generate(content, Set.of("搜索"), List.of());
        
        assertFalse(snippets.isEmpty(), "中文内容应该生成snippet");
        assertTrue(snippets.get(0).text().contains("搜索"), 
            "中文snippet应该包含查询词");
    }

    @Test
    @DisplayName("行号计算正确")
    void testLineNumber() {
        SnippetGenerator generator = new SnippetGenerator();
        String content = "Line 1\nLine 2\nLine 3 with Java\nLine 4";
        
        List<Snippet> snippets = generator.generate(content, Set.of("java"), List.of());
        
        assertFalse(snippets.isEmpty());
        // "Line 3 with Java" 应该是第3行
        assertEquals(3, snippets.get(0).lineNumber(), 
            "行号应该正确计算");
    }
}
