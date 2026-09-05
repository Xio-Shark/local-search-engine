# lse — 本地全文本搜索引擎

基于 [tantivy](https://github.com/quickwit-oss/tantivy)（Rust 全文索引引擎）的本地文件搜索引擎，
专为 **career 知识库**（桌面目录 / 配合 RAG 系统）设计。

- 🔍 **中英文与代码多流检索**：Code Tokenizer（驼峰/蛇形解离）+ CJK 语义词元
- 🌊 **动态局部共振证据求解**：消灭固定死板切 Chunk，基于能量波函数输出连续精准起止行与面包屑
- 🌲 **形式化 AST 查询引擎**：严谨递归下降语法分析器，支持嵌套、短语加权与长词 WAND 柔性匹配
- 📊 **BM25 相关性排序** + 命中高亮与置信度量化
- 🚀 **事务级增量与内容哈希**：基于 BLAKE2b 内容指纹与临时文件原子置换，彻底杜绝裂脑与虚假重建
- 🎨 **字段过滤**：`ext:` / `filename:` / `type:` / `path:` / `size:` / `mtime:`
- 💻 **纯 CLI**，无 GUI，轻量（打包产物 ~29MB，含 tantivy 引擎）
- 🪟 **跨平台**：macOS (arm64/x86_64) + Windows (amd64)，GitHub Actions 双矩阵自动打包

## 快速开始

```bash
# 安装（Python 3.10+，uv 管理）
uv install -e .

# 1. 索引 career 目录（全部文本文件，自动跳过 .git/.venv/构建产物）
lse index /Users/xioshark/Desktop/career

# 2. 搜索（中文 bigram，毫秒级）
lse search "本地搜索引擎检索知识库" --limit 10

# 3. 字段过滤
lse search 'ext:md'                    # 仅 Markdown
lse search 'filename:README.md'        # 精确文件名
lse search 'type:note'                 # 文档类型
lse search '简历 美团'                  # 组合关键词

# 4. 增量更新 / 状态 / 重建
lse update /Users/xioshark/Desktop/career
lse status
lse rebuild --yes /Users/xioshark/Desktop/career
```

## 与 RAG 集成

`rag-qa-bench` 通过 `lse_enabled` 配置启用 **BM25 预筛**：

```bash
# rag 配置（.env 或 Settings）
LSE_ENABLED=true
LSE_INDEX_DIR=/Users/xioshark/Desktop/career/.lse-index
```

启用后：先用 lse 依据 query 找出相关**文档**，再从这些文档的 chunks 做向量检索，
避免 SQLite 后端全量扫描所有 chunk 的 O(N) 开销。

## 查询 DSL

```
本地搜索引擎检索知识库   # 中文短语（自动 bigram OR）
"distributed system"     # 英文短语
error AND (timeout OR retry)  # 布尔组合
ext:md type:note         # 字段过滤
filename:README.md       # 精确文件名
mtime:2025-01-01..2025-12-31  # 日期范围
sort:mtime 或 sort:size  # 按字段排序（tantivy 原生）
```

## 索引存储位置

默认跨平台数据目录：

| 平台 | 路径 |
|------|------|
| macOS | `~/Library/Application Support/lse/index/` |
| Windows | `%LOCALAPPDATA%\lse\index\` |
| Linux | `~/.local/share/lse/index/` |

可用 `--index-dir` 或环境变量 `LSE_DATA_DIR` 覆盖。

## 打包分发

```bash
# 本机（macOS/Windows 各自）
pip install pyinstaller
pyinstaller --clean --noconfirm packaging/lse.spec
bash packaging/build_release.sh      # 产出 tar.gz / zip 到 release/

# CI：推送 v* tag 触发双平台构建
git tag v0.1.0 && git push origin v0.1.0
```

产物：

- `dist/lse/` — 单目录可执行（直接分发）
- `release/lse-macos-arm64-v0.1.0.tar.gz` — macOS 便携包
- `release/lse-windows-amd64-v0.1.0.zip` — Windows 便携包（CI 产出）

## 性能

在本仓库真实 career 数据（~15.8k 文本文件）上实测：

| 指标 | 结果 |
|------|------|
| 全量索引（15,829 文件） | 6.4s（~115MB 索引） |
| 中文查询延迟 | 1–31ms |
| 查询吞吐 | 秒级返回百级匹配 |
| 打包体积 | 29MB（压缩 12MB） |

## 项目结构

```
lse/
├── config.py      # 配置常量（文件类型、排除规则、内存限制）
├── discovery.py   # 目录递归 + 文本文件识别
├── schema.py      # tantivy schema + tokenizer
├── indexer.py     # 全量/增量/重建索引（原子写入 + BLAKE2b 内容哈希）
├── searcher.py    # BM25 查询 + AST 驱动检索
├── tokenizer.py   # 代码与 CJK 双轨多流分词体系
├── query_ast.py   # 形式化 AST 递归下降语法解析器
├── resonance.py   # 连续流形波函数证据区间求解器
├── model.py       # 领域模型 (SearchHit, EvidenceSpan 等)
├── store.py       # 索引目录管理
├── cli.py         # CLI 入口
├── tests/         # pytest 单元测试套件
└── packaging/     # PyInstaller spec + 打包脚本 + CI
```

## 测试

```bash
uv run pytest tests/       # 20 例单元测试
```
