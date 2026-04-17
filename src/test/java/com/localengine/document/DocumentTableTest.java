package com.localengine.document;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.nio.file.Path;
import java.time.Instant;
import java.util.List;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class DocumentTableTest {
    @TempDir
    Path tempDir;

    @Test
    void testCrudOperations() {
        Path dbPath = tempDir.resolve("crud.db");
        Instant baseTime = Instant.parse("2026-01-01T00:00:00Z");

        try (DocumentTable documentTable = new DocumentTable(dbPath)) {
            Document document = new Document(
                    1,
                    Path.of("/workspace/docs/readme.md"),
                    "md",
                    1024,
                    baseTime,
                    DocType.DOC,
                    120
            );
            documentTable.insert(document);

            Optional<Document> loadedByPath = documentTable.findByPath("/workspace/docs/readme.md");
            assertTrue(loadedByPath.isPresent());
            assertEquals(1, loadedByPath.get().docId());
            assertEquals("md", loadedByPath.get().extension());

            Optional<Document> loadedById = documentTable.findById(1);
            assertTrue(loadedById.isPresent());
            assertEquals(DocType.DOC, loadedById.get().docType());

            Instant updatedTime = baseTime.plusSeconds(3600);
            documentTable.update(1, 2048, updatedTime, 180);

            Document updatedDocument = documentTable.findById(1).orElseThrow();
            assertEquals(2048, updatedDocument.sizeBytes());
            assertEquals(updatedTime, updatedDocument.mtime());
            assertEquals(180, updatedDocument.tokenCount());

            Optional<Integer> deletedDocId = documentTable.deleteByPath("/workspace/docs/readme.md");
            assertTrue(deletedDocId.isPresent());
            assertEquals(1, deletedDocId.get());
            assertFalse(documentTable.findById(1).isPresent());
        }
    }

    @Test
    void testFilterMethods() {
        Path dbPath = tempDir.resolve("filters.db");
        Instant baseTime = Instant.parse("2026-02-01T00:00:00Z");

        try (DocumentTable documentTable = new DocumentTable(dbPath)) {
            documentTable.insert(new Document(1, Path.of("/repo/src/App.java"), "java", 100, baseTime, DocType.CODE, 10));
            documentTable.insert(new Document(2, Path.of("/repo/docs/guide.md"), "md", 200, baseTime.plusSeconds(60), DocType.DOC, 40));
            documentTable.insert(new Document(3, Path.of("/repo/data/table.csv"), "csv", 500, baseTime.plusSeconds(120), DocType.DATA, 5));
            documentTable.insert(new Document(4, Path.of("/repo/config/app.yaml"), "yaml", 80, baseTime.plusSeconds(180), DocType.CONFIG, 2));

            assertEquals(List.of(1), documentTable.findDocIdsByExtension("java"));
            assertEquals(List.of(2), documentTable.findDocIdsByType(DocType.DOC));
            assertEquals(List.of(2, 3), documentTable.findDocIdsByMtimeRange(baseTime.plusSeconds(60), baseTime.plusSeconds(120)));
            assertEquals(List.of(2, 3), documentTable.findDocIdsBySizeRange(150, 800));
            assertEquals(List.of(1, 2, 3, 4), documentTable.findDocIdsByPathPrefix("/repo/"));
            assertEquals(List.of(2), documentTable.findDocIdsByFileName("guide.md"));
            assertEquals(List.of(2), documentTable.findDocIdsByFileName("GUIDE.MD"));

            List<Document> changedDocuments = documentTable.findChangedSince(baseTime.plusSeconds(90));
            assertEquals(List.of(3, 4), changedDocuments.stream().map(Document::docId).toList());
        }
    }

    @Test
    void testPathUniqueConstraint() {
        Path dbPath = tempDir.resolve("unique.db");
        Instant baseTime = Instant.parse("2026-03-01T00:00:00Z");

        try (DocumentTable documentTable = new DocumentTable(dbPath)) {
            Document first = new Document(1, Path.of("/repo/docs/same-path.txt"), "txt", 10, baseTime, DocType.DOC, 1);
            Document duplicatedPath = new Document(2, Path.of("/repo/docs/same-path.txt"), "txt", 20, baseTime, DocType.DOC, 2);

            documentTable.insert(first);
            assertThrows(IllegalStateException.class, () -> documentTable.insert(duplicatedPath));
        }
    }

    @Test
    void testWalModeAndStatistics() {
        Path dbPath = tempDir.resolve("wal.db");
        Instant baseTime = Instant.parse("2026-04-01T00:00:00Z");

        try (DocumentTable documentTable = new DocumentTable(dbPath)) {
            documentTable.insert(new Document(1, Path.of("/repo/note/a.md"), "md", 100, baseTime, DocType.NOTE, 100));
            documentTable.insert(new Document(3, Path.of("/repo/note/b.md"), "md", 300, baseTime.plusSeconds(1), DocType.NOTE, 300));

            assertEquals("wal", documentTable.getJournalMode().toLowerCase());
            assertEquals(2, documentTable.getTotalDocCount());
            assertEquals(200.0, documentTable.getAverageDocLength());
            assertEquals(4, documentTable.nextDocId());
        }
    }
}
