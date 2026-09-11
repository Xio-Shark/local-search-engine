# 第三方公开数据集评测

本文件记录 lse 在公开检索数据集上的可复现评测。所有数字来自本机运行，
脚本、原始 JSON 与命令均已入库；不同机器 / CPU 调度可能造成小幅波动。
`--deterministic-index` 固定索引 writer 单线程，用于消除 segment 布局与
并列排序造成的运行间抖动；`--repeat N` 会重复评测并输出 mean ± std。

## 1. 数据集与划分

| 数据集 | 语料 | dev split（只用于调参） | test split（只用于最终报告） | 指标 |
| :--- | ---: | :--- | :--- | :--- |
| BEIR / SciFact | 5,183 篇摘要 | `qrels/train.tsv`，809 条 | `qrels/test.tsv`，300 条 | nDCG@10 / Recall@10 / MRR@10，深度 100 |
| CoIR / CosQA | 20,604 条 Python 代码 | `data/valid`，500 条 | `data/test`，500 条 | 同上 |

SciFact train / test qrels 只有 1 条 query 重叠；CoIR CosQA 使用官方
valid / test 划分。默认参数（`query_mode=auto` + `IDF^0.25`）只在 dev split
上选择，随后原样跑 test split，避免在最终报告集上调参。

Baseline：

- **native Tantivy BM25**：默认 analyzer、`title` + `body` 字段、OR 解析、
  原生 BM25 打分（Tantivy 0.26）。
- **ripgrep term-count**：按查询词在文件中的出现次数排序，case-insensitive。
- **lse**：Tantivy 之上的分词 / 查询编译层。

## 2. Query-level 消融（dev split）

### 2.1 SciFact train（809 q）

```bash
uv run python bench/bench_ablation.py \
  --dataset scifact --qrels-split train --include-tantivy --deterministic-index \
  --output-json bench/results/ablation-scifact-train.json
```

| 变体 | nDCG@10 | Recall@10 | MRR@10 | p50 | total |
| :--- | ---: | ---: | ---: | ---: | ---: |
| native Tantivy BM25 | 0.6279 | 0.7460 | 0.5982 | 0.27 ms | 0.23 s |
| `structured_and`（旧默认：AST + AND + 概念展开） | 0.5958 | 0.7130 | 0.5650 | 43.4 ms | 35.7 s |
| `structured_or`（旧 AST，仅默认连接改 OR） | 0.6081 | 0.7299 | 0.5759 | 45.9 ms | 39.3 s |
| `natural_or`（索引对齐分词 + OR，无 IDF 权重） | 0.6425 | 0.7783 | 0.6063 | 49.2 ms | 42.5 s |
| `natural_idf010`（IDF^0.10） | 0.6465 | 0.7849 | 0.6089 | 41.5 ms | 34.9 s |
| **`natural_idf025`（IDF^0.25，当前 dev 最优）** | **0.6487** | **0.7895** | **0.6098** | 32.7 ms | 28.0 s |
| `natural_idf050`（IDF^0.50） | 0.6441 | 0.7827 | 0.6052 | 36.1 ms | 30.8 s |
| `natural_idf025_content`（仅 content 字段） | 0.6487 | 0.7895 | 0.6098 | 36.4 ms | 31.1 s |
| `natural_idf025_noconcept`（关闭概念展开） | 0.6487 | 0.7895 | 0.6098 | 35.9 ms | 30.5 s |

结论：

1. 旧默认 `conjunction_by_default=True` 是 SciFact 上的主要硬伤：词项必须
   全部命中，recall 直接损失约 9 个点。
2. 仅把 AND 改成 OR 还不够（0.6081）；把 query 用索引侧同一套
   `tokenize_stream` 重写，能修复 query parser analyzer 与索引 analyzer
   的词项错配，再涨到 0.6425。
3. 在自然查询上对每个词项乘 `IDF^p` 软权重，`p=0.25` 在 dev 上最优。
4. SciFact 上 `filename` / `path` 不贡献检索信号，概念展开也未命中查询词；
   保留为可配置项，服务于本地代码检索。

### 2.2 CosQA valid（500 q）

```bash
uv run --extra eval python bench/bench_ablation.py \
  --dataset cosqa --qrels-split valid \
  --variants structured_and,structured_or,natural_or,natural_idf025,natural_idf050 \
  --deterministic-index \
  --output-json bench/results/ablation-cosqa-valid.json

# native BM25 dev baseline
uv run --extra eval python bench/bench_public.py \
  --dataset cosqa --qrels-split valid --baselines tantivy \
  --deterministic-index --bootstrap-samples 0 \
  --output-json bench/results/cosqa-valid-tantivy.json
```

| 变体 | nDCG@10 | Recall@10 | MRR@10 | p50 | total |
| :--- | ---: | ---: | ---: | ---: | ---: |
| native Tantivy BM25 | 0.1426 | 0.3100 | 0.0937 | 0.14 ms | 0.07 s |
| `structured_and`（旧默认） | 0.1422 | 0.3080 | 0.0938 | 12.2 ms | 6.1 s |
| `structured_or` | 0.1463 | 0.3140 | 0.0973 | 13.0 ms | 6.7 s |
| `natural_or` | 0.1448 | 0.3140 | 0.0954 | 12.9 ms | 6.6 s |
| **`natural_idf025`（当前默认）** | **0.1473** | 0.3080 | **0.1003** | 12.9 ms | 6.6 s |
| `natural_idf050` | 0.1408 | 0.2900 | 0.0967 | 12.7 ms | 6.5 s |

CosQA 每个 query 只有 1 条相关文档，大量 query 的 nDCG@10 由并列排序决定。
dev 上 `natural_idf025` 最优，但领先幅度只有 0.005 左右，因此最终 test 需要
paired bootstrap 判断是否显著。

## 3. 最终 test split 结果

### 3.1 SciFact test（300 q）

```bash
uv run python bench/bench_public.py \
  --dataset scifact --baselines lse,tantivy,ripgrep \
  --deterministic-index --bootstrap-samples 5000 \
  --output-json bench/results/scifact.json
```

| Baseline | nDCG@10 | Recall@10 | MRR@10 | p50 latency | total time |
| :--- | ---: | ---: | ---: | ---: | ---: |
| **lse（默认）** | **0.6492** | **0.7955** | **0.6074** | 20.3 ms | 6.6 s |
| native Tantivy BM25 | 0.6199 | 0.7474 | 0.5852 | 0.17 ms | 0.05 s |
| ripgrep term-count | 0.0477 | 0.1025 | 0.0311 | 82.4 ms | 24.9 s |

paired bootstrap（nDCG@10，5000 次重采样）：

- lse vs native BM25：mean diff **+0.0293**，95% CI **[+0.0042, +0.0553]**，
  W/L/T = 67/50/183。
- lse vs ripgrep：mean diff **+0.6015**，95% CI [+0.5577, +0.6459]。

`--repeat 3 --deterministic-index` 下 lse / native nDCG@10 的 std 均为 0.0，
结果稳定。SciFact 相比上一版 lse（0.5682）提升 **+0.0810**。

### 3.2 CoIR / CosQA test（500 q）

```bash
uv run --extra eval python bench/bench_public.py \
  --dataset cosqa --baselines lse,tantivy,ripgrep \
  --deterministic-index --bootstrap-samples 5000 \
  --output-json bench/results/cosqa.json
```

| Baseline | nDCG@10 | Recall@10 | MRR@10 | p50 latency | total time |
| :--- | ---: | ---: | ---: | ---: | ---: |
| **lse（默认）** | **0.1505** | 0.2980 | **0.1073** | 11.8 ms | 6.1 s |
| native Tantivy BM25 | 0.1474 | 0.2880 | 0.1060 | 0.16 ms | 0.08 s |
| ripgrep term-count | 0.0185 | 0.0400 | 0.0121 | 388.2 ms | 197.4 s |

paired bootstrap（nDCG@10，5000 次重采样）：

- lse vs native BM25：mean diff **+0.0031**，95% CI **[-0.0081, +0.0142]**，
  W/L/T = 29/26/445。

**结论要诚实**：在 deterministic 且可复现的口径下，CosQA 上 lse 仅比原生
BM25 高约 0.003，95% CI 跨 0，**不能宣称统计显著超越**；上一轮非确定性
运行（索引 segment 布局不同）曾出现 lse 0.1700 / native 0.1578，但该差异
对并列排序高度敏感，不应作为最终结论。需要 CodeSearchNet / 更大测试集
或多次运行均值来进一步判断。

## 4. 延迟：概念图缓存（P0）与 evidence span 成本

profiling（SciFact，`limit=10`）显示旧实现每个 query 都执行
`load_project_concepts()`：JSON parse + `merge_concept_maps(base, dynamic)`，
占单次搜索延迟的 **83%**。benchmark 临时路径还会挖出巨大噪声概念图。

| 指标 | 修复前 | 修复后 |
| :--- | ---: | ---: |
| 动态概念图条目 | 10,373 keys / 41,492 邻居 / 1.09 MB | 上限 2,048 keys |
| 合并后概念图 | 每次搜索重新 parse + merge | mtime/size keyed LRU |
| `load_project_concepts` | 8.8 ms/次 | 首次 1.2 ms，缓存命中 0.011 ms |
| `search(limit=10)` p50 | 11.5 ms | **2.15 ms** |
| `search(limit=100)` p50 | 29.0 ms | **19.9 ms** |
| SciFact public benchmark lse p50 | 29.2 ms | **20.3 ms** |
| CosQA public benchmark lse p50 | 74.4 ms | **11.8 ms** |

剩余延迟主要是命中后读取正文、计算 evidence span / snippet；纯
`compile + parse + rank` p50 实测约 **0.14 ms**。后续可增加
`include_spans=False` 的 rank-only 模式，让 Agent 预筛和 benchmark 使用
与原生 BM25 同口径的排序延迟。

## 5. 实现摘要

当前默认查询策略（`lse.options.SearchOptions`）：

1. **auto 查询模式**：短关键词查询（≤ 3 个内容词元、无句末标点）→ 结构化
   AND，保留文件搜索精度；长句 / claim → 用索引侧同一套 `tokenize_stream`
   分词，编译成字段内 OR-of-terms，并按 `IDF^0.25` 加权。
2. **结构化语法**（`ext:py`、`filename:...`、大写 `AND/OR/NOT`、引号短语、
   `sort:...`、`*`）→ 走 AST 查询编译器，默认 AND。
3. **CJK / 中西混排** → 保留分组语义，例如 `目录A` 编译为 `目录 AND a`。
4. **概念图缓存**：合并后的概念图按 `(path, mtime_ns, size)` LRU 缓存，
   索引更新自动失效；`AdaptiveConceptMiner` 默认限制动态图 2,048 条。
5. **benchmark 可复现性**：`--deterministic-index`、`--repeat N`、
   per-query JSON、paired bootstrap（`--bootstrap-samples` / `--bootstrap-metric`）。

## 6. 已知边界

1. CosQA / tie-heavy 数据集上 lse 相对原生 BM25 的领先很小且不显著；
   不应把 SciFact 的结论直接外推到代码检索。
2. lse p50 仍高于原生 BM25，因为包含正文读取 + evidence span；排序本身
   已是亚毫秒级。
3. CodeSearchNet 全量尚未运行：python split 约 280,310 docs / 280,652
   queries，需要流式 parquet 或固定种子采样子集；当前 file materialize
   路线会产生 28 万小文件。
4. tree-sitter 多语言符号解析尚未接入，符号闭包仍以正则 / AST 混合实现。
5. evidence span 目前只用于展示，不参与排序；所有质量提升来自查询编译层。
