package com.localengine.storage;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;

import java.io.File;
import java.io.IOException;
import java.time.Instant;

/**
 * 段元数据，描述段的基础统计信息与生命周期状态。
 */
public record SegmentMeta(
    String segmentId,
    int docCount,
    int termCount,
    long sizeBytes,
    String status,
    int level,
    Instant createTime
) {
    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper()
        .registerModule(new JavaTimeModule())
        .disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS);

    /**
     * 将当前段元数据写入指定 JSON 文件。
     *
     * @param file 元数据文件
     * @throws IOException 写入失败时抛出
     */
    public void writeTo(File file) throws IOException {
        if (file == null) {
            throw new IllegalArgumentException("元数据文件不能为空");
        }
        try {
            OBJECT_MAPPER.writerWithDefaultPrettyPrinter().writeValue(file, this);
        } catch (IOException exception) {
            throw new IOException("写入段元数据失败: " + file.getAbsolutePath(), exception);
        }
    }

    /**
     * 从指定 JSON 文件读取段元数据。
     *
     * @param file 元数据文件
     * @return 反序列化后的段元数据
     * @throws IOException 读取或解析失败时抛出
     */
    public static SegmentMeta readFrom(File file) throws IOException {
        if (file == null) {
            throw new IllegalArgumentException("元数据文件不能为空");
        }
        try {
            return OBJECT_MAPPER.readValue(file, SegmentMeta.class);
        } catch (IOException exception) {
            throw new IOException("读取段元数据失败: " + file.getAbsolutePath(), exception);
        }
    }
}
