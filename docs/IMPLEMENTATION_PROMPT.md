# 本地搜索引擎 — AI 编码 Prompt

> 将此 Prompt 直接喂给 AI 编码助手，即可按照规范逐模块实现项目。  
> 按 Phase 顺序执行，每个 Phase 完成后编译验证再进入下一个。

---

## 全局约束

```yaml
项目名: local-search-engine
语言: Java 21 (LTS)
构建: Gradle 8.6 (Kotlin DSL)
包名: com.localengine
风格:
  - 注释必须中文
  - 变量命名英文，驼峰命名
  - 每个类顶部 Javadoc 说明职责
  - 常量提取到 Constants.java
  - 不使用 Lucene/Elasticsearch 等搜索框架
  - 不使用实验性特性
```

---

## Phase 1: 存储基础

### Prompt 1.1 — 编码器
```
实现两个编码工具类：

1. VarIntCodec（变长整数编解码器）：
   - writeVarInt(int value, OutputStream out)
   - readVarInt(InputStream in) → int，流结束返回 -1
   - writeVarInt(int value, ByteBuffer buf)
   - readVarInt(ByteBuffer buf) → int
   - writeVarLong / readVarLong (long 版本)
   - varIntSize(int value) → 预计字节数
   - 编码规则：每字节 7 位有效，最高位为续接标志

2. DeltaCodec（Delta 编码器）：
   - encode(int[] values) → int[] deltas
   - decode(int[] deltas) → int[] values
   - encodeDeltaVarInt(int[] values, OutputStream out)
   - decodeDeltaVarInt(int count, InputStream in) → int[]
   - estimateEncodedSize(int[] values) → int

要求：输入必须是非负单调递增序列。写完后创建 CodecTest 单元测试。
```

### Prompt 1.2 — 文件格式读写器
```
基于 VarIntCodec 和 DeltaCodec 实现三组文件读写器。

1. DictionaryWriter / DictionaryReader
   文件格式：Header(magic 0x4C534449 + version 1 + termCount) + N 条 TermEntry + CRC32
   TermEntry = termLen(VarInt) + termBytes(UTF-8) + docFreq(VarInt) + postingsOffset(8B) + positionsOffset(8B)
   - Writer: 验证 term 严格递增，close 后调用 patchTermCount(File) 回填 header
   - Reader: new DictionaryReader(File) 时全量加载到 TreeMap
   - Reader 提供: lookup(term), prefixSearch(prefix), allTerms(), contains(term), getTermCount()

2. PostingsWriter / PostingsReader
   文件格式：Header(magic 0x4C535049 + version) + N 个 PostingList
   PostingList = docCount(VarInt) + skipCount(VarInt) + SkipEntries + DeltaDocIds(VarInt) + TermFreqs(VarInt)
   SkipEntry = skipDocId(4B) + skipOffset(4B)，每 128 个 docId 插一个
   - Writer: writePostingList(int[] docIds, int[] termFreqs) → long offset
   - Reader: 使用 RandomAccessFile，readPostingList(long offset) → PostingList record
   - PostingList record 提供: size(), docId(i), termFreq(i), docIds(), termFreqs()

3. PositionWriter / PositionReader
   文件格式：Header(magic 0x4C535053 + version) + N 个 PositionBlock + CRC32
   PositionBlock = docCount(VarInt) + [docId(VarInt) + posCount(VarInt) + positions(delta-VarInt)] × docCount
   - Writer: writePositions(int[] docIds, int[][] positions) → long offset
   - Reader: readPositions(offset) → Map<Integer, int[]>, readPositionsForDoc(offset, docId) → int[]

4. SegmentMeta — JSON 序列化的段元数据
   字段：segmentId, docCount, termCount, sizeBytes, status(ACTIVE/MERGING/DELETED), level, createTime
   - writeTo(File) / readFrom(File) 使用 Jackson

写完后创建 StorageRoundTripTest，测试写入→读取的正确性，包含前缀查询测试。
```

---

## Phase 2: 索引流水线

### Prompt 2.1 — 文档模型与元数据
```
1. Document record：
   (int docId, Path path, String extension, long sizeBytes, Instant mtime, DocType docType, int tokenCount)
   DocType 枚举: CODE, NOTE, DOC, DATA, CONFIG, OTHER
   工厂方法 ofFile(int docId, Path path, List<Path> notePaths) — 根据扩展名和路径推断 docType
   方法 withTokenCount(int count) 返回新实例

2. DocumentTable (SQLite)：
   表结构：doc_id INTEGER PK, path TEXT UNIQUE, extension TEXT, size_bytes INTEGER, mtime TEXT, doc_type TEXT, token_count INTEGER
   启用 WAL 模式
   方法：insert, update(docId, size, mtime, tokenCount), deleteByPath → Optional<Integer>, findByPath, findById
   过滤方法（均返回 List<Integer>）：findDocIdsByExtension, findDocIdsByType, findDocIdsByMtimeRange, findDocIdsBySizeRange, findDocIdsByPathPrefix
   统计方法：getTotalDocCount, getAverageDocLength, nextDocId

写完后测试 CRUD 和过滤方法。
```

### Prompt 2.2 — 分词器
```
SPI 接口 Tokenizer：tokenize(String text) → List<Token>
Token record: (String term, int position, int startOffset, int endOffset)

实现：
1. EnglishTokenizer(boolean enableStopWords)：非字母数字分割 → 小写 → 过滤 length≤1 → 可选停用词
2. StopWords：静态 Set.of("the","a","an","is","are","was","were","be","been","has","have","had","do","does","did","will","would","could","should","may","might","can","and","or","but","not","in","on","at","to","for","of","with","by","from","as","into","it","its","this","that","which","if","so","no","up","out","all","just","also","very")
3. BigramTokenizer：检测连续 CJK 字符 → 两两切分（单字符也输出），忽略非 CJK
4. CompositeTokenizer(boolean enableStopWords)：按字符类型分段，CJK 段用 BigramTokenizer，其余用 EnglishTokenizer，全局 position 递增

CJK 检测：Character.UnicodeScript.of(ch) ∈ {HAN, HIRAGANA, KATAKANA, HANGUL}

写完后测试：中英混合分词、停用词过滤、position 连续性。
```

### Prompt 2.3 — 核心索引组件
```
1. FileCollector：
   构造：FileCollector(Set<String> supportedExtensions, List<Path> notePaths)
   方法：
   - collectAll(List<Path> sourcePaths) → List<FileInfo>
   - streamCollect(List<Path> sourcePaths, BlockingQueue<FileInfo> queue) — 流式版，遍历完放 POISON pill
   FileInfo record: (Path path, long sizeBytes, Instant mtime, boolean isNote)
   静态常量 POISON = new FileInfo(Path.of("__POISON__"), -1, Instant.EPOCH, false)
   过滤逻辑：按扩展名 + 可读 + 非隐藏

2. WAL (Write-Ahead Log)：
   构造：WAL(Path walDir)
   格式：[op(1B)] [timestamp(8B)] [pathLen(VarInt)] [path(UTF-8)] [mtime(8B)] [size(8B)]
   方法：appendAdd/appendDelete/appendUpdate(path, mtime, size), checkpoint(), replay() → List<WalEntry>
   WalEntry record: (WalOp op, Instant timestamp, String path, Instant mtime, long sizeBytes)
   WalOp: ADD=1, DELETE=2, UPDATE=3
   超过 WAL_MAX_SIZE 轮转

3. MemorySegment：
   ConcurrentHashMap<String, TermData> 存储倒排
   TermData: docIds(IntList) + termFreqs(IntList) + positions(Map<Integer, IntList>)
   方法：addDocument(int docId, List<Token> tokens), flush(File segmentDir) — 排序写入 dict/inv/pos 三文件
   并发：ReadWriteLock 保护 flush，addDocument 期间允许并发写

4. DiskSegment：
   构造：加载 .meta + 词典全量到内存 + 打开 .inv/.pos RandomAccessFile
   方法：getPostings(term), prefixSearch(prefix), getPositions(term), getPositionsForDoc(term, docId), markDeleted(docId), isDeleted(docId), getDocFreq(term)
   已删除 docId 用 ConcurrentHashMap.newKeySet() 惰性标记

5. IndexManager：
   编排全流程：FileCollector → producers → BlockingQueue → consumers → MemorySegment → flush → DiskSegment
   方法：buildIndex(sourcePaths), rebuild(sourcePaths), flushMemorySegment(), recoverFromWal(), getActiveSegments(), getStatus()
   segments.gen 文件记录活跃段列表（原子替换写入）
```

---

## Phase 3: 查询引擎

### Prompt 3.1 — Query DSL
```
实现自定义查询 DSL 的词法分析和语法解析。

1. QueryNode (sealed interface)：
   TermQuery(term), PrefixQuery(prefix), PhraseQuery(List<String> terms),
   BooleanQuery(BoolOp op, left, right), NotQuery(child),
   FieldQuery(field, value), RangeQuery(field, from, to), SortDirective(field)
   BoolOp: AND, OR

2. QueryLexer：
   输入字符串 → List<LexToken>
   TokenType: TERM, PHRASE, FIELD, RANGE_SEP, LPAREN, RPAREN, AND, OR, NOT, MINUS, SORT, STAR, EOF
   处理：双引号短语、field:value（识别 path/ext/size/mtime/type/sort）、.. 范围分隔、布尔关键字、*前缀

3. QueryParser（递归下降）：
   语法：
     query = clause { clause }（隐式 AND）
     clause = [AND|OR|NOT|-] expression
     expression = group | phrase | field_expr | prefix | term
     group = '(' orExpr ')'    ← 括号内支持 OR
     field_expr = FIELD (range | value)
   错误处理：QueryParseException 包含 position、queryString 和 suggestion，格式化输出带 ^ 指示位置

测试用例：简单词项、短语、前缀、隐式AND、显式AND、OR(括号内)、NOT、-排除、字段过滤、范围查询、sort指令、复杂组合、未闭合引号错误。
```

### Prompt 3.2 — 查询执行
```
1. BM25Scorer：
   构造：(int totalDocs, double avgDocLength, double k1=1.2, double b=0.75)
   方法：score(int tf, int df, int docLength), computeIDF(int df), scoreMultiTerms(int[] tfs, int[] dfs, int docLen)
   公式：IDF = ln((N-df+0.5)/(df+0.5)+1)，TF归一化 = tf*(k1+1)/(tf+k1*(1-b+b*|D|/avgDL))

2. SnippetGenerator：
   构造：(int contextChars=80, int maxSnippets=3)
   方法：generate(String content, Set<String> queryTerms, List<int[]> hitOffsets) → List<Snippet>
   Snippet record: (String text, int lineNumber, int offset, List<HighlightSpan> highlights)
   逻辑：定位命中 → ±contextChars 窗口 → 对齐词边界 → 合并重叠 → term 密度排序 → ANSI 高亮

3. QueryEngine：
   构造：(IndexManager indexManager)
   方法：search(String queryString, int limit) → SearchResult
   SearchResult record: (List<SearchHit> hits, int totalMatches, long elapsedMs, String query)
   SearchHit record: (Document document, double score, List<Snippet> snippets)
   执行：
   - 解析 AST → 遍历每个 DiskSegment → 递归 evaluateNode
   - TermQuery: 读 PostingList → 逐 doc BM25
   - PhraseQuery: 多 PostingList 求 docId 交集 → 位置验证 pos[i+1]==pos[i]+1
   - BooleanQuery(AND): 左右子树交集
   - BooleanQuery(OR): 并集
   - NotQuery: 排除集
   - FieldQuery/RangeQuery: 委托 DocumentTable SQL
   - 最终排序 (relevance/mtime/size) → Top-N → 生成 Snippet
```

---

## Phase 4: CLI

### Prompt 4.1
```
使用 picocli 实现 CLI 主命令 MainCommand：

顶层选项：--index-dir, --note-dir, --threads
子命令：
- index <path...>: 调用 IndexManager.buildIndex
- search "<query>" [--limit N] [--format text|json]: 调用 QueryEngine.search，text 格式打印路径/分数/snippet，json 格式用 Jackson 输出
- status: 调用 IndexManager.getStatus 打印统计
- rebuild <path...>: 调用 IndexManager.rebuild

main 方法：new CommandLine(new MainCommand()).execute(args)
用 emoji 美化输出（🔍 🔎 ✅ ❌ ⚠️ 📊）
logback.xml: 控制台 + 滚动文件(10MB/份, 7天保留, 100MB上限)
```

---

## Phase 5: 段合并与增量

### Prompt 5.1
```
在 IndexManager 中实现：

1. 段合并 (mergeSegments)：
   - 选择同层 ≥ MERGE_FACTOR (10) 个段
   - 多路归并：遍历所有段的 DictionaryReader.allTerms()，按字典序合并
   - 对每个 term 合并 PostingList（跳过 deletedDocIds）
   - 写入新段 → 更新 segments.gen → 标记旧段 DELETED → 清理文件

2. 增量更新 (incrementalUpdate)：
   - FileCollector 收集全部文件 → 与 DocumentTable 对比
   - mtime 或 size 变化 → WAL.appendUpdate → 删旧 + 重索引
   - 新文件 → WAL.appendAdd → 索引
   - 缺失文件 → WAL.appendDelete → 标记删除

3. 文件监控 (可选)：
   - WatchService 注册源目录
   - ENTRY_CREATE/MODIFY/DELETE → 去抖动(500ms) → 增量更新
```

---

## Phase 6: 测试与基准

### Prompt 6.1
```
补充测试：

1. 集成测试 IndexIntegrationTest：
   - setUp: 创建临时目录，写入 50 个测试文件（.md/.java/.txt，含中英文混合内容）
   - 测试全量索引 → search 命中 → 验证 snippet 包含查询词
   - 测试增量更新：修改文件 → 重索引 → 验证结果变化
   - 测试崩溃恢复：索引中途强制中断 → recoverFromWal → 验证数据一致
   - 测试字段过滤：ext:md, type:note, mtime 范围
   - 测试短语查询：验证位置相邻性

2. JMH 基准 IndexBenchmark：
   - indexThroughput: 测量 10K 文件/秒
   - queryLatency: 测量单次查询 P99

目标覆盖率 ≥ 80%。
```
