package com.localengine.storage;

import com.localengine.config.Constants;

import java.io.File;
import java.io.IOException;
import java.io.RandomAccessFile;

/**
 * 倒排文件读取器，按偏移读取单条倒排列表。
 */
public final class PostingsReader implements AutoCloseable {
    private final RandomAccessFile randomAccessFile;
    private final long dataLength;
    private boolean closed;

    /**
     * 构造读取器并完成文件头与 CRC 校验。
     *
     * @param file 倒排文件
     * @throws IOException 文件损坏或版本不兼容时抛出
     */
    public PostingsReader(File file) throws IOException {
        if (file == null) {
            throw new IllegalArgumentException("倒排文件不能为空");
        }
        this.randomAccessFile = new RandomAccessFile(file, "r");
        this.dataLength = StorageFileUtil.verifyCrc32Footer(randomAccessFile, file.getName());
        this.randomAccessFile.seek(0L);

        int magic = randomAccessFile.readInt();
        if (magic != Constants.POSTINGS_MAGIC) {
            throw new IOException("倒排文件 magic 不匹配: " + file.getName());
        }
        short version = randomAccessFile.readShort();
        if (version != Constants.FORMAT_VERSION) {
            throw new IOException("倒排文件版本不支持: " + version);
        }
    }

    /**
     * 从指定偏移读取一条倒排列表。
     *
     * @param offset 倒排列表偏移
     * @return 解码后的倒排列表
     * @throws IOException 读取或解码失败时抛出
     */
    public PostingList readPostingList(long offset) throws IOException {
        ensureOpen();
        if (offset < Integer.BYTES + Short.BYTES || offset >= dataLength) {
            throw new IOException("无效倒排偏移: " + offset);
        }

        randomAccessFile.seek(offset);
        int documentCount = StorageFileUtil.readVarInt(randomAccessFile);
        int skipCount = StorageFileUtil.readVarInt(randomAccessFile);
        if (documentCount < 0 || skipCount < 0) {
            throw new IOException("倒排块计数非法: docCount=" + documentCount + ", skipCount=" + skipCount + ", offset=" + offset);
        }
        for (int skipIndex = 0; skipIndex < skipCount; skipIndex++) {
            randomAccessFile.readInt();
            randomAccessFile.readInt();
        }

        int[] deltas = new int[documentCount];
        for (int index = 0; index < documentCount; index++) {
            deltas[index] = StorageFileUtil.readVarInt(randomAccessFile);
            if (deltas[index] < 0) {
                throw new IOException("docId delta非法: index=" + index + ", offset=" + offset);
            }
        }
        int[] docIds = DeltaCodec.decode(deltas);

        int[] termFreqs = new int[documentCount];
        for (int index = 0; index < documentCount; index++) {
            termFreqs[index] = StorageFileUtil.readVarInt(randomAccessFile);
            if (termFreqs[index] < 0) {
                throw new IOException("termFreq非法: index=" + index + ", offset=" + offset);
            }
        }

        return new PostingList(docIds, termFreqs);
    }

    /**
     * 关闭底层随机读取句柄。
     *
     * @throws IOException 关闭失败时抛出
     */
    @Override
    public void close() throws IOException {
        if (closed) {
            return;
        }
        randomAccessFile.close();
        closed = true;
    }

    /**
     * 校验读取器是否已经关闭。
     */
    private void ensureOpen() {
        if (closed) {
            throw new IllegalStateException("PostingsReader 已关闭");
        }
    }
}
