package com.localengine.storage;

import com.localengine.config.Constants;

import java.io.File;
import java.io.IOException;
import java.io.RandomAccessFile;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 位置表读取器，支持读取整块位置数据或单文档位置数据。
 */
public final class PositionReader implements AutoCloseable {
    private final RandomAccessFile randomAccessFile;
    private final long dataLength;
    private boolean closed;

    /**
     * 构造读取器并验证文件头与 CRC32。
     *
     * @param file 位置文件
     * @throws IOException 文件损坏或版本不支持时抛出
     */
    public PositionReader(File file) throws IOException {
        if (file == null) {
            throw new IllegalArgumentException("位置文件不能为空");
        }
        this.randomAccessFile = new RandomAccessFile(file, "r");
        this.dataLength = StorageFileUtil.verifyCrc32Footer(randomAccessFile, file.getName());
        this.randomAccessFile.seek(0L);

        int magic = randomAccessFile.readInt();
        if (magic != Constants.POSITIONS_MAGIC) {
            throw new IOException("位置文件 magic 不匹配: " + file.getName());
        }
        short version = randomAccessFile.readShort();
        if (version != Constants.FORMAT_VERSION) {
            throw new IOException("位置文件版本不支持: " + version);
        }
    }

    /**
     * 从指定偏移读取完整位置块。
     *
     * @param offset 位置块偏移
     * @return docId 到位置数组的映射
     * @throws IOException 读取或解析失败时抛出
     */
    public Map<Integer, int[]> readPositions(long offset) throws IOException {
        ensureOpen();
        randomAccessFile.seek(validateOffset(offset));
        int documentCount = StorageFileUtil.readVarInt(randomAccessFile);
        if (documentCount < 0) {
            throw new IOException("位置块docCount非法: " + documentCount + ", offset=" + offset);
        }
        Map<Integer, int[]> positionsByDocId = new LinkedHashMap<>(documentCount);

        for (int index = 0; index < documentCount; index++) {
            int documentId = StorageFileUtil.readVarInt(randomAccessFile);
            int positionCount = StorageFileUtil.readVarInt(randomAccessFile);
            if (documentId < 0 || positionCount < 0) {
                throw new IOException("位置块字段非法: docId=" + documentId + ", posCount=" + positionCount + ", index=" + index);
            }
            int[] decodedPositions = decodePositions(positionCount);
            positionsByDocId.put(documentId, decodedPositions);
        }
        return positionsByDocId;
    }

    /**
     * 从指定偏移读取特定文档的位置数组，未命中返回空数组。
     *
     * @param offset 位置块偏移
     * @param docId 目标文档 ID
     * @return 目标文档的位置数组或空数组
     * @throws IOException 读取失败时抛出
     */
    public int[] readPositionsForDoc(long offset, int docId) throws IOException {
        ensureOpen();
        randomAccessFile.seek(validateOffset(offset));
        int documentCount = StorageFileUtil.readVarInt(randomAccessFile);
        if (documentCount < 0) {
            throw new IOException("位置块docCount非法: " + documentCount + ", offset=" + offset);
        }

        for (int index = 0; index < documentCount; index++) {
            int currentDocId = StorageFileUtil.readVarInt(randomAccessFile);
            int positionCount = StorageFileUtil.readVarInt(randomAccessFile);
            if (currentDocId < 0 || positionCount < 0) {
                throw new IOException("位置块字段非法: docId=" + currentDocId + ", posCount=" + positionCount + ", index=" + index);
            }
            int[] decodedPositions = decodePositions(positionCount);
            if (currentDocId == docId) {
                return decodedPositions;
            }
        }
        return new int[0];
    }

    /**
     * 关闭读取器。
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
     * 解码单文档的位置增量数组。
     */
    private int[] decodePositions(int positionCount) throws IOException {
        int[] deltas = new int[positionCount];
        for (int positionIndex = 0; positionIndex < positionCount; positionIndex++) {
            deltas[positionIndex] = StorageFileUtil.readVarInt(randomAccessFile);
            if (deltas[positionIndex] < 0) {
                throw new IOException("位置delta非法: index=" + positionIndex + ", posCount=" + positionCount);
            }
        }
        return DeltaCodec.decode(deltas);
    }

    /**
     * 校验偏移合法性。
     */
    private long validateOffset(long offset) throws IOException {
        if (offset < Integer.BYTES + Short.BYTES || offset >= dataLength) {
            throw new IOException("无效位置偏移: " + offset);
        }
        return offset;
    }

    /**
     * 校验读取器是否可用。
     */
    private void ensureOpen() {
        if (closed) {
            throw new IllegalStateException("PositionReader 已关闭");
        }
    }
}
