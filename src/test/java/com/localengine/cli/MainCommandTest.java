package com.localengine.cli;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.localengine.document.DocType;
import com.localengine.document.Document;
import com.localengine.highlight.Snippet;
import com.localengine.query.SearchHit;
import com.localengine.query.SearchResult;
import java.io.ByteArrayOutputStream;
import java.io.PrintStream;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.List;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.api.Test;
import picocli.CommandLine;
import picocli.CommandLine.ParseResult;

class MainCommandTest {

    @TempDir
    Path tempDir;

    @Test
    void testCallWithoutGuiMode() {
        MainCommand command = new MainCommand();
        assertEquals(0, command.call());
    }

    @Test
    void testHelpOptionReturnsZero() {
        int exitCode = new CommandLine(new MainCommand()).execute("--help");
        assertEquals(0, exitCode);
    }

    @Test
    void testParseGlobalOptionsAndSubcommand() {
        CommandLine commandLine = new CommandLine(new MainCommand());
        ParseResult parseResult = commandLine.parseArgs("--threads", "6", "status");

        assertNotNull(parseResult.subcommand());
        assertEquals("status", parseResult.subcommand().commandSpec().name());
    }

    @Test
    void testRebuildSubcommandWithoutConfirmReturnsOne() {
        MainCommand.RebuildSubcommand rebuildSubcommand = new MainCommand.RebuildSubcommand();
        assertEquals(1, rebuildSubcommand.call());
    }

    @Test
    void testStatusSubcommandFormatBytesBranches() throws Exception {
        MainCommand.StatusSubcommand statusSubcommand = new MainCommand.StatusSubcommand();
        Method formatBytesMethod = MainCommand.StatusSubcommand.class.getDeclaredMethod("formatBytes", long.class);
        formatBytesMethod.setAccessible(true);

        assertEquals("512 B", formatBytesMethod.invoke(statusSubcommand, 512L));
        assertEquals("2.00 KB", formatBytesMethod.invoke(statusSubcommand, 2048L));
        assertEquals("3.00 MB", formatBytesMethod.invoke(statusSubcommand, 3L * 1024 * 1024));
        assertEquals("4.00 GB", formatBytesMethod.invoke(statusSubcommand, 4L * 1024 * 1024 * 1024));
    }

    @Test
    void testSearchSubcommandPrintTextResultWhenNoHits() throws Exception {
        MainCommand.SearchSubcommand searchSubcommand = new MainCommand.SearchSubcommand();
        SearchResult emptyResult = new SearchResult(List.of(), 0, 2L, "none");
        Method printTextResultMethod = MainCommand.SearchSubcommand.class.getDeclaredMethod("printTextResult", SearchResult.class);
        printTextResultMethod.setAccessible(true);

        ByteArrayOutputStream outputBuffer = new ByteArrayOutputStream();
        PrintStream originalOut = System.out;
        try {
            System.setOut(new PrintStream(outputBuffer));
            printTextResultMethod.invoke(searchSubcommand, emptyResult);
        } finally {
            System.setOut(originalOut);
        }

        String outputText = outputBuffer.toString();
        assertTrue(outputText.contains("未找到匹配结果"));
    }

    @Test
    void testSearchSubcommandPrintJsonResult() throws Exception {
        MainCommand.SearchSubcommand searchSubcommand = new MainCommand.SearchSubcommand();
        Document document = new Document(1, Path.of("demo.txt"), "txt", 32L, Instant.now(), DocType.DOC, 12);
        SearchHit hit = new SearchHit(document, 1.5, List.of(new Snippet("demo snippet", 1, 0, List.of())));
        SearchResult searchResult = new SearchResult(List.of(hit), 1, 5L, "demo");

        Method printJsonResultMethod = MainCommand.SearchSubcommand.class.getDeclaredMethod("printJsonResult", SearchResult.class);
        printJsonResultMethod.setAccessible(true);

        ByteArrayOutputStream outputBuffer = new ByteArrayOutputStream();
        PrintStream originalOut = System.out;
        try {
            System.setOut(new PrintStream(outputBuffer));
            printJsonResultMethod.invoke(searchSubcommand, searchResult);
        } finally {
            System.setOut(originalOut);
        }

        String outputText = outputBuffer.toString();
        assertTrue(outputText.contains("\"totalMatches\""));
        assertTrue(outputText.contains("\"query\""));
    }

    @Test
    void testSubcommandsHappyPath() throws Exception {
        Path indexDir = tempDir.resolve("index");
        Path sourceDir = tempDir.resolve("source");
        Files.createDirectories(sourceDir);
        Files.writeString(sourceDir.resolve("doc1.md"), "hello java world");

        MainCommand mainCommand = new MainCommand();
        setField(mainCommand, "indexDir", indexDir);
        setField(mainCommand, "threads", 2);

        MainCommand.IndexSubcommand indexSubcommand = new MainCommand.IndexSubcommand();
        setField(indexSubcommand, "main", mainCommand);
        setField(indexSubcommand, "sourcePaths", List.of(sourceDir));
        assertEquals(0, indexSubcommand.call());

        MainCommand.StatusSubcommand statusSubcommand = new MainCommand.StatusSubcommand();
        setField(statusSubcommand, "main", mainCommand);
        assertEquals(0, statusSubcommand.call());

        MainCommand.SearchSubcommand searchSubcommand = new MainCommand.SearchSubcommand();
        setField(searchSubcommand, "main", mainCommand);
        setField(searchSubcommand, "query", "hello");
        setField(searchSubcommand, "limit", 5);
        setField(searchSubcommand, "format", "text");
        assertEquals(0, searchSubcommand.call());

        setField(searchSubcommand, "format", "json");
        assertEquals(0, searchSubcommand.call());

        MainCommand.RebuildSubcommand rebuildSubcommand = new MainCommand.RebuildSubcommand();
        setField(rebuildSubcommand, "main", mainCommand);
        setField(rebuildSubcommand, "confirmed", true);
        setField(rebuildSubcommand, "sourcePaths", List.of(sourceDir));
        assertEquals(0, rebuildSubcommand.call());
    }

    private static void setField(Object target, String fieldName, Object value) throws Exception {
        Field field = target.getClass().getDeclaredField(fieldName);
        field.setAccessible(true);
        field.set(target, value);
    }
}
