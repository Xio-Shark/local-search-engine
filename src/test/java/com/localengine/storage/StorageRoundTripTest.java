package com.localengine.storage;

import com.localengine.config.Constants;
import org.junit.jupiter.api.Test;

import java.io.File;
import java.io.IOException;
import java.io.RandomAccessFile;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Random;
import java.util.TreeMap;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 存储层文件格式集成测试，覆盖词典/倒排/位置 round-trip 与 CRC 防护。
 */
class StorageRoundTripTest {

    /**
     * 验证词典文件写入读取一致性与前缀搜索能力。
     */
    @Test
    void dictionaryRoundTripAndPrefixSearch() throws IOException {
        File dictionaryFile = Files.createTempFile("storage-roundtrip", ".dict").toFile();
        dictionaryFile.deleteOnExit();

        List<String> allTerms = buildSortedTerms();
        Map<String, TermEntry> expectedByTerm = new TreeMap<>();
        Random random = new Random(7);

        try (DictionaryWriter writer = new DictionaryWriter(dictionaryFile)) {
            for (String term : allTerms) {
                int docFrequency = random.nextInt(500) + 1;
                long postingsOffset = random.nextInt(1_000_000);
                long positionsOffset = random.nextInt(1_000_000);
                writer.writeTermEntry(term, docFrequency, postingsOffset, positionsOffset);
                expectedByTerm.put(term, new TermEntry(term, docFrequency, postingsOffset, positionsOffset));
            }
        }

        DictionaryReader reader = new DictionaryReader(dictionaryFile);
        assertEquals(expectedByTerm.size(), reader.getTermCount());

        for (Map.Entry<String, TermEntry> entry : expectedByTerm.entrySet()) {
            Optional<TermEntry> found = reader.lookup(entry.getKey());
            assertTrue(found.isPresent());
            assertEquals(entry.getValue(), found.get());
        }

        List<TermEntry> prefixResult = reader.prefixSearch("app");
        List<String> prefixTerms = prefixResult.stream().map(TermEntry::term).toList();
        assertEquals(List.of("app", "apple", "application", "apply"), prefixTerms);
    }

    /**
     * 验证倒排列表 round-trip 以及 skip entry 编码正确性。
     */
    @Test
    void postingsRoundTripAndSkipList() throws IOException {
        File postingsFile = Files.createTempFile("storage-roundtrip", ".inv").toFile();
        postingsFile.deleteOnExit();

        Random random = new Random(11);
        int[] docIds = new int[350];
        int[] termFreqs = new int[350];
        int currentDocId = 0;
        for (int index = 0; index < docIds.length; index++) {
            currentDocId += random.nextInt(4) + 1;
            docIds[index] = currentDocId;
            termFreqs[index] = random.nextInt(6) + 1;
        }

        long postingOffset;
        try (PostingsWriter writer = new PostingsWriter(postingsFile)) {
            postingOffset = writer.writePostingList(docIds, termFreqs);
        }

        try (PostingsReader reader = new PostingsReader(postingsFile)) {
            PostingList postingList = reader.readPostingList(postingOffset);
            assertArrayEquals(docIds, postingList.docIds());
            assertArrayEquals(termFreqs, postingList.termFreqs());
        }

        int[] expectedDeltas = buildDocIdDeltas(docIds);
        int[] expectedOffsets = buildDeltaOffsets(expectedDeltas);
        int expectedSkipCount = docIds.length / Constants.SKIP_INTERVAL;

        try (RandomAccessFile randomAccessFile = new RandomAccessFile(postingsFile, "r")) {
            randomAccessFile.seek(postingOffset);
            int docCount = readVarInt(randomAccessFile);
            int skipCount = readVarInt(randomAccessFile);
            assertEquals(docIds.length, docCount);
            assertEquals(expectedSkipCount, skipCount);

            for (int skipIndex = 0; skipIndex < skipCount; skipIndex++) {
                int docIndex = (skipIndex + 1) * Constants.SKIP_INTERVAL - 1;
                int skipDocId = randomAccessFile.readInt();
                int skipOffset = randomAccessFile.readInt();
                assertEquals(docIds[docIndex], skipDocId);
                assertEquals(expectedOffsets[docIndex], skipOffset);
            }
        }
    }

    /**
     * 验证位置表完整 round-trip 与按文档读取能力。
     */
    @Test
    void positionsRoundTripAndReadByDoc() throws IOException {
        File positionFile = Files.createTempFile("storage-roundtrip", ".pos").toFile();
        positionFile.deleteOnExit();

        Random random = new Random(19);
        int[] docIds = new int[120];
        int[][] expectedPositions = new int[120][];
        int currentDocId = 0;
        for (int index = 0; index < docIds.length; index++) {
            currentDocId += random.nextInt(5) + 1;
            docIds[index] = currentDocId;

            int positionCount = random.nextInt(5) + 1;
            expectedPositions[index] = new int[positionCount];
            int positionValue = 0;
            for (int positionIndex = 0; positionIndex < positionCount; positionIndex++) {
                positionValue += random.nextInt(4) + 1;
                expectedPositions[index][positionIndex] = positionValue;
            }
        }

        long positionOffset;
        try (PositionWriter writer = new PositionWriter(positionFile)) {
            positionOffset = writer.writePositions(docIds, expectedPositions);
        }

        try (PositionReader reader = new PositionReader(positionFile)) {
            Map<Integer, int[]> allPositions = reader.readPositions(positionOffset);
            assertEquals(docIds.length, allPositions.size());

            for (int index = 0; index < docIds.length; index++) {
                int docId = docIds[index];
                assertArrayEquals(expectedPositions[index], allPositions.get(docId));
                assertArrayEquals(expectedPositions[index], reader.readPositionsForDoc(positionOffset, docId));
            }

            assertArrayEquals(new int[0], reader.readPositionsForDoc(positionOffset, Integer.MAX_VALUE));
        }
    }

    /**
     * 验证 CRC32 校验可拦截损坏文件。
     */
    @Test
    void crcCorruptionShouldThrow() throws IOException {
        File dictionaryFile = Files.createTempFile("storage-crc", ".dict").toFile();
        dictionaryFile.deleteOnExit();
        try (DictionaryWriter writer = new DictionaryWriter(dictionaryFile)) {
            writer.writeTermEntry("checksum", 3, 128L, 256L);
        }
        corruptOneByte(dictionaryFile, 2);
        assertThrows(IOException.class, () -> new DictionaryReader(dictionaryFile));

        File postingsFile = Files.createTempFile("storage-crc", ".inv").toFile();
        postingsFile.deleteOnExit();
        try (PostingsWriter writer = new PostingsWriter(postingsFile)) {
            writer.writePostingList(new int[]{3, 10, 27}, new int[]{1, 2, 3});
        }
        corruptOneByte(postingsFile, 3);
        assertThrows(IOException.class, () -> new PostingsReader(postingsFile));
    }

    /**
     * 构造带有 app 前缀的有序测试词项。
     */
    private List<String> buildSortedTerms() {
        List<String> terms = new ArrayList<>(List.of("app", "apple", "application", "apply", "banana", "band"));
        for (int index = 0; index < 60; index++) {
            terms.add("term_" + String.format("%03d", index));
        }
        return terms.stream().sorted().toList();
    }

    /**
     * 计算 docId 的增量数组。
     */
    private int[] buildDocIdDeltas(int[] docIds) {
        int[] deltas = new int[docIds.length];
        int previousDocId = 0;
        for (int index = 0; index < docIds.length; index++) {
            int currentDocId = docIds[index];
            deltas[index] = index == 0 ? currentDocId : currentDocId - previousDocId;
            previousDocId = currentDocId;
        }
        return deltas;
    }

    /**
     * 计算每个增量值在编码区中的字节偏移。
     */
    private int[] buildDeltaOffsets(int[] deltas) {
        int[] offsets = new int[deltas.length];
        int runningOffset = 0;
        for (int index = 0; index < deltas.length; index++) {
            offsets[index] = runningOffset;
            runningOffset += VarIntCodec.varIntSize(deltas[index]);
        }
        return offsets;
    }

    /**
     * 使用与生产代码一致的 VarInt 规则读取整数。
     */
    private int readVarInt(RandomAccessFile randomAccessFile) throws IOException {
        int result = 0;
        int shift = 0;
        while (shift < 32) {
            int currentByte = randomAccessFile.read();
            if (currentByte == -1) {
                throw new IOException("读取 VarInt 失败：意外 EOF");
            }
            result |= (currentByte & 0x7F) << shift;
            if ((currentByte & 0x80) == 0) {
                return result;
            }
            shift += 7;
        }
        throw new IOException("VarInt 超过 32 位范围");
    }

    /**
     * 定位到指定偏移并翻转一个字节，模拟磁盘损坏。
     */
    private void corruptOneByte(File file, long offset) throws IOException {
        try (RandomAccessFile randomAccessFile = new RandomAccessFile(file, "rw")) {
            randomAccessFile.seek(offset);
            int origin = randomAccessFile.readUnsignedByte();
            randomAccessFile.seek(offset);
            randomAccessFile.writeByte(origin ^ 0xFF);
        }
    }
}
