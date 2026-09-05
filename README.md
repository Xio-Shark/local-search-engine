# lse — 面向本地代码与技术文档的符号感知检索预筛器

基于 [tantivy](https://github.com/quickwit-oss/tantivy)（Rust 全文索引引擎）的高性能本地搜索引擎，针对本地代码仓库与技术文档深度优化。专为本地开发检索、终端 CLI 与本地 Agent / RAG 检索流水线设计。

- 🌲 **结构与符号感知证据切片**：告别机械死板的 512 字符固定 Chunking，按类/函数/章节语法闭包自闭合抽取，输出完整上下文、起止行与层级面包屑（相比固定 Chunking 节省 ~42% 上下文 Token）
- 🔤 **词级多流倒排索引 (Word-level BM25)**：代码标识符（驼峰/蛇形/类路径）解离 + Jieba CJK 词级多粒度展开真正写入倒排索引，彻底解决纯字元 `ngram(1,2)` 导致的 IDF 统计失效与排序失真
- 💾 **零存储（Zero-Storage）本地架构**：Tantivy 仅作为倒排与排序器，不存压缩正文副本，命中后零拷贝直读磁盘，索引体积显著缩减
- 🛡️ **语法自愈查询编译器**：自动补齐未闭合括号、修剪悬挂操作符、保留数字与版本号（如 `GPT-4o`, `C++17`），容错降级杜绝崩溃
- ⚡ **单趟流式 IO 与极速增量**：一次读取同时完成 BLAKE2b 哈希与文本解码；增量更新对未修改文件毫秒级短路，零无意义哈希重读
- 💻 **极简轻量**：纯 CLI，零后台常驻守护，跨平台二进制打包发布

---

## 快速开始

```bash
# 安装（Python 3.10+，推荐 uv 管理）
uv pip install -e .

# 1. 索引目标目录（自动跳过 .git/.venv/构建缓存与二进制产物）
lse index /path/to/docs

# 2. 高精度检索（毫秒级响应，输出结构化证据跨度）
lse search "本地搜索引擎 架构设计" --limit 10

# 3. 精确字段与范围过滤
lse search 'ext:md'                             # 仅 Markdown 文档
lse search 'filename:README.md'                 # 精确文件名
lse search 'type:code error AND retry'          # 代码文件布尔检索
lse search 'size:10KB..5MB sort:size:desc'      # 文件大小范围与原生排序
lse search 'mtime:2025-01-01..2025-12-31'       # 修改日期范围过滤

# 4. 增量更新 / 状态 / 重建
lse update /path/to/docs
lse status
lse rebuild --yes /path/to/docs
```

---

## 核心架构设计

### 1. 结构与符号感知证据切片 (Symbol-Aware Structural Spans)
传统检索往往面临两难：直接返回整篇数千行文档对 LLM 造成极大上下文浪费；机械切分为 512 字符固定 Chunk 则割裂跨段落或函数的上下文。
`lse` 在文档命中后，结合符号作用域与语法边界自闭合求解最佳证据区间，返回：
```text
1. architecture.md (score: 34.4034)
   [L1-L8 | 系统总体设计 > 倒排索引与符号感知 | 100% 证据共振]
   # 系统总体设计
   ## 1. 背景介绍
   本项目是一个面向高并发场景的本地检索系统。
   ## 2. 倒排索引与符号感知
   搜索引擎通过倒排索引映射关键词到文档。
   在语法自包含边界内动态求解证据区间，消灭固定的切块边界。
```

### 2. 词级代码与 CJK 双轨倒排体系
- **代码流 (Code Stream)**：深度分解 `camelCase`（`localSearchEngine` $\to$ `local`, `search`, `engine`）、`snake_case`、包路径与类名，同时保留基础字母语言（如 `C++` 解离出 `c`）。
- **自然语言流 (CJK Stream)**：借助 Jieba 词典与多粒度短语展开，将真实的语义词元写入 Tantivy 倒排索引，保留完整的 BM25 长度归一化与词级 IDF 权重区分度。

### 3. 语法自愈查询编译器
提供健壮的查询编译与容错降级：
- 自动平衡闭合括号（如 `(error OR timeout` $\to$ `( error OR timeout )`）。
- 自动清理悬挂操作符（如 `timeout AND` $\to$ `timeout`）。
- 容错降级机制：当 Tantivy 抛出语法异常时，自动平滑回退为安全转义查询，杜绝向终端抛出 Traceback。

### 4. 零存储架构与单趟流式 IO
- **零存储冗余**：Tantivy 索引内的 `content` 配置为 `stored=False`，正文只保留在本地磁盘，检索命中后按需直读，极大减少磁盘占用并保护操作系统 Page Cache。
- **单趟流式读取**：单次磁盘 IO 同时完成 BLAKE2b 16 字节内容指纹计算与文本解码；增量更新时，未修改文件直接复用元数据，完全跳过磁盘读取。

---

## 性能基准测试与消融实验 (Benchmark & Ablation)

测试环境：Apple M系列芯片 / 600 个混合代码与技术文档（约 300KB 真实代码片段），运行 `uv run python bench/bench_engine.py` 实测结果：

| 度量指标 | 实测数值 | 说明 |
| :--- | :--- | :--- |
| **全量构建吞吐** | **840+ docs/s** (~0.40 MB/s) | 600 个文档在 700ms 内完成全量索引构建与分词 |
| **增量更新（无变更）** | **~60 ms** | 单趟元数据比对短路，0 磁盘文本重读与 0 重复哈希计算 |
| **增量更新（局部变更）** | **~290 ms** | 仅重算变更文件并原子置换状态 |
| **查询延迟中位数 (p50)** | **0.79 ms** | 毫秒级极速响应 |
| **查询延迟 99 分位 (p99)** | **3.64 ms** | 极端复杂多词与布尔查询延迟 |
| **LLM 上下文 Token 节省率** | **42.0%** | 相比固定 512 字符 Chunking，自闭合语法切片大幅消减冗余上下文 |

---

## 与 RAG 系统集成

`lse` 原生支持作为本地 RAG 系统的 BM25 预筛器：

```python
from lse.searcher import SearchEngine

engine = SearchEngine(index_dir)
result = engine.search("架构设计", limit=50)

# 获取命中文件集合与连续证据段
for hit in result.hits:
    print(hit.path, hit.score)
    for span in hit.spans:
        print(f"[{span.start_line}-{span.end_line}] {span.breadcrumbs}: {span.text}")
```

---

## 查询语法 (Query DSL)

| 语法形态 | 示例 | 语义说明 |
| :--- | :--- | :--- |
| **自然语言短语** | `本地搜索引擎架构设计` | 自动提取短语并加权展开 |
| **精确短语** | `"distributed system"` | 严格词组顺序精确匹配 |
| **布尔组合** | `error AND (timeout OR retry)` | 括号优先级布尔组合，支持语法自愈 |
| **后缀过滤** | `ext:md` 或 `ext:py` | 仅检索指定文件类型 |
| **文件名匹配** | `filename:README.md` | 精确/不区分大小写文件名定位 |
| **文档类别** | `type:code` 或 `type:note` | 自动识别代码、文档、配置 |
| **容量范围** | `size:10KB..5MB` | 文件大小范围过滤 |
| **时间范围** | `mtime:2025-01-01..2025-12-31` | 修改日期区间过滤 |
| **原生排序** | `sort:mtime:desc` / `sort:size:asc` | 基于 Tantivy Fast-Field 原生极速排序 |

---

## 默认存储位置

| 平台 | 默认路径 |
|------|------|
| macOS | `~/Library/Application Support/lse/index/` |
| Windows | `%LOCALAPPDATA%\lse\index\` |
| Linux | `~/.local/share/lse/index/` |

*(可通过 `--index-dir` 或环境变量 `LSE_DATA_DIR` 自定义)*

---

## 项目结构

```
lse/
├── config.py         # 配置常量（文件类型白名单、排除规则、内存限制）
├── discovery.py      # 目录递归发现与文本文件识别
├── schema.py         # Tantivy 索引 Schema（Zero-Storage + 词级分词注册）
├── indexer.py        # 全量/增量/重建索引（单趟流式 IO + BLAKE2b 原子状态）
├── searcher.py       # 统一检索入口（语法自愈 + 零拷贝磁盘读取 + 证据提取）
├── tokenizer.py      # 代码与 CJK 词级多流分词体系（Jieba 词级切词 + 驼峰解离）
├── query_ast.py      # 查询词法分析器与括号平衡自愈编译器
├── resonance.py      # 符号与结构感知证据区间求解器
├── model.py          # 领域模型 (SearchHit, EvidenceSpan, IndexStatus)
├── store.py          # 索引目录管理门面
├── cli.py            # CLI 命令行入口
├── bench/            # 性能基准测试与消融实验套件 (bench_engine.py)
├── packaging/        # PyInstaller spec、打包脚本与 CI 发布流程
└── tests/            # pytest 完备自动化测试套件 (25 例 100% 通过)
```

---

## 自动化测试

```bash
uv run pytest tests/
```
25 例核心单元测试 100% 通过（涵盖分词解离、语法自愈、多层符号感知、单趟哈希短路、零存储检索、版本号检索、范围过滤及终端格式化输出）。
