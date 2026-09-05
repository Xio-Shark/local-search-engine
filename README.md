# lse — 现代高性能本地全文搜索引擎

基于 [tantivy](https://github.com/quickwit-oss/tantivy)（Rust 全文索引引擎）的高性能本地搜索引擎，融合**动态局部共振证据区间求解**、**代码/CJK双轨多流分词**与**形式化 AST 查询引擎**。专为本地知识库、代码仓库与 Agent/RAG 检索流水线设计。

- 🌊 **动态局部共振证据求解**：消灭固定死板切 Chunk，基于高斯能量波函数动态计算证据区间，输出起止行（如 `L45-L68`）、章节面包屑与共振置信度
- 🔤 **中英文与代码双轨多流分词**：Code Tokenizer（驼峰/蛇形标识符解离）+ CJK 多粒度语义词元展开，原生支持中英混排（如 `GPT-4o架构`、`C++多线程`）
- 🌲 **形式化 AST 查询引擎**：严谨递归下降语法分析器，支持嵌套括号、短语加权、字段过滤与长词自适应匹配，杜绝语法异常
- 📊 **BM25 相关性排序** + 命中词项精确高亮
- 🚀 **事务级增量与内容哈希**：基于 BLAKE2b 内容指纹与临时文件原子置换，彻底杜绝误伤与裂脑
- 🎨 **丰富字段过滤**：`ext:` / `filename:` / `type:` / `path:` / `size:` / `mtime:`
- 💻 **极简轻量**：纯 CLI，零后台常驻守护，打包产物 ~29MB（含 Tantivy 引擎）
- 🪟 **跨平台支持**：macOS (arm64/x86_64) + Windows (amd64)，GitHub Actions 矩阵自动构建发布

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

## 核心架构创新

### 1. 动态局部共振证据求解 (Dynamic Evidence Resonance Spans)
传统检索往往面临两难：直接返回整篇数千行文档对 LLM 造成极大上下文浪费；机械切分为 512 字符固定 Chunk 则割裂跨段落上下文。
`lse` 引入连续流形波函数：
$$\tilde{E}(i) = \sum_{k=-W}^{W} E(i+k) \cdot \exp\left(-\frac{k^2}{2\sigma^2}\right)$$
在行流形上求解查询词项的高斯密度极大值，自适应定位最佳证据区间，返回：
```text
1. architecture.md (score: 34.4034)
   [L1-L8 | 系统总体设计 > 2. 倒排索引与连续流形 | 100% 证据共振]
   # 系统总体设计
   ## 1. 背景介绍
   本项目是一个面向高并发场景的本地检索系统。
   ## 2. 倒排索引与连续流形
   搜索引擎通过倒排索引映射关键词到文档。
   在连续局部流形上，我们使用能量波函数动态求解证据区间，消灭固定的切块边界。
```

### 2. 代码与 CJK 双轨多流分词体系
- **代码流 (Code Stream)**：深度分解 `camelCase`（`localSearchEngine` $\to$ `local`, `search`, `engine`）、`snake_case`、包路径与类名。
- **自然语言流 (CJK Stream)**：消除全量字符 n-gram 产生的无语义碎片；针对长短语提供自适应提升与 2-gram / 1-gram 无损回退，中英文混排无缝检索。

### 3. 形式化 AST 查询引擎
采用完整的词法解析与递归下降 AST 编译器，严格解析字段表达式（`ext:`, `filename:`, `size:`, `mtime:`）与布尔树（`AND`, `OR`, `NOT`, `()`），避免传统正则替换带来的语法破坏与执行崩溃。

### 4. 事务级原子状态与内容指纹
- 计算文件的 BLAKE2b 16 字节内容哈希，Git 分支切换或无修改 `touch` 不会触发无效全量重写。
- 索引状态维护采用临时快照 + `os.replace` 原子置换，确保即使在断电或强制中断下也不会破坏 `state.json`。

---

## 与 RAG 系统集成

`lse` 原生支持作为本地 RAG 系统的 BM25 预筛器：

```bash
# RAG 配置 (.env)
LSE_ENABLED=true
LSE_INDEX_DIR=/path/to/.lse-index
```

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
| **布尔组合** | `error AND (timeout OR retry)` | 括号优先级布尔组合 |
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

## 打包分发

```bash
# 本地单目录打包
pip install pyinstaller
bash packaging/build_release.sh 0.2.0

# 产物：
# release/lse-macos-arm64-v0.2.0.tar.gz
# release/lse-windows-amd64-v0.2.0.zip
```

---

## 项目结构

```
lse/
├── config.py         # 配置常量（文件类型白名单、排除规则、内存限制）
├── discovery.py      # 目录递归发现与文本文件识别
├── schema.py         # Tantivy 索引 Schema 与 Tokenizer 注册
├── indexer.py        # 全量/增量/重建索引（原子状态 + BLAKE2b 哈希）
├── searcher.py       # 统一检索入口（AST 驱动 + 动态共振提取）
├── tokenizer.py      # 代码与 CJK 双轨多流分词体系
├── query_ast.py      # 形式化 AST 递归下降语法解析器与编译器
├── resonance.py      # 连续流形波函数证据区间求解器
├── model.py          # 领域模型 (SearchHit, EvidenceSpan, IndexStatus)
├── store.py          # 索引目录管理门面
├── cli.py            # CLI 命令行入口
├── packaging/        # PyInstaller spec、打包脚本与 CI 发布流程
└── tests/            # pytest 完备自动化测试套件
    ├── conftest.py
    ├── test_cli.py
    ├── test_indexer.py
    ├── test_query_ast.py
    ├── test_resonance.py
    ├── test_search.py
    └── test_tokenizer.py
```

---

## 自动化测试

```bash
uv run pytest tests/
```
20 例核心单元测试 100% 通过（涵盖分词解离、AST 编译、波函数共振、原子哈希更新、中英文与代码混合搜索、字段范围过滤及终端格式化输出）。
