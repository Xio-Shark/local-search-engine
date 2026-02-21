package com.localengine.config;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;

import java.nio.file.Path;
import org.junit.jupiter.api.Test;

class EngineConfigTest {

    @Test
    void testDefaults() {
        EngineConfig config = EngineConfig.defaults();

        assertNotNull(config);
        assertEquals(Path.of("./index"), config.getIndexDir());
        assertEquals(Constants.DEFAULT_INDEX_THREADS, config.getIndexThreads());
        assertEquals(10, config.getQueryLimit());
        assertEquals(Constants.BM25_K1, config.getBm25K1());
        assertEquals(Constants.BM25_B, config.getBm25B());
        assertEquals(Constants.MEMORY_SEGMENT_MAX_DOCS, config.getMemorySegmentMaxDocs());
        assertEquals(Constants.MEMORY_SEGMENT_MAX_BYTES, config.getMemorySegmentMaxBytes());
        assertEquals(Constants.MERGE_FACTOR, config.getMergeFactor());
    }

    @Test
    void testSetters() {
        EngineConfig config = new EngineConfig();
        Path newIndexDir = Path.of("./custom-index");

        config.setIndexDir(newIndexDir);
        config.setIndexThreads(8);
        config.setQueryLimit(50);
        config.setBm25K1(1.8);
        config.setBm25B(0.5);
        config.setMemorySegmentMaxDocs(20000);
        config.setMemorySegmentMaxBytes(128L * 1024 * 1024);
        config.setMergeFactor(20);

        assertEquals(newIndexDir, config.getIndexDir());
        assertEquals(8, config.getIndexThreads());
        assertEquals(50, config.getQueryLimit());
        assertEquals(1.8, config.getBm25K1());
        assertEquals(0.5, config.getBm25B());
        assertEquals(20000, config.getMemorySegmentMaxDocs());
        assertEquals(128L * 1024 * 1024, config.getMemorySegmentMaxBytes());
        assertEquals(20, config.getMergeFactor());
    }
}
