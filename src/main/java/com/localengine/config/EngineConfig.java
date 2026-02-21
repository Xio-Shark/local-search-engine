package com.localengine.config;

import java.nio.file.Path;
import java.nio.file.Paths;

/**
 * 引擎运行时配置
 * 
 * 支持从CLI参数或配置文件注入，覆盖Constants默认值
 */
public class EngineConfig {
    private Path indexDir = Paths.get("./index");
    private int indexThreads = Constants.DEFAULT_INDEX_THREADS;
    private int queryLimit = 10;
    private double bm25K1 = Constants.BM25_K1;
    private double bm25B = Constants.BM25_B;
    private int memorySegmentMaxDocs = Constants.MEMORY_SEGMENT_MAX_DOCS;
    private long memorySegmentMaxBytes = Constants.MEMORY_SEGMENT_MAX_BYTES;
    private int mergeFactor = Constants.MERGE_FACTOR;
    
    public Path getIndexDir() {
        return indexDir;
    }
    
    public void setIndexDir(Path indexDir) {
        this.indexDir = indexDir;
    }
    
    public int getIndexThreads() {
        return indexThreads;
    }
    
    public void setIndexThreads(int indexThreads) {
        this.indexThreads = indexThreads;
    }
    
    public int getQueryLimit() {
        return queryLimit;
    }
    
    public void setQueryLimit(int queryLimit) {
        this.queryLimit = queryLimit;
    }
    
    public double getBm25K1() {
        return bm25K1;
    }
    
    public void setBm25K1(double bm25K1) {
        this.bm25K1 = bm25K1;
    }
    
    public double getBm25B() {
        return bm25B;
    }
    
    public void setBm25B(double bm25B) {
        this.bm25B = bm25B;
    }
    
    public int getMemorySegmentMaxDocs() {
        return memorySegmentMaxDocs;
    }
    
    public void setMemorySegmentMaxDocs(int memorySegmentMaxDocs) {
        this.memorySegmentMaxDocs = memorySegmentMaxDocs;
    }
    
    public long getMemorySegmentMaxBytes() {
        return memorySegmentMaxBytes;
    }
    
    public void setMemorySegmentMaxBytes(long memorySegmentMaxBytes) {
        this.memorySegmentMaxBytes = memorySegmentMaxBytes;
    }
    
    public int getMergeFactor() {
        return mergeFactor;
    }
    
    public void setMergeFactor(int mergeFactor) {
        this.mergeFactor = mergeFactor;
    }
    
    /**
     * 使用默认配置创建实例
     */
    public static EngineConfig defaults() {
        return new EngineConfig();
    }
}
