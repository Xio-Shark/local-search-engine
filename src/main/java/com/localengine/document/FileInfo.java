package com.localengine.document;

import java.nio.file.Path;
import java.time.Instant;

/**
 * 文件信息记录
 */
public record FileInfo(Path path, long sizeBytes, Instant mtime, boolean isNote) {
    
    /**
     * 毒丸对象，用于标记队列结束
     */
    public static final FileInfo POISON = 
        new FileInfo(Path.of("__POISON__"), -1, Instant.EPOCH, false);
}
