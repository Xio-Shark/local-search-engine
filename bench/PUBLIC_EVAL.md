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
| CoIR / CodeSearchNet-Python（采样） | 20,000 docs（固定种子） | 无官方 train qrels | 从 14,918 条 test qrels 中固定采样 2,000 条 | 同上 |

SciFact train / test qrels 只有 1 条 query 重叠；CoIR CosQA 使用官方
valid / test 划分。默认参数（`query_mode=auto` + `IDF^0.25`）只在 dev split
上选择，随后原样跑 test split，避免在最终报告集上调参。

CodeSearchNet 只有 test qrels，26 万级 corpus / query；本节报告的是
`--sample-docs 20000 --sample-queries 2000 --seed 42` 的固定种子采样：
先保留选中 query 的全部相关文档，再用 reservoir sampling 补足 20,000 篇，
queries 只流式读取选中 qid。为避免在最终样本上调参，采样和查询路径
实现完成后只跑一次，不基于该样本修改默认参数。

Baseline：

- **native Tantivy BM25**：默认 analyzer、`title` + `body` 字段、OR 解析、
  原生 BM25 打分（Tantivy 0.26）。代码 query 含 Python/Java 语法导致默认
  parser 报错时，先把非词字符替换为空白再解析，避免把 parser 失败误判成
  检索能力差距；自然语言 query 仍走原始 parser。
- **ripgrep term-count**：按查询词在文件中的出现次数排序，case-insensitive。
- **lse**：Tantivy 之上的分词 / 查询编译层；代码片段会绕过 Query DSL
  判定，按索引侧 tokenizer 走自然语言 OR 路径。

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
| **lse（默认）** | **0.6492** | **0.7955** | **0.6074** | 19.99 ms | 6.35 s |
| native Tantivy BM25 | 0.6232 | 0.7508 | 0.5886 | 0.16 ms | 0.05 s |
| ripgrep term-count | 0.0477 | 0.1025 | 0.0311 | 84.32 ms | 25.18 s |

paired bootstrap（nDCG@10，5000 次重采样）：

- lse vs native BM25：mean diff **+0.0260**，95% CI **[+0.0006, +0.0518]**，
  W/L/T = 66/51/183。
- lse vs ripgrep：mean diff **+0.6015**，95% CI [+0.5577, +0.6459]。

`--repeat 3 --deterministic-index` 下 lse / native nDCG@10 的 std 均为 0.0，
结果稳定。SciFact 相比上一版 lse（0.5682）提升 **+0.0810**。
`scifact-rank-only.json` 与 full 模式的 lse nDCG@10 完全相同（0.6492）。

### 3.2 CoIR / CosQA test（500 q）

```bash
uv run --extra eval python bench/bench_public.py \
  --dataset cosqa --baselines lse,tantivy,ripgrep \
  --deterministic-index --bootstrap-samples 5000 \
  --output-json bench/results/cosqa.json
```

| Baseline | nDCG@10 | Recall@10 | MRR@10 | p50 latency | total time |
| :--- | ---: | ---: | ---: | ---: | ---: |
| **lse（默认）** | **0.1505** | 0.2980 | **0.1073** | 10.93 ms | 5.67 s |
| native Tantivy BM25 | 0.1481 | 0.2900 | 0.1063 | 0.13 ms | 0.07 s |
| ripgrep term-count | 0.0185 | 0.0400 | 0.0121 | 396.56 ms | 200.52 s |

paired bootstrap（nDCG@10，5000 次重采样）：

- lse vs native BM25：mean diff **+0.0025**，95% CI **[-0.0087, +0.0136]**，
  W/L/T = 28/26/446。

**结论要诚实**：在 deterministic 且可复现的口径下，CosQA 上 lse 仅比原生
BM25 高约 0.0025，95% CI 跨 0，**不能宣称统计显著超越**；上一轮非确定性
运行（索引 segment 布局不同）曾出现更大的差距，但该差异对并列排序高度
敏感，不应作为最终结论。`cosqa-rank-only.json` 与 full 模式的 lse
nDCG@10 完全相同（0.1505）。

### 3.3 CoIR / CodeSearchNet-Python 固定种子采样（2,000 q）

```bash
uv run --extra eval python bench/bench_public.py \
  --dataset codesearchnet-python \
  --sample-docs 20000 --sample-queries 2000 --seed 42 \
  --baselines lse,tantivy \
  --deterministic-index --repeat 3 --bootstrap-samples 5000 \
  --output-json bench/results/codesearchnet-python-sample.json

# rank-only 复跑：nDCG 与 full 完全一致
uv run --extra eval python bench/bench_public.py \
  --dataset codesearchnet-python \
  --sample-docs 20000 --sample-queries 2000 --seed 42 \
  --baselines lse,tantivy \
  --deterministic-index --repeat 3 --lse-rank-only \
  --output-json bench/results/codesearchnet-python-sample-rank-only.json
```

| Baseline | nDCG@10 | Recall@10 | MRR@10 | full p50 | rank p50 |
| :--- | ---: | ---: | ---: | ---: | ---: |
| lse（默认） | 0.9451 | **0.9805** | 0.9336 | 32.14 ms | 1.13 ms |
| native Tantivy BM25 | **0.9453** | 0.9750 | **0.9355** | 0.47 ms | 0.47 ms |

paired bootstrap（nDCG@10，5000 次重采样）：

- lse vs native BM25：mean diff **-0.0002**，95% CI **[-0.0059, +0.0056]**，
  W/L/T = 76/93/1831。

**决策门结论**：固定种子 CodeSearchNet 采样上 lse 与 native BM25 基本
打平（CI 跨 0，均值还略低 0.0002），Recall 略高、MRR 略低。因此**不能
宣称 lse 在代码检索上领先**；后续应先查 tokenizer / IDF / 字段权重，
而不是直接上 reranker / 向量检索。真实代码检索的结论仍是“未确认”。

### 3.4 泛化验证：NFCorpus / FiQA / Arguana

```bash
for ds in nfcorpus fiqa arguana; do
  uv run python bench/bench_public.py --dataset "$ds" --baselines lse,tantivy \
    --deterministic-index --bootstrap-samples 5000 \
    --output-json "bench/results/$ds.json"
done

# NFCorpus 显式 natural profile；FiQA natural 作为补充诊断
uv run python bench/bench_public.py --dataset nfcorpus --baselines lse,tantivy \
  --lse-query-mode natural --deterministic-index --bootstrap-samples 5000 \
  --output-json bench/results/nfcorpus-natural.json
uv run python bench/bench_public.py --dataset fiqa --baselines lse,tantivy \
  --lse-query-mode natural --deterministic-index --bootstrap-samples 5000 \
  --output-json bench/results/fiqa-natural.json
```

| 数据集（test） | lse nDCG@10 | native BM25 | mean diff | 95% CI | W/L/T |
| :--- | ---: | ---: | ---: | ---: | :--- |
| NFCorpus（323 q） | 0.2884 | **0.2994** | -0.0110 | [-0.0232, +0.0010] | 72/87/164 |
| FiQA（648 q） | 0.2283 | **0.2336** | -0.0054 | [-0.0138, +0.0026] | 95/103/450 |
| Arguana（1,406 q） | 0.3097 | **0.3152** | -0.0055 | [-0.0122, +0.0009] | 255/301/850 |

三条 CI 都跨 0，因此**不能判定 lse 显著劣于原生 BM25**；但三个点估计
全部为负，也**没有出现 SciFact 上的正 gap**。这直接说明：`IDF^0.25`
与 `query_mode=auto` 的组合不能从 SciFact 外推为通用最优，SciFact 的
+0.0260 更像数据集特定收益，而不是引擎的普遍优势。

进一步定位：

1. **短查询 auto AND 是明确缺口**。NFCorpus 用
   `--lse-query-mode natural` 后 nDCG@10 = **0.3061**，反超原生 BM25 的
   0.2994（mean diff **+0.0067**，95% CI [-0.0022, +0.0160]，仍跨 0）。
   默认 auto 的短关键词 AND 策略在该数据集损失约 0.011 nDCG，说明并不是
   BM25 打分本身弱，而是短查询连接语义需要按数据分布选择。
2. **句中标点误判曾显著伤害 FiQA / Arguana**。修复前的 FiQA diff 为
   -0.0125（CI 显著为负）、Arguana 为 -0.1310（CI 显著为负）。原因是
   自然语言 claim 中的 `business:`、`environment:` 及句内引号被
   `QueryCompiler` 误判为字段表达式 / 精确短语，从而退回结构化 AND AST。
   现已改为“未知 prefix:value 与长句中的引号按自然语言标点处理”，
   修复后两条 diff 均回到 CI 跨 0。
3. **`IDF^0.25` 本身不是唯一问题**。关闭 IDF 或在自然模式下改变
   IDF power，并未在这些数据集上出现系统性反转；不应把结论简单写成
   “IDF^0.25 在 SciFact 过拟合后直接砍掉”。下一步需要的是按数据集 /
   查询模式选择 profile，或把短查询 auto AND 改为经过 dev 验证的策略。

**发布决策**：Phase C1 未达到“多数数据集上不劣于 native BM25”的
验收线，当前不应 bump 0.3.0 或进入 tree-sitter / reranker 等新能力投资。

## 4. 延迟：概念图缓存（P0）、rank-only 与 evidence span 成本

profiling（SciFact，`limit=10`）显示旧实现每个 query 都执行
`load_project_concepts()`：JSON parse + `merge_concept_maps(base, dynamic)`，
占单次搜索延迟的 **83%**。benchmark 临时路径还会挖出巨大噪声概念图。

| 指标 | 修复前 | 修复后 |
| :--- | ---: | ---: |
| 动态概念图条目 | 10,373 keys / 41,492 邻居 / 1.09 MB | 上限 2,048 keys |
| 合并后概念图 | 每次搜索重新 parse + merge | mtime/size keyed LRU |
| `load_project_concepts` | 8.8 ms/次 | 首次 1.2 ms，缓存命中 0.011 ms |
| `search(limit=10)` p50（full） | 11.5 ms | **2.15 ms** |
| `search(limit=100)` p50（full） | 29.0 ms | **19.9 ms** |
| SciFact public full p50 | 29.2 ms | **19.99 ms** |
| CosQA public full p50 | 74.4 ms | **10.93 ms** |
| CodeSearchNet sample full p50 | — | **32.14 ms** |

`SearchOptions.include_spans=False` 已实现 rank-only 模式：只读 stored
元数据并返回 `path/filename/extension/size/mtime/score`，完全跳过
`_read_disk_file` 与 `extract_evidence_spans`，排序路径和 full 模式相同：

| 数据集 | lse full p50 | lse rank-only p50 | native BM25 p50 | nDCG 是否一致 |
| :--- | ---: | ---: | ---: | :--- |
| SciFact test | 19.99 ms | **0.86 ms** | 0.18 ms | 完全一致 (0.6492) |
| CosQA test | 10.93 ms | **0.90 ms** | 0.15 ms | 完全一致 (0.1505) |
| CodeSearchNet-Python 采样 | 32.14 ms | **1.13 ms** | 0.47 ms | 完全一致 (0.9451) |

full p50 包含命中后读取正文、计算 evidence span / snippet，是 Agent 拿到
上下文时的真实成本；rank-only p50 则与原生 BM25 同口径，适合 Agent 预筛
和大规模 rerank 前召回。CodeSearchNet 长代码 query 的 rank-only p50 略高
于 1 ms，量级仍与原生 BM25 相同（亚 2 ms），主要成本在长 query 的
tokenizer / IDF 编译。

## 5. 实现摘要

当前默认查询策略（`lse.options.SearchOptions`）：

1. **auto 查询模式**：短关键词查询（≤ 3 个内容词元、无句末标点）→ 结构化
   AND，保留文件搜索精度；长句 / claim → 用索引侧同一套 `tokenize_stream`
   分词，编译成字段内 OR-of-terms，并按 `IDF^0.25` 加权。
2. **代码片段识别**：整段含换行或出现强代码声明形态时，忽略 Query DSL
   语法（Python 字符串引号、dict `name:`、类型标注等），直接按索引侧
   tokenizer 走自然语言 OR 路径。
3. **结构化语法**（已知字段 `ext:py` / `filename:...`、整句精确引号短语、
   大写 `AND/OR/NOT`、`sort:...`、`*`）→ 走 AST 查询编译器，默认 AND；
   未知 `prefix:value` 与长句中的引号按自然语言标点处理。
4. **CJK / 中西混排** → 保留分组语义，例如 `目录A` 编译为 `目录 AND a`。
5. **rank-only 模式**：`SearchOptions(include_spans=False)` 只返回排序
   元数据，不读取正文 / 不计算 span，用于 Agent 预筛与公平延迟基准。
6. **概念图缓存**：合并后的概念图按 `(path, mtime_ns, size)` LRU 缓存，
   索引更新自动失效；`AdaptiveConceptMiner` 默认限制动态图 2,048 条。
7. **benchmark 可复现性**：`--deterministic-index`、`--repeat N`、
   per-query JSON、paired bootstrap（`--bootstrap-samples` / `--bootstrap-metric`）、
   固定种子 CoIR 采样（`--sample-docs` / `--sample-queries` / `--seed`）。

## 6. 已知边界

1. 除 SciFact 外，CosQA、CodeSearchNet 采样、NFCorpus、FiQA、Arguana
   上 lse 相对原生 BM25 的点估计均不为正；多数 CI 跨 0，不能宣称
   通用或代码检索领先。
2. `IDF^0.25 + query_mode=auto` 尚未证明可泛化；NFCorpus 上显式
   `query_mode=natural` 即可从 -0.0110 回到持平，短查询 auto AND
   阈值是下一步最值得验证的方向。
3. 当前不能 bump 0.3.0 / 打 tag / 走 release workflow：Phase C1 的
   “多数数据集不劣于 native BM25”前置条件未满足。条件性优化应优先
   做 query profile / 短查询策略，而不是 title/BM25F、reranker 或
   tree-sitter。
4. CodeSearchNet 目前只跑固定种子采样（20k docs / 2k queries），未跑全量
   280,310 docs；如果后续需要全量，应继续使用流式 parquet + 采样，
   不能 materialize 28 万个小文件。
5. rank-only p50 与原生 BM25 同量级，但 full p50 仍高一个数量级，因为
   包含正文读取 + evidence span；排序本身已是亚毫秒到 1.1 ms。
6. tree-sitter 多语言符号解析尚未接入，符号闭包仍以正则 / AST 混合实现。
   注意：在 C1 泛化问题解决前不应启动该投资。
