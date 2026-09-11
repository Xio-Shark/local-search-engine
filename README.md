# lse — 面向本地代码与技术文档的符号感知检索预筛器

基于 [tantivy](https://github.com/quickwit-oss/tantivy)（Rust 全文索引引擎）的高性能本地搜索引擎，针对本地代码仓库与技术文档深度优化。专为本地开发检索、终端 CLI 与本地 Agent / RAG 检索流水线设计。

- 🌲 **结构与符号感知证据切片**：告别机械死板的 512 字符固定 Chunking，按类/函数/章节语法闭包自闭合抽取，输出完整上下文、起止行与层级面包屑（相比固定 Chunking 节省 ~42% 上下文 Token）
- 📦 **意图到上下文胶囊 (lse pack)**：搜索即 Prompt！按自然语言意图秒级定位核心语法块，就地自动吸附其内部调用的 1-hop 依赖符号声明（类/函数接口），在严格 Token 预算内压缩并一键注入剪贴板（`Cmd+V` 直达 AI）
- 🔤 **词级多流倒排索引 (Word-level BM25)**：代码标识符（驼峰/蛇形/类路径）解离 + Jieba CJK 词级多粒度展开真正写入倒排索引，彻底解决纯字元 `ngram(1,2)` 导致的 IDF 统计失效与排序失真
- 💾 **零存储（Zero-Storage）本地架构**：Tantivy 仅作为倒排与排序器，不存压缩正文副本，命中后零拷贝直读磁盘，索引体积显著缩减
- 🛡️ **自适应查询语义与语法自愈**：纯词项查询统一走与索引侧同分词器对齐、按 BM25 IDF 软加权的 OR（短查询 AND 阈值经四个公开 dev split 扫描后定为 0，见 [bench/PUBLIC_EVAL.md](bench/PUBLIC_EVAL.md)）。代码片段会绕过 Query DSL 判定，避免字符串引号 / dict `name:` 被误解析。字段过滤、显式布尔、短语、排序等结构化语法仍走 AST。自动补齐未闭合括号、修剪悬挂操作符，杜绝脱靶与崩溃
- ⚡ **rank-only 预筛模式**：`SearchOptions(include_spans=False)` 只返回排序元数据（`path/filename/extension/size/mtime/score`），不读正文、不算 evidence span，为 Agent 预筛与 rerank 召回提供与原生 BM25 同口径的延迟
- ⚡ **单趟流式 IO 与极速增量**：一次读取同时完成 BLAKE2b 哈希与文本解码；增量更新对未修改文件毫秒级短路，零无意义哈希重读
- 💻 **极简轻量**：纯 CLI，零后台常驻守护，跨平台二进制打包发布

---

## 快速开始

```bash
# 安装（Python 3.10+，推荐 uv 管理）
uv pip install -e .

# 1. 索引目标代码库或文档目录
lse index /path/to/project

# 2. 🎯 一键生成 AI 上下文胶囊（搜索 + 语法切片 + 1-hop 依赖吸附 + 写入剪贴板）
lse pack "authenticate_jwt_request Bearer" --budget 1500 -c
# 终端提示：📋 已成功拷贝上下文胶囊到系统剪贴板！直接去 AI 窗口 Cmd+V 粘贴即可。

# 3. 常规高精度检索（毫秒级响应，输出结构化证据跨度）
lse search "本地搜索引擎 架构设计" --limit 10

# 4. 精确字段与范围过滤
lse search 'ext:md'                             # 仅 Markdown 文档
lse search 'filename:README.md'                 # 精确文件名
lse search 'type:code error AND retry'          # 代码文件布尔检索
lse search 'size:10KB..5MB sort:size:desc'      # 文件大小范围与原生排序
lse search 'mtime:2025-01-01..2025-12-31'       # 修改日期范围过滤

# 5. 增量更新 / 实时监听 / 状态 / 重建
lse update /path/to/project
lse watch /path/to/project                      # 实时监听文件系统变动（FSEvents/inotify），文件修改自动增量同步
lse status
lse rebuild --yes /path/to/project
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

## 性能与检索质量基准测试 (Benchmarks)

### 1. 引擎底层性能消融（吞吐与延迟）
运行 `uv run python bench/bench_engine.py`（脚本自建 600 个混合代码/文档，约 300KB）。

> 以下为本机回归参考值（Apple Silicon，`uv` 环境），会随硬件与并发状态波动；请以本机实际输出为准。

| 度量指标 | 实测数值 | 说明 |
| :--- | :--- | :--- |
| **全量构建吞吐** | **~4,500 docs/s (~2.1 MB/s)** | 600 个文档约 130ms 完成全量索引构建与词级多流分词 |
| **增量更新（无变更）** | **~49 ms** | 单趟元数据比对短路，0 磁盘文本重读与 0 重复哈希计算 |
| **增量更新（局部变更）** | **~100 ms** | 仅重算变更文件并原子置换状态 |
| **查询延迟中位数 (p50)** | **~1.6 ms** | 毫秒级响应 |
| **查询延迟 99 分位 (p99)** | **~3.6 ms** | 复杂多词与布尔查询延迟 |
| **LLM 上下文 Token 节省率** | **42.0%** | 相比固定 512 字符 Chunking，自闭合语法切片大幅消减冗余上下文 |

### 2. 内置合成代码库 IR 冒烟评测
运行 `python bench/bench_ir_quality.py`：脚本在临时目录生成一个 10 文件的微服务风格合成代码库，并使用 12 组人工构造查询。该评测用于**回归与冒烟验证**，不等同于第三方 IR 基准。

| IR 质量度量 | 实测数值 | 说明（合成集内） |
| :--- | :--- | :--- |
| **Hit@1 准确率** | **91.7%** (11/12) | 引入双向技术概念投影后，跨语言自然语言意图直达英文代码符号，首位召回大幅跃升 |
| **Hit@3 准确率** | **100.0%** (12/12) | 100% 召回，自适应 BM25 容错与概念增强机制下全部核心目标文件进入 Top-3 |
| **MRR (平均倒数排名)** | **0.958** | 严格量化倒数排序位置；注意该集由本脚本生成 |
| **严格跨文件 1-Hop 依赖反查召回** | **100.0%** (5组有效) | 静态导入精准直达 + 类方法级推导，跨文件依赖反查达 100% 还原 |
| **胶囊完整上下文符号覆盖率** | **100.0%** (10组有效) | 包含同文件未在 Anchor 内的定义反查与跨文件调用完整闭环 |
| **胶囊端到端生成延迟 (p50)** | **4.6 ms** | 涵盖倒排检索 + AST 闭包切片 + 批量依赖反查 + 接口存根化与预算压包全流程 |
| **胶囊端到端生成延迟 (p95)** | **20.4 ms** | 合成集上的端到端冒烟数值 |

> 注意：上述语料与 Gold Query 均由 benchmark 脚本自行生成，存在过拟合和关键词重叠风险，**不能作为对外泛化能力证明**；第三方公开数据集评测见下一节。


### 3. 第三方公开数据集评测

已接入 BEIR / SciFact（5,183 篇摘要）与 CoIR / CosQA（20,604 条 Python 代码），
对比 lse、原生 Tantivy BM25 与 ripgrep term-count。调参只在 dev split
（SciFact `qrels/train.tsv` 809 条、CosQA `data/valid` 500 条）进行，
test split 只用于最终报告；最终结果使用 `--deterministic-index` 固定索引
布局，并用 paired bootstrap 检查显著性。

```bash
# dev 消融（SciFact / CosQA 二选一）
uv run python bench/bench_ablation.py --dataset scifact --qrels-split train \
  --include-tantivy --deterministic-index

# 最终 test 报告（含 paired bootstrap）
uv run python bench/bench_public.py \
  --dataset scifact --baselines lse,tantivy,ripgrep \
  --deterministic-index --bootstrap-samples 5000

uv run --extra eval python bench/bench_public.py \
  --dataset cosqa --baselines lse,tantivy,ripgrep \
  --deterministic-index --bootstrap-samples 5000

# CodeSearchNet-Python 固定种子采样：20k docs / 2k queries
uv run --extra eval python bench/bench_public.py \
  --dataset codesearchnet-python \
  --sample-docs 20000 --sample-queries 2000 --seed 42 \
  --baselines lse,tantivy \
  --deterministic-index --repeat 3 --bootstrap-samples 5000

# BEIR 泛化补跑（数据集级并行：--dataset a,b,c --jobs N）
uv run python bench/bench_public.py \
  --dataset nfcorpus,fiqa,arguana --jobs 3 --baselines lse,tantivy \
  --lse-rank-only --deterministic-index --bootstrap-samples 5000 \
  --output-json "bench/results/{dataset}-rank-only.json"
```

| 数据集 / split | Baseline | nDCG@10 | Recall@10 | MRR@10 | full p50 | rank-only p50 |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: |
| SciFact test (300 q) | **lse（默认）** | **0.6492** | **0.7955** | **0.6074** | 19.99 ms | 0.69 ms |
| SciFact test (300 q) | native Tantivy BM25 | 0.6232 | 0.7508 | 0.5886 | 0.15 ms | 0.15 ms |
| SciFact test (300 q) | ripgrep term-count | 0.0477 | 0.1025 | 0.0311 | 84.32 ms | — |
| CosQA test (500 q) | **lse（默认）** | **0.1505** | 0.2980 | **0.1073** | 10.93 ms | 0.69 ms |
| CosQA test (500 q) | native Tantivy BM25 | 0.1481 | 0.2900 | 0.1063 | 0.13 ms | 0.13 ms |
| CodeSearchNet-Python sample (2,000 q) | lse（默认） | 0.9451 | **0.9805** | 0.9336 | 32.14 ms | 1.13 ms |
| CodeSearchNet-Python sample (2,000 q) | native Tantivy BM25 | **0.9453** | 0.9750 | **0.9355** | 0.47 ms | 0.47 ms |

- **SciFact**：lse 相比原生 BM25 nDCG@10 **+0.0260**，paired bootstrap
  95% CI [+0.0006, +0.0518]，仍为小但显著的提升；相比上一版 lse（0.5682）
  提升 **+0.0810**。
- **CosQA**：lse 相比原生 BM25 nDCG@10 **+0.0025**，95% CI
  [-0.0087, +0.0136] 跨 0，**不能宣称统计显著超越**。
- **CodeSearchNet-Python 采样**：lse vs native BM25 mean diff **-0.0002**，
  95% CI [-0.0059, +0.0056] 跨 0；代码检索结论为“持平/未确认”，
  **不能宣称 lse 在代码检索上领先**。下一步先查 tokenizer / IDF /
  字段权重，而不是直接上 reranker 或向量检索。
- `SearchOptions(include_spans=False)` 提供明确拆分的 rank-only 口径：
  三个数据集上排序结果 / nDCG 与 full 模式完全相同，rank-only p50 为
  0.69 / 0.69 / 1.13 ms；full p50 则包含正文读取与 evidence span 切片，
  是 Agent 拿上下文时的真实成本。

**BEIR 泛化补跑（短查询 AND 阈值改为 0 之后，默认 auto + IDF^0.25）**：

| 数据集（test） | lse nDCG@10 | native BM25 | mean diff | 95% CI |
| :--- | ---: | ---: | ---: | ---: |
| NFCorpus（323 q） | **0.3061** | 0.2994 | +0.0067 | [-0.0022, +0.0160] |
| FiQA（648 q） | 0.2297 | **0.2336** | -0.0039 | [-0.0119, +0.0040] |
| Arguana（1,406 q） | 0.3097 | **0.3152** | -0.0055 | [-0.0122, +0.0009] |

短查询阈值由 `bench/bench_query_policy.py` 在 SciFact train / NFCorpus train /
FiQA train / CosQA valid 四个 dev split 上扫描得到：0（纯词项查询一律 OR）在
四个数据集上全部最优或并列最优，任何 >0 的阈值都只会在 NFCorpus 上掉分。
切换后 NFCorpus 从 -0.0110 翻正到 +0.0067，FiQA 从 -0.0054 收到 -0.0039，
Arguana 不变；五个 test 数据集中 SciFact（+0.0260，CI 不跨 0）、NFCorpus
（+0.0067）、CosQA（+0.0025）点估计为正，FiQA / Arguana 仍为小幅负值但
CI 跨 0。**没有数据集再出现显著负 gap，但也不足以宣称通用 / 代码检索领先。**

残余负 gap 已按 §2.4 的旋钮诊断定位：概念展开与查询字段逐位无影响，
唯一有效的是 IDF 幂次，且最优值随 query 形态变化——Arguana（全部 >160
字符的长论据 query）用 `IDF^1.0` 可把 gap 从 -0.0055 翻正到 +0.0017，
四个 dev split 则一致支持当前的 `0.25`。因此这是打分权重的 profile 问题，
不是缺少 reranker / tree-sitter 能力；长度自适应 IDF 需要带 train split
的长 query 数据集才能验证，本轮不改默认值。

完整消融、缓存 / 延迟对比、统计方法、复现命令与原始 JSON 见
[bench/PUBLIC_EVAL.md](bench/PUBLIC_EVAL.md)。

---

## 与 RAG 系统集成

`lse` 原生支持作为本地 RAG 系统的 BM25 预筛器：

```python
from lse.options import SearchOptions
from lse.searcher import SearchEngine

engine = SearchEngine(index_dir)

# Agent 预筛 / rerank 召回：只排序，不读正文、不算 evidence span
screened = engine.search(
    "架构设计",
    limit=50,
    options=SearchOptions(include_spans=False),
)
print([(hit.path, hit.score) for hit in screened.hits])

# 需要给 LLM 上下文时再用 full 模式取证据段
result = engine.search("架构设计", limit=10)
for hit in result.hits:
    for span in hit.spans:
        print(f"[{span.start_line}-{span.end_line}] {span.breadcrumbs}: {span.text}")
```

---

## 查询语法 (Query DSL)

| 语法形态 | 示例 | 语义说明 |
| :--- | :--- | :--- |
| **短关键词** | `error timeout retry` | 与索引对齐分词 + IDF 软加权 OR（dev split 扫描证明短查询 AND 在四个数据集上均不占优） |
| **自然语言意图** | `本地搜索引擎架构设计` | 自动切换为索引对齐分词 + BM25 IDF 软加权 OR |
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
├── options.py        # SearchOptions（auto/natural/structured、IDF 权重、字段选择、include_spans）
├── searcher.py       # 统一检索入口（自然查询重写 + 代码片段识别 + rank-only 快速路径 + 证据提取）
├── packer.py         # 🎯 意图到上下文胶囊打包器（AST 闭包 + 1-hop 依赖吸附 + 预算控制 + 剪贴板）
├── tokenizer.py      # 代码与 CJK 词级多流分词体系（Jieba 词级切词 + 驼峰解离）
├── query_ast.py      # 查询词法分析器与括号平衡自愈编译器
├── resonance.py      # 符号与结构感知证据区间求解器
├── model.py          # 领域模型 (SearchHit, EvidenceSpan, IndexStatus)
├── cli.py            # CLI 命令行入口（index / update / search / pack / status / rebuild / watch）
├── bench/            # 吞吐 / IR 评测、公开数据集评测 (bench_public.py) 与 query 消融 (bench_ablation.py)
├── packaging/        # PyInstaller spec、打包脚本与 CI 发布流程
└── tests/            # pytest 自动化测试套件 (60 例 100% 通过)
```

---

## 自动化测试

```bash
uv run pytest tests/
```
66 例核心单元测试 100% 通过（涵盖分词解离、语法自愈、多层符号感知、静态导入依赖解析、同文件 Intra-file 反查、单趟哈希短路、零存储检索、版本号检索、ContextPacker 依赖解析、Token 预算压包、多语言接口存根化、双向概念投影、Rust/Go 静态导入、相邻跨度融合与剪贴板容错）。

