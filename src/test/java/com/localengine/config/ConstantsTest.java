package com.localengine.config;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;

import java.lang.reflect.Constructor;
import org.junit.jupiter.api.Test;

class ConstantsTest {

    @Test
    void testConstantValues() {
        assertEquals(0x4C534449, Constants.DICT_MAGIC);
        assertEquals(0x4C535049, Constants.POSTINGS_MAGIC);
        assertEquals(0x4C535053, Constants.POSITIONS_MAGIC);
        assertEquals(1, Constants.FORMAT_VERSION);

        assertEquals(128, Constants.SKIP_INTERVAL);
        assertEquals(10_000, Constants.MEMORY_SEGMENT_MAX_DOCS);
        assertEquals(64L * 1024 * 1024, Constants.MEMORY_SEGMENT_MAX_BYTES);
        assertEquals(10, Constants.MERGE_FACTOR);

        assertEquals(1.2, Constants.BM25_K1);
        assertEquals(0.75, Constants.BM25_B);
        assertEquals(80, Constants.SNIPPET_CONTEXT_CHARS);
        assertEquals(3, Constants.MAX_SNIPPETS);
        assertEquals(16L * 1024 * 1024, Constants.WAL_MAX_SIZE);
        assertEquals(1000, Constants.FILE_COLLECTOR_QUEUE_CAPACITY);
    }

    @Test
    void testPrivateConstructorReachableByReflection() throws Exception {
        Constructor<Constants> constructor = Constants.class.getDeclaredConstructor();
        constructor.setAccessible(true);

        Constants constantsInstance = constructor.newInstance();
        assertNotNull(constantsInstance);
    }
}
