package com.localengine.storage;

import com.localengine.config.Constants;

import java.io.File;
import java.io.IOException;
import java.io.RandomAccessFile;

/**
 * 位置表写入器，写入按文档分组的增量位置数据。
 */
public final class PositionWriter implements AutoCloseable {
    private final RandomAccessFile randomAccessFile;
    private final String positionsFileName;
    private boolean closed;

    /**
     * 创建位置表写入器并写入文件头。
     *
     * @param file 位置文件
     * @throws IOException 初始化失败时抛出
     */
    public PositionWriter(File file) throws IOException {
        if (file == null) {
            throw new IllegalArgumentException("位置文件不能为空");
        }
        this.randomAccessFile = new RandomAccessFile(file, "rw");
        this.positionsFileName = file.getName();
        this.randomAccessFile.setLength(0L);
        this.randomAccessFile.writeInt(Constants.POSITIONS_MAGIC);
        this.randomAccessFile.writeShort(Constants.FORMAT_VERSION);
    }

    /**
     * 写入一个位置块并返回写入偏移。
     *
     * @param docIds 文档 ID 数组
     * @param positions 每个文档对应的位置数组
     * @return 位置块偏移
     * @throws IOException 写入失败时抛出
     */
    public long writePositions(int[] docIds, int[][] positions) throws IOException {
        ensureOpen();
        validateInput(docIds, positions);

        long blockOffset = randomAccessFile.getFilePointer();
        StorageFileUtil.writeVarInt(randomAccessFile, docIds.length);

        for (int index = 0; index < docIds.length; index++) {
            int documentId = docIds[index];
            int[] documentPositions = positions[index];
            StorageFileUtil.writeVarInt(randomAccessFile, documentId);
            StorageFileUtil.writeVarInt(randomAccessFile, documentPositions.length);

            int[] positionDeltas = DeltaCodec.encode(documentPositions);
            for (int delta : positionDeltas) {
                StorageFileUtil.writeVarInt(randomAccessFile, delta);
            }
        }
        return blockOffset;
    }

    /**
     * 关闭写入器并写入 CRC32 页脚。
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
            StorageFileUtil.verifyCrc32Footer(randomAccessFile, positionsFileName);
        } catch (IOException exception) {
            throw new IOException("关闭位置写入器失败: file=" + positionsFileName, exception);
        } finally {
            randomAccessFile.close();
            closed = true;
        }
    }

    /**
     * 校验输入数组完整性、长度一致性和递增关系。
     */
    private void validateInput(int[] docIds, int[][] positions) {
        if (docIds == null || positions == null) {
            throw new IllegalArgumentException("docIds 和 positions 不能为空");
        }
        if (docIds.length != positions.length) {
            throw new IllegalArgumentException("docIds 与 positions 长度不一致: " + docIds.length + " vs " + positions.length);
        }

        for (int index = 0; index < docIds.length; index++) {
            if (docIds[index] < 0) {
                throw new IllegalArgumentException("docId 不能为负数: " + docIds[index]);
            }
            if (index > 0 && docIds[index] <= docIds[index - 1]) {
                throw new IllegalArgumentException("docIds 必须严格递增");
            }

            int[] currentDocPositions = positions[index];
            if (currentDocPositions == null) {
                throw new IllegalArgumentException("positions[" + index + "] 不能为空");
            }
            for (int positionIndex = 0; positionIndex < currentDocPositions.length; positionIndex++) {
                if (currentDocPositions[positionIndex] < 0) {
                    throw new IllegalArgumentException("位置值不能为负数: " + currentDocPositions[positionIndex]);
                }
                if (positionIndex > 0 && currentDocPositions[positionIndex] <= currentDocPositions[positionIndex - 1]) {
                    throw new IllegalArgumentException("文档内位置必须严格递增");
                }
            }
        }
    }

    /**
     * 校验写入器可用状态。
     */
    private void ensureOpen() {
        if (closed) {
            throw new IllegalStateException("PositionWriter 已关闭");
        }
    }
}
