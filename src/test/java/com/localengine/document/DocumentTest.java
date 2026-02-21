package com.localengine.document;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

class DocumentTest {

    @TempDir
    Path tempDir;

    @Test
    void testOfFileInfersCodeType() throws IOException {
        Path javaFile = tempDir.resolve("Main.java");
        Files.writeString(javaFile, "class Main {}");

        Document document = Document.ofFile(1, javaFile, List.of());

        assertEquals(1, document.docId());
        assertEquals("java", document.extension());
        assertEquals(DocType.CODE, document.docType());
        assertTrue(document.sizeBytes() > 0);
    }

    @Test
    void testOfFileInfersNoteTypeByNotePath() throws IOException {
        Path noteFile = tempDir.resolve("note.md");
        Files.writeString(noteFile, "# note");

        Document document = Document.ofFile(2, noteFile, List.of(noteFile));

        assertEquals(DocType.NOTE, document.docType());
    }

    @Test
    void testOfFileInfersOtherTypeForUnknownExtension() throws IOException {
        Path unknown = tempDir.resolve("artifact.unknownext");
        Files.writeString(unknown, "payload");

        Document document = Document.ofFile(3, unknown, List.of());

        assertEquals(DocType.OTHER, document.docType());
    }

    @Test
    void testWithTokenCount() throws IOException {
        Path file = tempDir.resolve("doc.txt");
        Files.writeString(file, "hello world");

        Document original = Document.ofFile(4, file, List.of());
        Document updated = original.withTokenCount(99);

        assertEquals(0, original.tokenCount());
        assertEquals(99, updated.tokenCount());
        assertEquals(original.docId(), updated.docId());
    }
}
