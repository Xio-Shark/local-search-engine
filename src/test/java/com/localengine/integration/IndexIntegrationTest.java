package com.localengine.integration;

import com.localengine.document.DocumentTable;
import com.localengine.index.IndexManager;
import com.localengine.query.QueryEngine;
import com.localengine.query.SearchHit;
import com.localengine.query.SearchResult;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

/**
 * 索引集成测试
 * 
 * 覆盖完整索引流程：建索引 → 搜索 → snippet验证 → 字段过滤 → 增量更新
 */
class IndexIntegrationTest {

    @TempDir
    Path tempDir;
    
    private Path indexDir;
    private Path sourceDir;
    private IndexManager indexManager;
    private DocumentTable docTable;
    private QueryEngine queryEngine;

    @BeforeEach
    void setUp() throws IOException {
        indexDir = tempDir.resolve("index");
        sourceDir = tempDir.resolve("source");
        Files.createDirectories(sourceDir);
        
        indexManager = new IndexManager(indexDir, 2);
        docTable = new DocumentTable(indexDir.resolve("documents.db"));
        queryEngine = new QueryEngine(indexManager, docTable);
    }

    @AfterEach
    void tearDown() throws IOException {
        if (queryEngine != null) {
            // QueryEngine没有close方法，依赖IndexManager和DocumentTable
        }
        if (docTable != null) {
            docTable.close();
        }
        if (indexManager != null) {
            indexManager.close();
        }
    }

    @Test
    void testFullIndexAndSearch() throws IOException {
        // 创建测试文件
        createTestFile("doc1.md", "This is a test document about Java programming.");
        createTestFile("doc2.md", "Python is a great language for data science.");
        createTestFile("doc3.txt", "Java and Python are both popular programming languages.");
        
        // 构建索引
        indexManager.buildIndex(List.of(sourceDir));
        
        // 验证索引状态
        assertEquals(3, indexManager.getStatus().docCount());
        
        // 搜索测试
        SearchResult result = queryEngine.search("Java", 10);
        assertTrue(result.totalMatches() >= 2, "应该至少匹配2个包含Java的文档");
        
        // 验证snippet包含查询词
        for (SearchHit hit : result.hits()) {
            boolean hasSnippetWithTerm = hit.snippets().stream()
                .anyMatch(s -> s.text().toLowerCase().contains("java"));
            assertTrue(hasSnippetWithTerm, "Snippet应该包含查询词Java");
        }
    }

    @Test
    void testPhraseQuery() throws IOException {
        createTestFile("doc1.md", "The quick brown fox jumps over the lazy dog.");
        createTestFile("doc2.md", "A quick brown dog runs fast.");
        
        indexManager.buildIndex(List.of(sourceDir));
        
        // 短语查询
        SearchResult result = queryEngine.search("\"quick brown\"", 10);
        assertTrue(result.totalMatches() >= 1, "应该匹配包含quick brown短语的文档");
    }

    @Test
    void testFieldFilter() throws IOException {
        createTestFile("readme.md", "This is the readme file.");
        createTestFile("code.java", "public class Test { }");
        createTestFile("data.txt", "Some text data here.");
        
        indexManager.buildIndex(List.of(sourceDir));
        
        // 按扩展名过滤
        SearchResult result = queryEngine.search("ext:md", 10);
        assertEquals(1, result.totalMatches(), "应该只匹配1个md文件");
        assertTrue(result.hits().get(0).document().path().toString().endsWith(".md"));
    }

    @Test
    void testIncrementalUpdate() throws IOException {
        // 初始索引
        createTestFile("doc1.md", "Original content");
        indexManager.buildIndex(List.of(sourceDir));
        assertEquals(1, indexManager.getStatus().docCount());
        
        // 新增文件
        createTestFile("doc2.md", "New document added");
        
        // 修改现有文件
        Files.writeString(sourceDir.resolve("doc1.md"), "Updated content here");
        
        // 执行增量更新
        indexManager.incrementalUpdate(List.of(sourceDir));
        
        // 验证状态
        assertEquals(2, indexManager.getStatus().docCount(), "应该有2个文档");
        
        // 验证新文件可搜索
        SearchResult result = queryEngine.search("Updated", 10);
        assertEquals(1, result.totalMatches(), "应该能搜到更新的文档");
    }

    @Test
    void testIncrementalDelete() throws IOException {
        // 创建两个文件并索引
        createTestFile("keep.md", "Keep this file");
        createTestFile("delete.md", "Delete this file");
        indexManager.buildIndex(List.of(sourceDir));
        assertEquals(2, indexManager.getStatus().docCount());
        
        // 删除一个文件
        Files.delete(sourceDir.resolve("delete.md"));
        
        // 执行增量更新
        indexManager.incrementalUpdate(List.of(sourceDir));
        
        // 验证只剩一个文档
        assertEquals(1, indexManager.getStatus().docCount());
        
        // 验证被删除的文件搜不到
        SearchResult result = queryEngine.search("Delete", 10);
        assertEquals(0, result.totalMatches(), "已删除的文件不应被搜索到");
    }

    @Test
    void testCrashRecovery() throws IOException {
        // 创建测试文件
        createTestFile("doc1.md", "Test document for crash recovery");
        
        // 构建索引（WAL会被写入）
        indexManager.buildIndex(List.of(sourceDir));
        
        // 模拟崩溃：直接关闭，不checkpoint（实际上buildIndex会调用checkpoint）
        indexManager.close();
        
        // 重新打开IndexManager，应该能从WAL恢复
        IndexManager newManager = new IndexManager(indexDir, 2);
        DocumentTable newDocTable = new DocumentTable(indexDir.resolve("documents.db"));
        QueryEngine newQueryEngine = new QueryEngine(newManager, newDocTable);
        
        try {
            // 验证索引数据可恢复
            SearchResult result = newQueryEngine.search("crash recovery", 10);
            assertTrue(result.totalMatches() >= 1, "崩溃恢复后应该能搜到文档");
        } finally {
            newDocTable.close();
            newManager.close();
        }
    }

    @Test
    void testBooleanQuery() throws IOException {
        createTestFile("doc1.md", "Java programming guide");
        createTestFile("doc2.md", "Python programming guide");
        createTestFile("doc3.md", "Java and Python comparison");
        
        indexManager.buildIndex(List.of(sourceDir));
        
        // AND查询
        SearchResult result = queryEngine.search("Java AND programming", 10);
        assertEquals(1, result.totalMatches(), "AND查询应该只匹配同时包含Java和programming的文档");
    }

    @Test
    void testPrefixQuery() throws IOException {
        createTestFile("doc1.md", "Configuration file settings");
        createTestFile("doc2.md", "Configure your application");
        createTestFile("doc3.md", "Different topic");
        
        indexManager.buildIndex(List.of(sourceDir));
        
        // 前缀查询
        SearchResult result = queryEngine.search("config*", 10);
        assertTrue(result.totalMatches() >= 2, "前缀查询应该匹配至少2个文档");
    }

    /**
     * 崩溃恢复增强验证：多文件场景下重启后索引数据完整可搜。
     */
    @Test
    void testCrashRecoveryMultiFile() throws IOException {
        // 创建多类型测试文件
        createTestFile("readme.md", "# Project Readme\nThis is a readme file for the project.");
        createTestFile("Main.java", "public class Main { public static void main(String[] args) {} }");
        createTestFile("notes.txt", "Meeting notes: discuss crash recovery strategy.");

        // 构建索引并立即关闭（模拟崩溃）
        indexManager.buildIndex(List.of(sourceDir));
        int docCountBeforeCrash = indexManager.getStatus().docCount();
        indexManager.close();
        docTable.close();

        // 完全重新打开——验证从持久化段恢复
        IndexManager recoveredManager = new IndexManager(indexDir, 2);
        DocumentTable recoveredDocTable = new DocumentTable(indexDir.resolve("documents.db"));
        QueryEngine recoveredEngine = new QueryEngine(recoveredManager, recoveredDocTable);

        try {
            assertEquals(docCountBeforeCrash, recoveredManager.getStatus().docCount(),
                "恢复后文档数应与崩溃前一致");

            SearchResult mdResult = recoveredEngine.search("readme", 10);
            assertTrue(mdResult.totalMatches() >= 1, "恢复后应能搜到 md 文件");

            SearchResult javaResult = recoveredEngine.search("Main", 10);
            assertTrue(javaResult.totalMatches() >= 1, "恢复后应能搜到 java 文件");

            SearchResult txtResult = recoveredEngine.search("crash recovery", 10);
            assertTrue(txtResult.totalMatches() >= 1, "恢复后应能搜到 txt 文件");
        } finally {
            recoveredDocTable.close();
            recoveredManager.close();
        }

        // 防止 tearDown 重复关闭
        indexManager = null;
        docTable = null;
    }

    /**
     * 多批索引后的查询一致性验证。
     * 模拟分批写入→产生多段→搜索结果应包含全部文档。
     */
    @Test
    void testMultiBatchQueryConsistency() throws IOException {
        // 第一批文件
        createTestFile("batch1_a.md", "Algorithm analysis of sorting");
        createTestFile("batch1_b.md", "Algorithm analysis of searching");
        indexManager.buildIndex(List.of(sourceDir));

        SearchResult beforeSecondBatch = queryEngine.search("Algorithm", 10);
        int matchesBefore = beforeSecondBatch.totalMatches();
        assertTrue(matchesBefore >= 2, "第一批应至少匹配2个文档");

        // 第二批新增文件——作为增量更新产生新段
        createTestFile("batch2_a.md", "Algorithm design patterns overview");
        indexManager.incrementalUpdate(List.of(sourceDir));

        SearchResult afterSecondBatch = queryEngine.search("Algorithm", 10);
        assertTrue(afterSecondBatch.totalMatches() >= matchesBefore + 1,
            "增量更新后应包含新旧全部匹配文档");
    }

    private void createTestFile(String filename, String content) throws IOException {
        Path file = sourceDir.resolve(filename);
        Files.writeString(file, content);
    }
}
