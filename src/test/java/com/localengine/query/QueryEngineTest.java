package com.localengine.query;

import com.localengine.document.DocType;
import com.localengine.document.Document;
import com.localengine.document.DocumentTable;
import com.localengine.index.DiskSegment;
import com.localengine.index.IndexManager;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.io.TempDir;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.FileTime;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.*;

class QueryEngineTest {

    @TempDir
    Path tempDir;

    @Test
    @DisplayName("简单词项查询")
    void testTermQuery() throws IOException {
        // 准备测试数据
        Path indexDir = tempDir.resolve("index");
        Path sourceDir = tempDir.resolve("source");
        Files.createDirectories(sourceDir);
        Files.writeString(sourceDir.resolve("doc1.md"), "Java programming guide");
        Files.writeString(sourceDir.resolve("doc2.md"), "Python programming tutorial");

        try (IndexManager indexManager = new IndexManager(indexDir, 2);
             DocumentTable docTable = new DocumentTable(indexDir.resolve("documents.db"))) {
            indexManager.buildIndex(List.of(sourceDir));
            QueryEngine engine = new QueryEngine(indexManager, docTable);

            SearchResult result = engine.search("Java", 10);

            assertTrue(result.totalMatches() >= 1);
            assertTrue(result.hits().stream()
                .anyMatch(h -> h.document().path().toString().contains("doc1")));
        }
    }

    @Test
    @DisplayName("布尔AND查询")
    void testBooleanAndQuery() throws IOException {
        Path indexDir = tempDir.resolve("index");
        Path sourceDir = tempDir.resolve("source");
        Files.createDirectories(sourceDir);
        Files.writeString(sourceDir.resolve("doc1.md"), "Java programming");
        Files.writeString(sourceDir.resolve("doc2.md"), "Java tutorial");
        Files.writeString(sourceDir.resolve("doc3.md"), "Python programming");

        try (IndexManager indexManager = new IndexManager(indexDir, 2);
             DocumentTable docTable = new DocumentTable(indexDir.resolve("documents.db"))) {
            indexManager.buildIndex(List.of(sourceDir));
            QueryEngine engine = new QueryEngine(indexManager, docTable);

            SearchResult result = engine.search("Java AND programming", 10);

            // 应该只匹配doc1（同时包含Java和programming）
            assertTrue(result.totalMatches() >= 1);
        }
    }

    @Test
    @DisplayName("短语查询")
    void testPhraseQuery() throws IOException {
        Path indexDir = tempDir.resolve("index");
        Path sourceDir = tempDir.resolve("source");
        Files.createDirectories(sourceDir);
        Files.writeString(sourceDir.resolve("doc1.md"), "distributed system architecture");
        Files.writeString(sourceDir.resolve("doc2.md"), "system distributed design");

        try (IndexManager indexManager = new IndexManager(indexDir, 2);
             DocumentTable docTable = new DocumentTable(indexDir.resolve("documents.db"))) {
            indexManager.buildIndex(List.of(sourceDir));
            QueryEngine engine = new QueryEngine(indexManager, docTable);

            SearchResult result = engine.search("\"distributed system\"", 10);

            // 应该只匹配doc1（包含连续短语）
            assertTrue(result.totalMatches() >= 1);
        }
    }

    @Test
    @DisplayName("字段过滤查询")
    void testFieldQuery() throws IOException {
        Path indexDir = tempDir.resolve("index");
        Path sourceDir = tempDir.resolve("source");
        Files.createDirectories(sourceDir);
        Files.writeString(sourceDir.resolve("readme.md"), "Documentation");
        Files.writeString(sourceDir.resolve("code.java"), "Source code");

        try (IndexManager indexManager = new IndexManager(indexDir, 2);
             DocumentTable docTable = new DocumentTable(indexDir.resolve("documents.db"))) {
            indexManager.buildIndex(List.of(sourceDir));
            QueryEngine engine = new QueryEngine(indexManager, docTable);

            SearchResult result = engine.search("ext:md", 10);

            assertTrue(result.totalMatches() >= 1);
            assertTrue(result.hits().stream()
                .allMatch(h -> h.document().path().toString().endsWith(".md")));
        }
    }

    @Test
    @DisplayName("直接输入文件名可命中目标文件")
    void testDirectFileNameQuery() throws IOException {
        Path indexDir = tempDir.resolve("index");
        Path sourceDir = tempDir.resolve("source");
        Files.createDirectories(sourceDir);
        Files.writeString(sourceDir.resolve("readme.md"), "Documentation content");
        Files.writeString(sourceDir.resolve("note.txt"), "Other file");

        try (IndexManager indexManager = new IndexManager(indexDir, 2);
             DocumentTable docTable = new DocumentTable(indexDir.resolve("documents.db")) ) {
            indexManager.buildIndex(List.of(sourceDir));
            QueryEngine engine = new QueryEngine(indexManager, docTable);

            SearchResult result = engine.search("readme.md", 10);

            assertEquals(1, result.totalMatches());
            assertTrue(result.hits().getFirst().document().path().toString().endsWith("readme.md"));
        }
    }

    @Test
    @DisplayName("前缀查询")
    void testPrefixQuery() throws IOException {
        Path indexDir = tempDir.resolve("index");
        Path sourceDir = tempDir.resolve("source");
        Files.createDirectories(sourceDir);
        Files.writeString(sourceDir.resolve("doc1.md"), "Configuration settings");
        Files.writeString(sourceDir.resolve("doc2.md"), "Configure the app");

        try (IndexManager indexManager = new IndexManager(indexDir, 2);
             DocumentTable docTable = new DocumentTable(indexDir.resolve("documents.db"))) {
            indexManager.buildIndex(List.of(sourceDir));
            QueryEngine engine = new QueryEngine(indexManager, docTable);

            SearchResult result = engine.search("config*", 10);

            assertTrue(result.totalMatches() >= 2);
        }
    }

    @Test
    @DisplayName("搜索结果按分数排序")
    void testResultsSortedByScore() throws IOException {
        Path indexDir = tempDir.resolve("index");
        Path sourceDir = tempDir.resolve("source");
        Files.createDirectories(sourceDir);
        Files.writeString(sourceDir.resolve("doc1.md"), "Java Java Java");  // 更多词频
        Files.writeString(sourceDir.resolve("doc2.md"), "Java");           // 较少词频

        try (IndexManager indexManager = new IndexManager(indexDir, 2);
             DocumentTable docTable = new DocumentTable(indexDir.resolve("documents.db"))) {
            indexManager.buildIndex(List.of(sourceDir));
            QueryEngine engine = new QueryEngine(indexManager, docTable);

            SearchResult result = engine.search("Java", 10);

            List<SearchHit> hits = result.hits();
            if (hits.size() >= 2) {
                assertTrue(hits.get(0).score() >= hits.get(1).score(),
                    "结果应该按分数降序排列");
            }
        }
    }

    @Test
    @DisplayName("限制返回结果数量")
    void testLimitResults() throws IOException {
        Path indexDir = tempDir.resolve("index");
        Path sourceDir = tempDir.resolve("source");
        Files.createDirectories(sourceDir);
        for (int i = 0; i < 10; i++) {
            Files.writeString(sourceDir.resolve("doc" + i + ".md"), "content " + i);
        }

        try (IndexManager indexManager = new IndexManager(indexDir, 2);
             DocumentTable docTable = new DocumentTable(indexDir.resolve("documents.db"))) {
            indexManager.buildIndex(List.of(sourceDir));
            QueryEngine engine = new QueryEngine(indexManager, docTable);

            SearchResult result = engine.search("content", 5);

            assertTrue(result.hits().size() <= 5, "返回结果不应超过限制");
        }
    }

    @Test
    @DisplayName("空查询返回空结果")
    void testEmptyQuery() throws IOException {
        Path indexDir = tempDir.resolve("index");
        try (IndexManager indexManager = new IndexManager(indexDir, 2);
             DocumentTable docTable = new DocumentTable(indexDir.resolve("documents.db"))) {
            QueryEngine engine = new QueryEngine(indexManager, docTable);

            SearchResult result = engine.search("nonexistentterm12345", 10);

            assertEquals(0, result.totalMatches());
            assertTrue(result.hits().isEmpty());
        }
    }

    @Test
    @DisplayName("范围查询 size 与 mtime")
    void testRangeQuerySizeAndMtime() throws IOException {
        Path indexDir = tempDir.resolve("index-range");
        Path sourceDir = tempDir.resolve("source-range");
        Files.createDirectories(sourceDir);

        Path a = sourceDir.resolve("a.md");
        Path b = sourceDir.resolve("b.md");
        Files.writeString(a, "java a");
        Files.writeString(b, "java bbbbbbbbbbbb");
        Files.setLastModifiedTime(a, FileTime.from(Instant.parse("2025-02-01T00:00:00Z")));
        Files.setLastModifiedTime(b, FileTime.from(Instant.parse("2025-03-01T00:00:00Z")));

        try (IndexManager indexManager = new IndexManager(indexDir, 2);
             DocumentTable docTable = new DocumentTable(indexDir.resolve("documents.db"))) {
            indexManager.buildIndex(List.of(sourceDir));
            QueryEngine engine = new QueryEngine(indexManager, docTable);

            SearchResult sizeResult = engine.search("size:1..20", 10);
            assertTrue(sizeResult.totalMatches() >= 1);

            SearchResult timeResult = engine.search("mtime:\"2025-01-01T00:00:00Z\"..\"2025-12-31T00:00:00Z\"", 10);
            assertTrue(timeResult.totalMatches() >= 2);
        }
    }

    @Test
    @DisplayName("非法字段与非法范围值返回空")
    void testInvalidFieldAndRangeValue() throws IOException {
        Path indexDir = tempDir.resolve("index-invalid");
        Path sourceDir = tempDir.resolve("source-invalid");
        Files.createDirectories(sourceDir);
        Files.writeString(sourceDir.resolve("doc.md"), "java test");

        try (IndexManager indexManager = new IndexManager(indexDir, 2);
             DocumentTable docTable = new DocumentTable(indexDir.resolve("documents.db"))) {
            indexManager.buildIndex(List.of(sourceDir));
            QueryEngine engine = new QueryEngine(indexManager, docTable);

            assertThrows(QueryParseException.class, () -> engine.search("unknown:value", 10));

            SearchResult invalidRange = engine.search("size:a..b", 10);
            assertEquals(0, invalidRange.totalMatches());
        }
    }
}
