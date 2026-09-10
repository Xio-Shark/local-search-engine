# 第三方公开数据集评测

本文件记录 lse 在公开检索数据集上的可复现评测。所有数字来自本机单次运行，
脚本、原始 JSON 与命令均已入库；不同机器 / CPU 调度可能造成小幅波动。

## 1. 数据集与划分

| 数据集 | 语料 | dev split（只用于调参） | test split（只用于最终报告） | 指标 |
| :--- | ---: | :--- | :--- | :--- |
| BEIR / SciFact | 5,183 篇摘要 | `qrels/train.tsv`，809 条 | `qrels/test.tsv`，300 条 | nDCG@10 / Recall@10 / MRR@10，检索深度 100 |
| CoIR / CosQA | 20,604 条 Python 代码 | `data/valid`，500 条 | `data/test`，500 条 | 同上 |

SciFact 的 train / test qrels 只有 1 条 query 重叠；CoIR CosQA 使用官方
valid / test 划分。默认参数（自然查询重写 + IDF^0.25）只在 dev split 上选择，
然后用同一套默认参数跑 test split，避免在最终报告集上调参。

Baseline：

- **native Tantivy BM25**：默认 analyzer、`title` + `body` 字段、OR 解析、
  原生 BM25 打分（0.26）。
- **ripgrep term-count**：按查询词在文件中出现次数排序，case-insensitive。
- **lse**：Tantivy 之上的查询编译 / 分词层；默认 `natural_query=True`、
  `idf_power=0.25`、`content,filename,path` 三字段。

评测协议、下载与语料物化逻辑见 `bench/bench_public.py`；调参 harness 见
`bench/bench_ablation.py`。

## 2. Query-level 消融（dev split）

### 2.1 SciFact train（809 q）

```bash
uv run python bench/bench_ablation.py \
  --dataset scifact --qrels-split train --include-tantivy \
  --output-json bench/results/ablation-scifact-train.json
```

| 变体 | nDCG@10 | Recall@10 | MRR@10 | p50 | total |
| :--- | ---: | ---: | ---: | ---: | ---: |
| native Tantivy BM25 | 0.6279 | 0.7460 | 0.5982 | 0.47 ms | 0.43 s |
| `structured_and`（旧默认：AST + AND + 概念展开） | 0.5958 | 0.7130 | 0.5650 | 93.5 ms | 74.1 s |
| `structured_or`（旧 AST，仅把默认连接改为 OR） | 0.6082 | 0.7299 | 0.5760 | 54.2 ms | 45.4 s |
| `natural_or`（索引对齐分词 + OR，无 IDF 权重） | 0.6425 | 0.7783 | 0.6063 | 49.3 ms | 41.2 s |
| `natural_idf010`（IDF^0.10） | 0.6465 | 0.7849 | 0.6089 | 46.5 ms | 39.0 s |
| **`natural_idf025`（IDF^0.25，当前默认）** | **0.6487** | **0.7895** | **0.6098** | 47.1 ms | 39.3 s |
| `natural_idf050`（IDF^0.50） | 0.6441 | 0.7827 | 0.6052 | 38.5 ms | 32.2 s |
| `natural_idf025_content`（仅 content 字段） | 0.6487 | 0.7895 | 0.6098 | 34.7 ms | 28.9 s |
| `natural_idf025_noconcept`（关闭概念展开） | 0.6487 | 0.7895 | 0.6098 | 37.2 ms | 31.2 s |

结论：

1. 旧默认 `conjunction_by_default=True` 是 SciFact 上的主要硬伤：词项必须全部
   命中，recall 直接损失约 9 个点。
2. 仅把 AND 改成 OR 还不够（0.6082）；把 query 用与索引侧一致的
   `tokenize_stream` 重写，能修复 query parser analyzer 与索引 analyzer 的
   词项错配，再涨到 0.6425。
3. 在自然查询上对每个词项乘以 `IDF^p` 的软权重，`p=0.25` 在 dev 上最优，
   相比无权重版本再涨约 0.006 nDCG。
4. SciFact 上 `filename` / `path` 不贡献检索信号，概念展开也未命中查询词，
   因此这两个开关在该数据集上无差异；保留为可配置项，服务于本地代码检索。

### 2.2 CosQA valid（500 q）

```bash
uv run --extra eval python bench/bench_ablation.py \
  --dataset cosqa --qrels-split valid \
  --variants structured_and,structured_or,natural_or,natural_idf025,natural_idf050 \
  --output-json bench/results/ablation-cosqa-valid.json
```

| 变体 | nDCG@10 | Recall@10 | MRR@10 | p50 | total |
| :--- | ---: | ---: | ---: | ---: | ---: |
| native Tantivy BM25 | 0.1586 | 0.3260 | 0.1088 | 0.23 ms | 0.12 s |
| `structured_and`（旧默认） | 0.1695 | 0.3320 | 0.1213 | 97.3 ms | 47.5 s |
| `structured_or` | 0.1732 | 0.3200 | 0.1290 | 96.8 ms | 46.6 s |
| `natural_or` | 0.1703 | 0.3320 | 0.1222 | 96.7 ms | 46.6 s |
| **`natural_idf025`（当前默认）** | **0.1742** | **0.3340** | 0.1264 | 99.0 ms | 48.8 s |
| `natural_idf050` | 0.1714 | 0.3240 | 0.1256 | 97.4 ms | 48.3 s |

CosQA 上代码标识符解离本身已带来收益；自然查询重写 + IDF^0.25 在 dev 上
进一步小幅领先，选择该参数后进入 test。

## 3. 最终 test split 结果

### 3.1 BEIR / SciFact test（300 q）

```bash
uv run python bench/bench_public.py \
  --dataset scifact --baselines lse,tantivy,ripgrep \
  --output-json bench/results/scifact.json
```

| Baseline | nDCG@10 | Recall@10 | MRR@10 | p50 latency | total time |
| :--- | ---: | ---: | ---: | ---: | ---: |
| **lse（默认）** | **0.6492** | **0.7955** | **0.6074** | 29.2 ms | 9.1 s |
| native Tantivy BM25 | 0.6199 | 0.7474 | 0.5852 | 0.16 ms | 0.05 s |
| ripgrep term-count | 0.0477 | 0.1025 | 0.0311 | 82.4 ms | 24.3 s |

lse 相比原生 BM25 nDCG@10 提升 **+0.0293（相对 +4.7%）**，Recall@10
提升 **+0.0481**；相比上一版 lse（0.5682）提升 **+0.0810**。

### 3.2 CoIR / CosQA test（500 q）

```bash
uv run --extra eval python bench/bench_public.py \
  --dataset cosqa --baselines lse,tantivy,ripgrep \
  --output-json bench/results/cosqa.json
```

| Baseline | nDCG@10 | Recall@10 | MRR@10 | p50 latency | total time |
| :--- | ---: | ---: | ---: | ---: | ---: |
| **lse（默认）** | **0.1700** | **0.3180** | **0.1260** | 74.4 ms | 37.7 s |
| native Tantivy BM25 | 0.1578 | 0.3120 | 0.1115 | 0.17 ms | 0.10 s |
| ripgrep term-count | 0.0185 | 0.0400 | 0.0121 | 417.9 ms | 211.6 s |

lse nDCG@10 提升 **+0.0122（相对 +7.7%）**。CosQA 每个 query 只有 1 条
相关文档，nDCG@10 单次运行受并列排序影响，波动约 ±0.005；lse 在
valid / test 两个 split 上均稳定领先。

## 4. 实现摘要

当前默认查询策略（`lse.options.SearchOptions`）：

1. **纯词项自然语言查询**（无字段过滤、引号短语、大写布尔操作符、排序、
   通配符）→ 用索引侧同一套 `tokenize_stream` 分词，编译成字段内的
   OR-of-terms；每个词项按 `IDF^0.25` 加权。
2. **结构化查询**（`ext:py`、`filename:...`、`error AND (timeout OR retry)`、
   引号短语、`sort:...`、`*`）→ 走原有 AST 查询编译器，默认仍为 AND 语义。
3. **CJK / 中西混排词项** → 保留分组语义，例如 `目录A` 编译为
   `目录 AND a`，不会被拆成 OR 后召回 `目录B`。
4. 所有开关均可在 `SearchOptions` / `bench_public.py` CLI 上关闭，
   用于回归与消融。

## 5. 已知边界

1. lse p50 延迟仍显著高于原生 BM25：差距主要来自命中后读取正文、计算
   evidence span / snippet；纯倒排查询与排序本身是亚毫秒级。后续可改为
   按行范围读取与 AST/符号解析缓存。
2. 本评测尚未包含 CodeSearchNet 全量（python split 约 280,310 docs /
   280,652 queries）；如需运行应使用流式 parquet 或固定种子采样子集。
3. tree-sitter 多语言符号解析尚未接入，目前符号闭包仍以正则 / AST
   混合实现为主。
4. evidence span 当前只用于展示，不参与排序；本文件中的质量提升全部
   来自查询编译层，不依赖上下文切片指标。
