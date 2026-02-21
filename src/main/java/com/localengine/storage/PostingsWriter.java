package com.localengine.storage;

import com.localengine.config.Constants;

import java.io.File;
import java.io.IOException;
import java.io.RandomAccessFile;

/**
 * 倒排文件写入器，负责写入 skip 区、docId 增量区和词频区。
 */
public final class PostingsWriter implements AutoCloseable {
    private final RandomAccessFile randomAccessFile;
    private final String postingsFileName;
    private boolean closed;

    /**
     * 创建倒排写入器并写入文件头。
     *
     * @param file 倒排文件
     * @throws IOException 初始化失败时抛出
     */
    public PostingsWriter(File file) throws IOException {
        if (file == null) {
            throw new IllegalArgumentException("倒排文件不能为空");
        }
        this.randomAccessFile = new RandomAccessFile(file, "rw");
        this.postingsFileName = file.getName();
        this.randomAccessFile.setLength(0L);
        this.randomAccessFile.writeInt(Constants.POSTINGS_MAGIC);
        this.randomAccessFile.writeShort(Constants.FORMAT_VERSION);
    }

    /**
     * 写入一条倒排列表并返回写入起始偏移。
     *
     * @param docIds 递增 docId 数组
     * @param termFreqs 词频数组
     * @return 该倒排列表在文件中的偏移
     * @throws IOException 写入失败时抛出
     */
    public long writePostingList(int[] docIds, int[] termFreqs) throws IOException {
        ensureOpen();
        validateInput(docIds, termFreqs);

        long postingOffset = randomAccessFile.getFilePointer();
        int documentCount = docIds.length;
        int skipCount = documentCount / Constants.SKIP_INTERVAL;

        int[] docIdDeltas = buildDocIdDeltas(docIds);
        int[] docIdByteOffsets = buildDocIdByteOffsets(docIdDeltas);

        StorageFileUtil.writeVarInt(randomAccessFile, documentCount);
        StorageFileUtil.writeVarInt(randomAccessFile, skipCount);

        for (int skipIndex = 0; skipIndex < skipCount; skipIndex++) {
            int targetDocIndex = (skipIndex + 1) * Constants.SKIP_INTERVAL - 1;
            randomAccessFile.writeInt(docIds[targetDocIndex]);
            randomAccessFile.writeInt(docIdByteOffsets[targetDocIndex]);
        }

        for (int delta : docIdDeltas) {
            StorageFileUtil.writeVarInt(randomAccessFile, delta);
        }

        for (int termFrequency : termFreqs) {
            StorageFileUtil.writeVarInt(randomAccessFile, termFrequency);
        }

        return postingOffset;
    }

    /**
     * 关闭写入器并追加文件级 CRC32。
     *
     * @throws IOException 关闭失败时抛出
     */
    @Override
    public void close() throws IOException {
        if (closed) {
            return;
        }
        try {
            randomAccessFile.seek(randomAccessFile.length());
            StorageFileUtil.appendCrc32Footer(randomAccessFile);
            StorageFileUtil.verifyCrc32Footer(randomAccessFile, postingsFileName);
        } catch (IOException exception) {
            throw new IOException("关闭倒排写入器失败: file=" + postingsFileName, exception);
        } finally {
            randomAccessFile.close();
            closed = true;
        }
    }

    /**
     * 校验输入数据的一致性与单调性。
     */
    private void validateInput(int[] docIds, int[] termFreqs) {
        if (docIds == null || termFreqs == null) {
            throw new IllegalArgumentException("docIds 和 termFreqs 不能为空");
        }
        if (docIds.length != termFreqs.length) {
            throw new IllegalArgumentException("docIds 与 termFreqs 长度不一致: " + docIds.length + " vs " + termFreqs.length);
        }
        for (int index = 0; index < docIds.length; index++) {
            if (docIds[index] < 0) {
                throw new IllegalArgumentException("docId 不能为负数: " + docIds[index]);
            }
            if (termFreqs[index] < 0) {
                throw new IllegalArgumentException("termFreq 不能为负数: " + termFreqs[index]);
            }
            if (index > 0 && docIds[index] <= docIds[index - 1]) {
                throw new IllegalArgumentException("docIds 必须严格递增");
            }
        }
    }

    /**
     * 将 docId 转换为增量数组。
     */
    private int[] buildDocIdDeltas(int[] docIds) {
        return DeltaCodec.encode(docIds);
    }

    /**
     * 计算每个 docId 在 docId 区块中的字节偏移。
     */
    private int[] buildDocIdByteOffsets(int[] docIdDeltas) {
        int[] offsets = new int[docIdDeltas.length];
        int currentOffset = 0;
        for (int index = 0; index < docIdDeltas.length; index++) {
            offsets[index] = currentOffset;
            currentOffset += VarIntCodec.varIntSize(docIdDeltas[index]);
        }
        return offsets;
    }

    /**
     * 校验写入器处于可写状态。
     */
    private void ensureOpen() {
        if (closed) {
            throw new IllegalStateException("PostingsWriter 已关闭");
        }
    }
}
