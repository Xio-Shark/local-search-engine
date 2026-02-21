package com.localengine.storage;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import org.junit.jupiter.api.Test;

class PostingListTest {

    @Test
    void testBasicAccessors() {
        PostingList postingList = new PostingList(new int[] {1, 3, 7}, new int[] {2, 1, 4});

        assertEquals(3, postingList.size());
        assertEquals(1, postingList.docId(0));
        assertEquals(4, postingList.termFreq(2));
    }

    @Test
    void testDefensiveCopyOnConstructorAndAccess() {
        int[] docIds = new int[] {1, 2};
        int[] termFreqs = new int[] {3, 4};
        PostingList postingList = new PostingList(docIds, termFreqs);

        docIds[0] = 99;
        termFreqs[1] = 88;
        assertArrayEquals(new int[] {1, 2}, postingList.docIds());
        assertArrayEquals(new int[] {3, 4}, postingList.termFreqs());

        int[] returnedDocIds = postingList.docIds();
        returnedDocIds[0] = 77;
        assertArrayEquals(new int[] {1, 2}, postingList.docIds());
    }

    @Test
    void testRejectNullArrays() {
        assertThrows(IllegalArgumentException.class, () -> new PostingList(null, new int[] {1}));
        assertThrows(IllegalArgumentException.class, () -> new PostingList(new int[] {1}, null));
    }

    @Test
    void testRejectLengthMismatch() {
        assertThrows(IllegalArgumentException.class, () -> new PostingList(new int[] {1, 2}, new int[] {1}));
    }

    @Test
    void testRejectNegativeDocIdAndTermFreq() {
        assertThrows(IllegalArgumentException.class, () -> new PostingList(new int[] {-1}, new int[] {1}));
        assertThrows(IllegalArgumentException.class, () -> new PostingList(new int[] {1}, new int[] {-1}));
    }

    @Test
    void testRejectNonIncreasingDocIds() {
        assertThrows(IllegalArgumentException.class, () -> new PostingList(new int[] {1, 1}, new int[] {1, 1}));
        assertThrows(IllegalArgumentException.class, () -> new PostingList(new int[] {2, 1}, new int[] {1, 1}));
    }
}
