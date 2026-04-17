package com.localengine.gui;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.localengine.document.DocType;
import com.localengine.document.Document;
import com.localengine.highlight.HighlightSpan;
import com.localengine.highlight.Snippet;
import com.localengine.query.SearchHit;
import com.localengine.query.SearchResult;
import java.nio.file.Path;
import java.time.Instant;
import java.util.List;
import javax.swing.JTextPane;
import org.junit.jupiter.api.Test;

class DesktopAppTest {

    @Test
    void testToFileNameQueryEscapesQuoteAndBackslash() {
        String query = DesktopApp.toFileNameQuery("a\\b\"c.txt");
        assertEquals("filename:\"a\\\\b\\\"c.txt\"", query);
    }

    @Test
    void testParseSourcePaths() {
        List<Path> paths = DesktopApp.parseSourcePaths("docs\n./src/main");
        assertEquals(List.of(Path.of("docs"), Path.of("./src/main")), paths);
    }

    @Test
    void testParseSourcePathsRejectsEmptyInput() {
        IllegalArgumentException exception =
            assertThrows(IllegalArgumentException.class, () -> DesktopApp.parseSourcePaths("\n  \n"));
        assertTrue(exception.getMessage().contains("至少提供一个源路径"));
    }

    @Test
    void testParseIndexDir() {
        assertEquals(Path.of("./index"), DesktopApp.parseIndexDir(" ./index "));
    }

    @Test
    void testParseIndexDirRejectsEmpty() {
        IllegalArgumentException exception =
            assertThrows(IllegalArgumentException.class, () -> DesktopApp.parseIndexDir("   "));
        assertTrue(exception.getMessage().contains("索引目录不能为空"));
    }

    @Test
    void testStripAnsi() {
        assertEquals("", DesktopApp.stripAnsi(null));
        assertEquals("hello world", DesktopApp.stripAnsi("hello \u001B[1;33mworld\u001B[0m"));
    }

    @Test
    void testFormatBytesBranches() {
        assertEquals("999 B", DesktopApp.formatBytes(999));
        assertEquals("2.00 KB", DesktopApp.formatBytes(2048));
        assertEquals("3.00 MB", DesktopApp.formatBytes(3L * 1024 * 1024));
        assertEquals("5.00 GB", DesktopApp.formatBytes(5L * 1024 * 1024 * 1024));
    }

    @Test
    void testRenderSearchResultWithHits() {
        JTextPane resultPane = new JTextPane();
        Document document = new Document(1, Path.of("docs/demo.md"), "md", 64, Instant.now(), DocType.DOC, 8);
        Snippet snippet = new Snippet("hello world", 1, 0, List.of(new HighlightSpan(0, 5)));
        SearchHit hit = new SearchHit(document, 1.5, List.of(snippet));
        SearchResult searchResult = new SearchResult(List.of(hit), 1, 7, "hello");

        DesktopApp.renderSearchResult(resultPane, searchResult);

        String renderedText = resultPane.getText();
        assertTrue(renderedText.contains("demo.md"));
        assertTrue(renderedText.contains("总命中: 1"));
    }

    @Test
    void testRenderSearchResultWithEmptyHits() {
        JTextPane resultPane = new JTextPane();
        DesktopApp.renderSearchResult(resultPane, new SearchResult(List.of(), 0, 2, "none"));
        assertTrue(resultPane.getText().contains("未找到匹配结果"));
    }

}
