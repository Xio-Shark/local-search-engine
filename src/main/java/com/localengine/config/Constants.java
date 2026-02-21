package com.localengine.config;

/**
 * 全局常量定义
 * 
 * 包含存储格式魔数、索引参数、BM25参数、Snippet参数和WAL参数
 */
public final class Constants {
    private Constants() {
        // 工具类，禁止实例化
    }
    
    // ==================== 存储格式魔数 ====================
    /** 词典文件魔数 "LSDI" */
    public static final int DICT_MAGIC = 0x4C534449;
    /** 倒排列表文件魔数 "LSPI" */
    public static final int POSTINGS_MAGIC = 0x4C535049;
    /** 位置表文件魔数 "LSPS" */
    public static final int POSITIONS_MAGIC = 0x4C535053;
    /** 文件格式版本号 */
    public static final short FORMAT_VERSION = 1;
    
    // ==================== 索引参数 ====================
    /** 跳表间隔，每128个docId插入一个skip entry */
    public static final int SKIP_INTERVAL = 128;
    /** 内存段文档上限 */
    public static final int MEMORY_SEGMENT_MAX_DOCS = 10_000;
    /** 内存段字节上限（64MB） */
    public static final long MEMORY_SEGMENT_MAX_BYTES = 64L * 1024 * 1024;
    /** 段合并阈值，同层达到此数量触发合并 */
    public static final int MERGE_FACTOR = 10;
    
    // ==================== BM25参数 ====================
    /** 词频饱和系数 */
    public static final double BM25_K1 = 1.2;
    /** 长度归一化系数 */
    public static final double BM25_B = 0.75;
    
    // ==================== Snippet参数 ====================
    /** Snippet单侧上下文字符数 */
    public static final int SNIPPET_CONTEXT_CHARS = 80;
    /** 最大snippet数量 */
    public static final int MAX_SNIPPETS = 3;
    
    // ==================== WAL参数 ====================
    /** WAL文件最大大小（16MB），超过后轮转 */
    public static final long WAL_MAX_SIZE = 16L * 1024 * 1024;
    
    // ==================== 线程参数 ====================
    /** 默认索引工作线程数 */
    public static final int DEFAULT_INDEX_THREADS = Runtime.getRuntime().availableProcessors();
    /** 文件收集队列容量 */
    public static final int FILE_COLLECTOR_QUEUE_CAPACITY = 1000;
}
