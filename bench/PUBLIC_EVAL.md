# 第三方公开数据集评测

## 数据集

- **BEIR / SciFact**（test split）
- Corpus：5,183 篇文档
- Queries：300 条带 qrels 的测试查询
- 指标：nDCG@10、Recall@10、MRR@10
- 检索深度：top 100

## 复现命令

```bash
uv run python bench/bench_public.py \
  --dataset scifact \
  --baselines lse,tantivy,ripgrep \
  --output-json bench/results/scifact.json
```

首次运行会把 `scifact.zip` 下载到 `~/.cache/lse-eval/beir/`，之后离线复跑。

## 结果

| Baseline | nDCG@10 | Recall@10 | MRR@10 | p50 latency | total time |
| :--- | ---: | ---: | ---: | ---: | ---: |
| lse | 0.5682 | 0.6962 | 0.5320 | 28.6 ms | 8.9 s |
| native Tantivy BM25 | **0.6199** | **0.7474** | **0.5852** | 0.16 ms | 0.05 s |
| ripgrep term-count | 0.0477 | 0.1025 | 0.0311 | 86.5 ms | 26.4 s |

环境：macOS 26.5.1 arm64，Python 3.11.15，lse 0.2.0，Tantivy 0.26，ripgrep 15.1.0。

## 结论

1. lse 当前实现明显优于 ripgrep 字面词频 baseline，但**低于原生 Tantivy BM25 baseline**。
2. 这说明当前自定义 query compiler、concept projection、`conjunction_by_default=True` 或字段选择可能伤害标准 BM25 召回，而不是稳定带来排序提升。
3. lse 单查询延迟更高（p50 28.6 ms），主要原因是为 snippet/evidence span 读取正文并计算结构切片；对本地 Agent 预筛场景可接受，但仍需优化。
4. 后续应做 query-level 消融：关闭 concept expansion、把 AND 改为 OR/加权 OR、移除 filename/path 字段噪声，再在 SciFact 上重新评测；在此之前不应引用旧合成 benchmark 的 91.7% 作为泛化能力结论。

## 尚未接入

- CoIR（代码检索，HuggingFace）
- CodeSearchNet（代码检索）
- BM25 + 向量混合检索 baseline

## CoIR / CosQA

- CoIR / CosQA（test split）
- Corpus：20,604 条 Python 代码片段
- Queries：500 条，qrels 来自 `data/test`
- 指标与深度：nDCG@10、Recall@10、MRR@10，top 100

```bash
uv run --extra eval python bench/bench_public.py \
  --dataset cosqa \
  --baselines lse,tantivy,ripgrep \
  --output-json bench/results/cosqa.json
```

| Baseline | nDCG@10 | Recall@10 | MRR@10 | p50 latency | total time |
| :--- | ---: | ---: | ---: | ---: | ---: |
| lse | 0.1569 | 0.3040 | 0.1129 | 81.0 ms | 40.6 s |
| native Tantivy BM25 | **0.1610** | **0.3160** | **0.1149** | 0.19 ms | 0.10 s |
| ripgrep term-count | 0.0185 | 0.0400 | 0.0121 | 457.7 ms | 237.2 s |

CosQA 上 lse 与原生 Tantivy BM25 的 nDCG@10 很接近（0.1569 vs 0.1610），说明代码检索场景下 lse 的标识符解离/结构切片相对有价值；但仍未形成领先，且延迟高约 400 倍，主要成本在正文读取与 evidence span 计算。

## 支持的公开数据集

- BEIR：`scifact`、`nfcorpus`、`fiqa`、`arguana` 等（zip 自动下载）
- CoIR simple repos：`cosqa`、`apps`、`codefeedback-st/mt`、`synthetic-text2sql`、`stackoverflow-qa`、`codetrans-contest/dl`
- CoIR CodeSearchNet：`codesearchnet-go/java/javascript/php/python/ruby`（parquet 自动下载；python split 约 280,310 篇 corpus / 280,652 条 query，本轮未跑全量 benchmark，需后续增加流式/采样子集模式）

## 结论与下一步

1. **BEIR SciFact：lse 明显低于原生 Tantivy BM25，必须做查询层消融。**
2. **CoIR CosQA：lse 接近原生 BM25，但延迟和尾部召回仍需优化。**
3. ripgrep term-count 在自然语言文档和代码检索上都远弱于 BM25，可作为下限 baseline。
4. 下一步优先级：`concept expansion` / `conjunction_by_default` / `filename+path` 权重消融，再做 query-level rank fusion，避免在测试集上调参。
