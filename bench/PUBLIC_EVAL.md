# 第三方公开数据集评测

本文件记录 lse 在公开检索数据集上的可复现评测。所有数字来自本机运行，
脚本、原始 JSON 与命令均已入库；不同机器 / CPU 调度可能造成小幅波动。
`--deterministic-index` 固定索引 writer 单线程，用于消除 segment 布局与
并列排序造成的运行间抖动；`--repeat N` 会重复评测并输出 mean ± std。

## 1. 数据集与划分

| 数据集 | 语料 | dev split（只用于调参） | test split（只用于最终报告） | 指标 |
| :--- | ---: | :--- | :--- | :--- |
| BEIR / SciFact | 5,183 篇摘要 | `qrels/train.tsv`，809 条 | `qrels/test.tsv`，300 条 | nDCG@10 / Recall@10 / MRR@10，深度 100 |
| BEIR / NFCorpus | 3,633 篇医学摘要 | `qrels/train.tsv`，2,590 条 | `qrels/test.tsv`，323 条 | 同上 |
| BEIR / FiQA | 57,638 条金融问答 | `qrels/train.tsv`，5,500 条 | `qrels/test.tsv`，648 条 | 同上 |
| BEIR / Arguana | 8,674 条论据 | 无 train qrels | `qrels/test.tsv`，1,406 条 | 同上 |
| CoIR / CosQA | 20,604 条 Python 代码 | `data/valid`，500 条 | `data/test`，500 条 | 同上 |
| CoIR / CodeSearchNet-Python（采样） | 20,000 docs（固定种子） | 无官方 train qrels | 从 14,918 条 test qrels 中固定采样 2,000 条 | 同上 |

SciFact train / test qrels 只有 1 条 query 重叠；CoIR CosQA 使用官方
valid / test 划分。默认参数（`query_mode=auto` + `auto_structured_max_terms=0`
+ `IDF^0.25`）只在 dev split 上选择，随后原样跑 test split，避免在最终
报告集上调参。Arguana 没有官方 train qrels，只作为泛化验证集出现，
不参与任何默认值选择。

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

### 2.3 短查询 auto AND 阈值扫描（四个 dev split）

`bench_ablation.py` 每个变体都要重建索引，无法扫完整阈值网格；
`bench_query_policy.py` 只切换 `SearchOptions`，索引与文档目录只建一次，
并额外输出按内容词元数分桶的 natural vs structured 对比。所有策略都是
rank-only（`include_spans=False`），已确认排序与 full 模式一致。

```bash
# 数据集级并行：benchmark 进程是单线程的（实测 cpu/wall ≈ 1.0），
# 每个子进程独占临时索引目录，结果与串行逐位一致。
uv run --extra eval python bench/bench_query_policy.py \
  --dataset scifact,nfcorpus,fiqa,cosqa --jobs 4 \
  --include-tantivy --deterministic-index \
  --output-json "bench/results/query-policy-{dataset}.json"
```

四个数据集串行 153.7 s，按数据集并行 **117.5 s**；下限由最慢的 FiQA
决定。脚本会把阶段计时写进 JSON 的 `timings` 字段：

| 数据集 | dataset load | materialize | index build | policy eval（12 策略） | total |
| :--- | ---: | ---: | ---: | ---: | ---: |
| SciFact train（809 q） | 0.0 s | 0.5 s | 1.6 s | 9.0 s | 15.1 s |
| NFCorpus train（2,590 q） | 0.1 s | 0.3 s | 1.2 s | 14.6 s | 25.4 s |
| FiQA train（5,500 q） | 0.2 s | 6.2 s | 11.0 s | **74.8 s** | 116.8 s |
| CosQA valid（500 q） | 0.3 s | 2.5 s | 3.3 s | 6.0 s | 16.0 s |

FiQA 的 `policy_eval`（12 策略 × 5,500 query × ~1.1 ms，即引擎真实
rank-only 单查询成本）占其总耗时 64%，是并行之后的主要瓶颈；若以后需要
再压时间，应按策略分片并行，而不是继续调栅格。

nDCG@10（`auto@N` = 内容词元数 ≤ N 时走结构化 AND；`auto@0` 等价于 natural）：

| 策略 | SciFact train | NFCorpus train | FiQA train | CosQA valid | 均值 |
| :--- | ---: | ---: | ---: | ---: | ---: |
| native Tantivy BM25 | 0.6314 | 0.2989 | 0.2316 | 0.1426 | 0.3261 |
| `structured_and`（旧默认） | 0.5958 | 0.2648 | 0.1500 | 0.1422 | 0.2882 |
| `structured_or` | 0.6081 | 0.2884 | 0.1714 | 0.1463 | 0.3036 |
| **`natural` / `auto@0`（当前默认）** | **0.6499** | **0.3022** | **0.2308** | **0.1473** | **0.3326** |
| `auto@1` | 0.6499 | 0.3012 | 0.2308 | 0.1473 | 0.3323 |
| `auto@2` | 0.6499 | 0.2903 | 0.2303 | 0.1473 | 0.3295 |
| `auto@3`（旧默认阈值） | 0.6499 | 0.2863 | 0.2298 | 0.1473 | 0.3283 |
| `auto@4` | 0.6499 | 0.2821 | 0.2291 | 0.1448 | 0.3265 |
| `auto@6` | 0.6499 | 0.2749 | 0.2267 | 0.1436 | 0.3238 |
| `auto@12` | 0.6478 | 0.2713 | 0.2192 | 0.1421 | 0.3201 |

结论：

1. **阈值 0 在四个 dev split 上全部最优或并列最优。** SciFact train 的
   query 内容词元数都 ≥ 3，所以 N ≤ 6 的阈值在该数据集上完全等价；
   但 NFCorpus train 有 762 条 ≤ 1 词元的 query，阈值每提高一档都会掉分
   （`auto@1` 已 -0.0010，CI [-0.0019, -0.0003]；`auto@3` -0.0158）。
2. **分桶后 natural 在每个词元数桶都 ≥ structured AND**，包括
   `content_terms=1`（NFCorpus：0.3209 vs 0.3175），不存在“极短查询
   仍然该用 AND”的子区间。
3. CosQA 是代码 query，走代码路径，阈值对它几乎无影响（0.1473 持平），
   因此该选择不需要在代码检索上做额外妥协。
4. 选中的是 profile（纯词项 → 与索引对齐分词 + IDF 加权 OR），不是
   数据集特判：没有任何按数据集 / 按查询来源切换策略的逻辑。

`SearchOptions.auto_structured_max_terms` 暴露了该阈值（默认 0，
负值报错），`bench_public.py --lse-auto-max-terms` 可复现其他取值。

### 2.4 残余负 gap 诊断：IDF 幂次 vs 概念展开 vs 查询字段

§3.4 里 FiQA / Arguana 的点估计仍为负。为了区分“缺能力”和“打分旋钮 /
profile 没选对”，用同一套单索引扫描固定 natural 路径，只切换打分参数
（`--suite gap`），不引入任何新模型：

```bash
# 四个 dev split + Arguana（无 train qrels，只用于解释，不参与选择）
uv run --extra eval python bench/bench_query_policy.py \
  --dataset scifact,nfcorpus,fiqa,cosqa --jobs 4 --suite gap \
  --include-tantivy --deterministic-index \
  --output-json "bench/results/gap-probe-{dataset}.json"
uv run --extra eval python bench/bench_query_policy.py \
  --dataset arguana --qrels-split test --suite gap \
  --include-tantivy --deterministic-index \
  --output-json bench/results/gap-probe-arguana.json
```

nDCG@10（`natural` = 当前默认 IDF^0.25 + 概念展开 + content,filename,path）：

| 策略 | SciFact train | NFCorpus train | FiQA train | CosQA valid | Arguana test |
| :--- | ---: | ---: | ---: | ---: | ---: |
| native Tantivy BM25 | 0.6314 | 0.2989 | **0.2316** | 0.1426 | 0.3152 |
| **`natural`（当前默认）** | **0.6499** | **0.3022** | 0.2308 | **0.1473** | 0.3097 |
| `natural_no_idf`（完全不加权） | 0.6437 | 0.3015 | 0.2301 | 0.1448 | 0.3028 |
| `natural_idf050` | 0.6453 | 0.3013 | 0.2277 | 0.1408 | 0.3124 |
| `natural_idf100` | 0.6395 | 0.2984 | 0.2115 | 0.1396 | **0.3169** |
| `natural_noconcept` | 0.6499 | 0.3022 | 0.2309 | 0.1480 | 0.3097 |
| `natural_content_only` | 0.6499 | 0.3022 | 0.2308 | 0.1473 | 0.3097 |

相对 native BM25 的 delta（nDCG@10）：

| 策略 | SciFact | NFCorpus | FiQA | CosQA | Arguana |
| :--- | ---: | ---: | ---: | ---: | ---: |
| `natural` | +0.0186 | +0.0033 | -0.0007 | +0.0047 | -0.0055 |
| `natural_idf100` | +0.0082 | -0.0005 | -0.0200 | -0.0030 | **+0.0017** |

结论：

1. **概念展开与查询字段被排除**：`natural_noconcept` / `natural_content_only`
   与 `natural` 在五个数据集上逐位相同（W/L/T = 0/0/N；FiQA 只有 5 条
   query 差 1e-4、CosQA 1 条）。残余 gap 与“同义词扩召回噪声”“filename /
   path 字段污染”无关。
2. **唯一有效旋钮是 IDF 幂次，且最优值随 query 形态变化**：`0.25` 在四个
   dev split 上最优；Arguana（1,406 条全部 >160 字符的长论据 query）上
   `IDF^1.0` 显著更好（+0.0072，CI [+0.0026, +0.0119]），并把该数据集
   相对 native BM25 的 gap 从 -0.0055 **翻正到 +0.0017**。完全不加权
   （`no_idf`）在五个数据集上全部更差，说明 IDF 加权本身不是问题，
   幂次才是。
3. **长度分桶是同一机制的第二观测点**：SciFact train 中 >160 字符的
   18 条 query，natural 比 native 低 0.1333；FiQA 最大的负桶是 21-40
   字符（-0.0060），其余桶都在 ±0.002 内。即“长 query 需要更接近原生
   BM25 的 IDF 幂次，短 claim / question 需要压平 IDF”。
4. **不把它变成默认值**：Arguana 没有 train qrels，无法在 dev split 上
   验证“按 query 长度切换 IDF 幂次”的 profile，而四个 dev split 一致
   支持当前 0.25；在最终报告集上按长度调参违反本文件的调参纪律。
5. **仍未验证的结构性差异（明确标注，不在本轮结论内）**：lse 把 `title`
   并入 `content` 单字段，native 用 `title` + `body` 双字段。本轮实验全部
   在 `SearchOptions` 层面，无法测试字段布局；但 `idf100` 已把 Arguana
   翻正、其余数据集点估计 ≥ 0，残余 ≤0.004，没有证据显示它是主要缺口。
   若要继续验证，应先找一个带 train split 的长 query 数据集（如
   HotpotQA），而不是直接改 schema 或上 reranker / tree-sitter。
6. FiQA 的 dev（train）gap 只有 -0.0007，test 上为 -0.0039，量级差异属于
   split 间波动；FiQA 的旋钮结论（0.25 最优、1.0 显著更差）在两个
   split 上一致。

### 2.5 长度分段 IDF 的可行性验证（实验 A）

§2.4 的结论是“长 query 需要更高的 IDF 幂次”。本节的实验把它做成一条
可配置规则并验证：query 字符数 > `idf_power_long_chars` 时改用
`idf_power_long`，阈值以下保持 `idf_power`。规则默认关闭
（`idf_power_long=None`，逐位等价于旧行为，有单测覆盖）。

```bash
# 1) 四个 dev split 回归：阈值是否只在长 query 上生效
uv run --extra eval python bench/bench_query_policy.py \
  --dataset scifact,nfcorpus,fiqa,cosqa --jobs 4 --suite length \
  --include-tantivy --deterministic-index \
  --output-json "bench/results/length-probe-{dataset}.json"

# 2) Arguana 全量 + A/B（A 选规则 / B 报告；切分按 query id + 固定种子）
for sub in all a b; do
  uv run --extra eval python bench/bench_query_policy.py \
    --dataset arguana --qrels-split test --suite length --query-subset "$sub" \
    --include-tantivy --deterministic-index \
    --output-json "bench/results/length-arguana-$sub.json"
done

# 3) 代码检索连带影响：同一 20k/2k 固定种子采样
uv run --extra eval python bench/bench_public.py \
  --dataset codesearchnet-python --sample-docs 20000 --sample-queries 2000 --seed 42 \
  --baselines lse,tantivy --deterministic-index --repeat 3 --bootstrap-samples 5000 \
  --lse-rank-only --lse-idf-long 1.0 --lse-idf-long-chars 160 \
  --output-json bench/results/length-codesearchnet-python-sample.json
```

**1) dev 回归**（delta vs `natural`，nDCG@10）：

| 数据集 | >160 字符 query | `len100_idf100` | `len160_idf050` | `len160_idf100` | `len240_idf100` |
| :--- | ---: | ---: | ---: | ---: | ---: |
| SciFact train | 18 / 809 | -0.0036 | -0.0000 | -0.0003 | +0.0002 |
| NFCorpus train | 0 / 2590 | -0.0001 | +0.0000 | **+0.0000** | +0.0000 |
| FiQA train | 0 / 5500 | **-0.0017** | +0.0000 | **+0.0000** | +0.0000 |
| CosQA valid | 0 / 500 | +0.0000 | +0.0000 | **+0.0000** | +0.0000 |

阈值 160 / 240 时 NFCorpus、FiQA、CosQA **逐位相同**（W/L/T = 0/0/N），
SciFact 只有 18 条长 query 受影响且中性（-0.0003，CI [-0.0015, +0.0004]）。
阈值 100 会把 FiQA 的 81–160 字符 query 拖进长 query 分支，造成
**-0.0017 的显著回归**——阈值必须 ≥ 160，这由 dev split 的长度分布决定，
与 test 集无关。

**2) Arguana 全量 / A / B**（1,406 条 query 全部 >160 字符）：

| 策略 | full（1406） | A（703） | B（703） |
| :--- | ---: | ---: | ---: |
| `natural`（IDF^0.25） | 0.3097 | 0.3243 | 0.2951 |
| native Tantivy BM25 | 0.3152 | 0.3235 | 0.3070 |
| `len160_idf050` | 0.3124（+0.0027） | 0.3264（+0.0021） | 0.2984（+0.0033） |
| `len160_idf100` | **0.3169（+0.0072）** | **0.3321（+0.0078）** | **0.3016（+0.0065）** |
| vs native：`natural` → `len160_idf100` | -0.0055 → **+0.0017** | -0.0009 → **+0.0086** | -0.0119 → -0.0054 |

两个半集独立显著（A：CI [+0.0013, +0.0142]；B：CI [+0.0002, +0.0133]），
全量 gap 翻正，说明收益不是少数 query 的偶然。

**3) 代码检索连带影响（决定性）**：99% 的 CodeSearchNet query 超过
160 字符（p50 = 624），规则会覆盖几乎全部代码 query：

| 口径 | CSN 采样 lse nDCG@10 | lse vs native BM25 |
| :--- | ---: | ---: |
| 规则关闭（当前默认） | **0.9451** | -0.0002，CI [-0.0059, +0.0056] |
| 规则开启（>160 字符 IDF^1.0） | 0.9373 | **-0.0080，CI [-0.0149, -0.0014]** |

**结论：规则不进入默认值。** 长度是单一维度，同一个“>160 字符”桶里同时
装着长论据（Arguana，规则 +0.0072）和长代码片段（CSN，规则 -0.0078 并把
相对 native BM25 的关系从持平变成显著劣化）。把代码 query 排除在外确实能
让两个数据集都好看，但那样剩下的唯一证据就是 Arguana 这个没有 train qrels
的最终报告集——属于对着 test 调参。因此：

- `SearchOptions.idf_power_long` / `idf_power_long_chars` 保留为**默认关闭**
  的实验开关，`bench_public.py --lse-idf-long/--lse-idf-long-chars` 可复现；
- 在拿到带 train qrels 的长 prose 语料（HotpotQA / FEVER 量级，见 §6）之前
  不再推进这条线，也不会上 reranker / tree-sitter 来掩盖这 0.005 的差距。

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

### 3.4 泛化验证：NFCorpus / FiQA / Arguana（阈值 0 口径全部复跑）

§2.3 的 dev 扫描把默认 `auto_structured_max_terms` 从 3 改为 0，随后原样
重跑全部 test split（rank-only 口径，排序与 full 一致）：

```bash
# 数据集级并行；结果与串行逐位一致（mean diff 差 0.00e+00）
uv run python bench/bench_public.py \
  --dataset scifact,nfcorpus,fiqa,arguana,cosqa --jobs 3 \
  --baselines lse,tantivy --lse-rank-only --deterministic-index \
  --bootstrap-samples 5000 \
  --output-json "bench/results/{dataset}-rank-only.json"
```

串行 5 次合计 34.1 s → 并行 21.4 s（`--jobs 3` 两批，FiQA 批次为下限；
`--jobs 5` 单批约 14 s）。

| 数据集（test） | lse nDCG@10 | native BM25 | mean diff | 95% CI | W/L/T |
| :--- | ---: | ---: | ---: | ---: | :--- |
| SciFact（300 q） | **0.6492** | 0.6232 | **+0.0260** | [+0.0006, +0.0518] | 66/51/183 |
| NFCorpus（323 q） | **0.3061** | 0.2994 | +0.0067 | [-0.0022, +0.0160] | 85/74/164 |
| FiQA（648 q） | 0.2297 | **0.2336** | -0.0039 | [-0.0119, +0.0040] | 95/101/452 |
| Arguana（1,406 q） | 0.3097 | **0.3152** | -0.0055 | [-0.0122, +0.0009] | 255/301/850 |
| CosQA（500 q） | **0.1505** | 0.1481 | +0.0025 | [-0.0087, +0.0136] | 28/26/446 |

与阈值 3 的旧口径对比：

| 数据集 | 阈值 3（旧） | 阈值 0（新） | 变化 |
| :--- | ---: | ---: | :--- |
| NFCorpus | 0.2884（diff -0.0110） | **0.3061（diff +0.0067）** | 翻正，+0.0177 |
| FiQA | 0.2283（diff -0.0054） | 0.2297（diff -0.0039） | +0.0014 |
| Arguana | 0.3097（diff -0.0055） | 0.3097（diff -0.0055） | 不变 |
| SciFact | 0.6492（diff +0.0260） | 0.6492（diff +0.0260） | 不变 |
| CosQA | 0.1505（diff +0.0025） | 0.1505（diff +0.0025） | 不变 |

结论：

1. **短查询 auto AND 缺口已关闭**。NFCorpus 从 -0.0110 翻正到 +0.0067
   （与旧口径下 `--lse-query-mode natural` 的 0.3061 完全一致，说明
   缺口的全部来源就是短查询连接语义，而不是 BM25 打分）。
2. **没有任何数据集再出现显著负 gap**：FiQA / Arguana 仍是小幅负值，
   但 CI 跨 0，且点估计都比旧口径更接近 0 或不变。
3. **仍不足以宣称领先**：5 个 test 数据集中只有 SciFact 的正 gap
   CI 不跨 0，NFCorpus / CosQA 的点估计为正但 CI 跨 0。
   FiQA / Arguana 的点估计仍为负，说明 FiQA 的长句 / 多主题 query
   与 Arguana 的长论据仍有未解释的差距，不能把这一轮修复包装成
   “lse 全面优于原生 BM25”。
4. **句中标点误判是上一轮已修的独立问题**：修复前 FiQA diff 为 -0.0125
   （CI 显著为负）、Arguana 为 -0.1310（CI 显著为负）；自然语言 claim 中的
   `business:`、`environment:` 及句内引号曾被 `QueryCompiler` 误判为字段
   表达式 / 精确短语而退回结构化 AND AST，现按自然语言标点处理。
5. **`IDF^0.25` 本身没有被证伪**：关闭 IDF 或改变 IDF power 都不能在
   这些数据集上产生系统性反转，因此保留 dev split 上选出的 0.25。

**发布决策**：短查询策略这一前置问题已按 dev split 证据解决，C1 不再有
“显著劣于 native BM25”的数据集；但正 gap 仍只在 SciFact 上显著，
因此仍不应把结论写成通用 / 代码检索领先，也不应立刻 bump 0.3.0。
下一步若继续做质量投资，应先解释 FiQA / Arguana 的残余负 gap
（query 长度 / 多主题结构），而不是直接上 reranker 或 tree-sitter。

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
| SciFact test | 19.99 ms | **0.69 ms** | 0.15 ms | 完全一致 (0.6492) |
| CosQA test | 10.93 ms | **0.69 ms** | 0.13 ms | 完全一致 (0.1505) |
| CodeSearchNet-Python 采样 | 32.14 ms | **1.13 ms** | 0.47 ms | 完全一致 (0.9451) |

full p50 包含命中后读取正文、计算 evidence span / snippet，是 Agent 拿到
上下文时的真实成本；rank-only p50 则与原生 BM25 同口径，适合 Agent 预筛
和大规模 rerank 前召回。CodeSearchNet 长代码 query 的 rank-only p50 略高
于 1 ms，量级仍与原生 BM25 相同（亚 2 ms），主要成本在长 query 的
tokenizer / IDF 编译。

## 5. 实现摘要

当前默认查询策略（`lse.options.SearchOptions`）：

1. **auto 查询模式**：纯词项查询 → 用索引侧同一套 `tokenize_stream` 分词，
   编译成字段内 OR-of-terms，并按 `IDF^0.25` 加权；短查询 AND 阈值
   `auto_structured_max_terms` 默认 **0**（四个 dev split 扫描结果见 §2.3），
   非 0 取值仅用于复现实验。
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
8. **benchmark 运行开销约定**：两个脚本都支持 `--dataset a,b,c --jobs N`
   数据集级并行（子进程隔离，结果与串行逐位一致）；JSON 默认只存聚合值 /
   显著性 / 分桶（`--include-per-query` 才存 per-query），产物 KB 级；
   `bench_query_policy.py` 会把 `dataset_load / materialize / index_build /
   policy_eval / total` 阶段计时写进 JSON。**不要为了改产物形态重跑
   benchmark**：先用已有 JSON 做后处理，只有口径（策略 / 划分 / 采样）变化
   才需要重跑。

## 6. 已知边界

1. 5 个 test 数据集中只有 SciFact 的正 gap CI 不跨 0（+0.0260）；
   NFCorpus（+0.0067）、CosQA（+0.0025）为正但 CI 跨 0；FiQA（-0.0039）、
   Arguana（-0.0055）点估计仍为负。没有任何数据集显著劣于原生 BM25，
   但仍不能宣称通用或代码检索领先。
2. 短查询 auto AND 已按四个 dev split 的证据改为阈值 0（§2.3），
   NFCorpus test 随之从 -0.0110 翻正到 +0.0067。`IDF^0.25` 保留：
   dev 上最优，且关闭 / 改变 IDF power 都不能在这些数据集上产生
   系统性反转。FiQA / Arguana 的残余负 gap 已定位到 IDF 幂次与
   query 长度形态（§2.4）：概念展开、查询字段逐位无影响；Arguana 上
   `IDF^1.0` 可把 gap 翻正，但该数据集没有 train qrels，无法在 dev 上
   验证“按长度切换 IDF 幂次”的 profile。
2b. 实验 A 已把该 profile 做成默认关闭的开关并验证（§2.5）：阈值 ≥160 时
   三个 dev split 逐位不变、SciFact 中性，Arguana 两个半集独立显著
   （+0.0078 / +0.0065），但同一条规则在 CodeSearchNet 采样上把代码检索
   从 0.9451 压到 0.9373、相对 native BM25 由持平变为**显著劣化**
   （-0.0080，CI [-0.0149, -0.0014]）。长度单维度无法区分长论据与长代码
   片段，因此规则不进入默认值；要合法地把它变成默认值，需要一个带
   train qrels 的长 prose 语料（HotpotQA / FEVER 量级，约 5M 文档）。
3. 当前不 bump 0.3.0 / 打 tag / 走 release workflow：C1 已无“显著劣于
   native BM25”的数据集，但正 gap 只在 SciFact 显著，证据强度不足以支撑
   一次版本发布。残余量级已收敛到 ≤0.0055 nDCG 且定位在打分权重层面，
   因此下一步不是 title/BM25F、reranker 或 tree-sitter；若继续，应先
   找带 train split 的长 query 数据集验证长度自适应 IDF，或验证
   `title` 独立字段这一未测结构差异。
4. CodeSearchNet 目前只跑固定种子采样（20k docs / 2k queries），未跑全量
   280,310 docs；如果后续需要全量，应继续使用流式 parquet + 采样，
   不能 materialize 28 万个小文件。
5. rank-only p50 与原生 BM25 同量级，但 full p50 仍高一个数量级，因为
   包含正文读取 + evidence span；排序本身已是亚毫秒到 1.1 ms。
6. tree-sitter 多语言符号解析尚未接入，符号闭包仍以正则 / AST 混合实现。
   注意：在 C1 泛化问题解决前不应启动该投资。
