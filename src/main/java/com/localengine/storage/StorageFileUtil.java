package com.localengine.storage;

import java.io.ByteArrayOutputStream;
import java.io.EOFException;
import java.io.IOException;
import java.io.RandomAccessFile;
import java.util.zip.CRC32;

/**
 * 存储文件工具方法，封装 VarInt 与 CRC32 的随机访问读写逻辑。
 */
final class StorageFileUtil {
    private StorageFileUtil() {
    }

    /**
     * 向随机访问文件写入 VarInt。
     *
     * @param randomAccessFile 目标文件
     * @param value 非负整数
     * @throws IOException 写入失败时抛出
     */
    static void writeVarInt(RandomAccessFile randomAccessFile, int value) throws IOException {
        ByteArrayOutputStream buffer = new ByteArrayOutputStream();
        VarIntCodec.writeVarInt(value, buffer);
        randomAccessFile.write(buffer.toByteArray());
    }

    /**
     * 从随机访问文件读取 VarInt。
     *
     * @param randomAccessFile 源文件
     * @return 解码后的整数
     * @throws IOException 遇到 EOF 或格式损坏时抛出
     */
    static int readVarInt(RandomAccessFile randomAccessFile) throws IOException {
        int result = 0;
        int shift = 0;
        while (shift < 32) {
            int currentByte = randomAccessFile.read();
            if (currentByte == -1) {
                throw new EOFException("读取 VarInt 时遇到 EOF");
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
     * 计算指定前缀字节区间的 CRC32。
     *
     * @param randomAccessFile 源文件
     * @param length 参与校验的字节长度
     * @return CRC32 无符号值
     * @throws IOException 读取失败时抛出
     */
    static long computeCrc32(RandomAccessFile randomAccessFile, long length) throws IOException {
        long originalPointer = randomAccessFile.getFilePointer();
        CRC32 crc32 = new CRC32();
        byte[] buffer = new byte[8 * 1024];
        long remainingBytes = length;
        randomAccessFile.seek(0L);
        while (remainingBytes > 0) {
            int chunkSize = (int) Math.min(buffer.length, remainingBytes);
            int readBytes = randomAccessFile.read(buffer, 0, chunkSize);
            if (readBytes < 0) {
                throw new EOFException("计算 CRC32 时遇到 EOF");
            }
            crc32.update(buffer, 0, readBytes);
            remainingBytes -= readBytes;
        }
        randomAccessFile.seek(originalPointer);
        return crc32.getValue();
    }

    /**
     * 在文件尾部追加 CRC32 页脚。
     *
     * @param randomAccessFile 目标文件
     * @throws IOException 写入失败时抛出
     */
    static void appendCrc32Footer(RandomAccessFile randomAccessFile) throws IOException {
        long dataLength = randomAccessFile.length();
        long crc32Value = computeCrc32(randomAccessFile, dataLength);
        randomAccessFile.seek(dataLength);
        randomAccessFile.writeInt((int) crc32Value);
    }

    /**
     * 验证尾部 CRC32 并返回数据区长度。
     *
     * @param randomAccessFile 源文件
     * @param fileName 文件名（用于错误消息）
     * @return 不含 CRC 页脚的数据区长度
     * @throws IOException CRC 不匹配或文件过短时抛出
     */
    static long verifyCrc32Footer(RandomAccessFile randomAccessFile, String fileName) throws IOException {
        long fileLength = randomAccessFile.length();
        if (fileLength < Integer.BYTES) {
            throw new IOException("文件过短，缺少 CRC32 页脚: " + fileName);
        }
        long dataLength = fileLength - Integer.BYTES;
        randomAccessFile.seek(dataLength);
        long expectedCrc32 = Integer.toUnsignedLong(randomAccessFile.readInt());
        long actualCrc32 = computeCrc32(randomAccessFile, dataLength);
        if (actualCrc32 != expectedCrc32) {
            throw new IOException("CRC32 校验失败: " + fileName + ", expected=" + expectedCrc32 + ", actual=" + actualCrc32);
        }
        return dataLength;
    }
}
