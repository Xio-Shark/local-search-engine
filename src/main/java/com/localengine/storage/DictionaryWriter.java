package com.localengine.storage;

import com.localengine.config.Constants;

import java.io.File;
import java.io.IOException;
import java.io.RandomAccessFile;
import java.nio.charset.StandardCharsets;

/**
 * 词典文件写入器，按严格递增词序写入词条并在关闭时追加 CRC32。
 */
public final class DictionaryWriter implements AutoCloseable {
    private static final long TERM_COUNT_OFFSET = Integer.BYTES + Short.BYTES;

    private final RandomAccessFile randomAccessFile;
    private final String dictionaryFileName;
    private int termCount;
    private String lastTerm;
    private boolean closed;

    /**
     * 创建词典文件写入器并写入文件头。
     *
     * @param file 目标词典文件
     * @throws IOException 初始化失败时抛出
     */
    public DictionaryWriter(File file) throws IOException {
        if (file == null) {
            throw new IllegalArgumentException("词典文件不能为空");
        }
        this.randomAccessFile = new RandomAccessFile(file, "rw");
        this.dictionaryFileName = file.getName();
        this.randomAccessFile.setLength(0L);
        this.randomAccessFile.writeInt(Constants.DICT_MAGIC);
        this.randomAccessFile.writeShort(Constants.FORMAT_VERSION);
        this.randomAccessFile.writeInt(0);
    }

    /**
     * 写入一个词条，要求 term 按字典序严格递增。
     *
     * @param term 词项
     * @param docFreq 文档频次
     * @param postingsOffset 倒排偏移
     * @param positionsOffset 位置偏移
     * @throws IOException 写入失败时抛出
     */
    public void writeTermEntry(String term, int docFreq, long postingsOffset, long positionsOffset) throws IOException {
        ensureOpen();
        if (term == null || term.isEmpty()) {
            throw new IllegalArgumentException("term 不能为空");
        }
        if (docFreq < 0) {
            throw new IllegalArgumentException("docFreq 不能为负数: " + docFreq);
        }
        if (postingsOffset < 0 || positionsOffset < 0) {
            throw new IllegalArgumentException("offset 不能为负数");
        }
        if (lastTerm != null && term.compareTo(lastTerm) <= 0) {
            throw new IllegalArgumentException("term 必须严格递增，last=" + lastTerm + ", current=" + term);
        }

        byte[] termBytes = term.getBytes(StandardCharsets.UTF_8);
        StorageFileUtil.writeVarInt(randomAccessFile, termBytes.length);
        randomAccessFile.write(termBytes);
        StorageFileUtil.writeVarInt(randomAccessFile, docFreq);
        randomAccessFile.writeLong(postingsOffset);
        randomAccessFile.writeLong(positionsOffset);

        termCount++;
        lastTerm = term;
    }

    /**
     * 回填 termCount 并写入 CRC32 页脚。
     *
     * @throws IOException 关闭失败时抛出
     */
    @Override
    public void close() throws IOException {
        if (closed) {
            return;
        }
        try {
            randomAccessFile.seek(TERM_COUNT_OFFSET);
            randomAccessFile.writeInt(termCount);
            randomAccessFile.seek(randomAccessFile.length());
            StorageFileUtil.appendCrc32Footer(randomAccessFile);
            StorageFileUtil.verifyCrc32Footer(randomAccessFile, dictionaryFileName);
        } catch (IOException exception) {
            throw new IOException("关闭词典写入器失败: file=" + dictionaryFileName + ", termCount=" + termCount, exception);
        } finally {
            randomAccessFile.close();
            closed = true;
        }
    }

    /**
     * 校验写入器状态，防止关闭后继续写入。
     */
    private void ensureOpen() {
        if (closed) {
            throw new IllegalStateException("DictionaryWriter 已关闭");
        }
    }
}
