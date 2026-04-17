# 高性能本地搜索引擎

基于 Java 21 + Gradle 的高性能本地文件全文搜索引擎，不依赖 Lucene 等搜索框架。

## 功能特性

- 🔍 **全文检索**：支持倒排索引 + 位置索引
- 📊 **BM25 评分**：基于 BM25 算法的相关性排序
- 📝 **自定义 Query DSL**：支持布尔、短语、前缀、字段过滤、范围查询
- 🚀 **增量更新**：基于文件 mtime/size 的增量索引
- 💾 **崩溃恢复**：WAL（预写日志）保证数据不丢失
- 🔄 **段合并**：Tiered Merge 策略优化查询性能
- 🎨 **CLI 交互**：支持 index/search/status/rebuild 四子命令

## 技术栈

- **Java 21 LTS**
- **Gradle 8.6** (Kotlin DSL)
- **SQLite**：文档元数据存储
- **picocli**：命令行接口
- **Jackson**：JSON 序列化
- **Logback**：日志管理
- **JMH**：性能基准测试
- **JaCoCo**：代码覆盖率

## 快速开始

### 1. 构建项目

```bash
./gradlew build
```

### 1.1 启动图形界面（GUI）

```bash
./gradlew run --args="--gui"
```

### 2. 构建索引

```bash
./gradlew run --args="index /path/to/documents"
```

### 3. 搜索查询

```bash
# 简单查询
./gradlew run --args='search "java programming"'

# 短语查询
./gradlew run --args='search "\"distributed system\""'

# 布尔查询
./gradlew run --args='search "error AND (timeout OR retry)"'

# 字段过滤
./gradlew run --args='search "ext:md type:code"'

# 范围查询
./gradlew run --args='search "mtime:2025-01-01..2025-12-31"'
```

### 4. 查看索引状态

```bash
./gradlew run --args="status"
```

### 5. 重建索引

```bash
./gradlew run --args="rebuild --yes /path/to/documents"
```

## 使用说明

### 1) 启动方式

- CLI：`./gradlew run --args="--help"`
- GUI：`./gradlew run --args="--gui"`

### 2) GUI 操作流程

1. 顶部配置 `索引目录` 与 `线程数`。
2. 在“索引”页签填入源路径（每行一个目录或文件），点击“构建/增量索引”。
3. 在“搜索”页签输入查询语句并执行搜索。
4. 可使用“文件名快速检索”直接按文件名搜索（自动转为 `filename:"xxx"`）。
5. 在“状态”页签点击“刷新状态”查看文档数、词条数、段数与索引大小。

### 3) 查询示例

- 全文：`java programming`
- 短语：`"distributed system"`
- 布尔：`error AND (timeout OR retry)`
- 扩展名：`ext:md`
- 类型：`type:note`
- 路径前缀：`path:C:/work/docs`
- 文件名：`filename:PROJECT_SPEC.md`
- 直接文件名：`PROJECT_SPEC.md`（会自动按文件名过滤）

### 4) 结果高亮

- CLI 中高亮由 ANSI 控制序列实现。
- GUI 中高亮由富文本渲染实现（黄色背景），用于直观看到命中片段。

## 分发与安装包（Windows EXE）

### 1) 先决条件

- Java 21（已包含 `jpackage`）。
- `JAVA_HOME` 正确指向 JDK 目录。
- 若要生成 `exe` 安装包，需安装 WiX Toolset（jpackage 在 Windows 生成 exe 的依赖）。

### 2) 生成产物

```bash
# 生成可分发 app-image（不依赖 WiX）
./gradlew packageAppImage

# 生成可直接给用户下载的便携版 zip（推荐）
./gradlew packagePortableZip

# 生成 Windows EXE 安装包（依赖 WiX）
./gradlew packageExe
```

产物路径：

- app-image（推荐直接分发）：`build/distributions/appimage/LocalSearchEnginePortable/LocalSearchEnginePortable.exe`
- 便携版 zip（推荐分发）：`build/distributions/LocalSearchEnginePortable-1.0.0.zip`
- exe 安装包：`build/distributions/`（需 WiX 3.x）

注意：`packageExe` 依赖 WiX 3.x（需要 `candle.exe`、`light.exe`）。若缺失该环境，可先分发 app-image 目录（将整个目录打包 zip 给用户）。

### 3) 分发建议

- 需要“开箱即用”安装体验：分发 `packageExe` 生成的 `.exe`。
- 需要免安装绿色版：优先分发 `packagePortableZip` 生成的 zip。

## Query DSL 语法

```
hello world                    # 隐式 AND
"distributed system"           # 短语查询
config*                        # 前缀匹配
error AND (timeout OR retry)   # 布尔组合
-draft NOT internal            # 排除
ext:md type:note               # 字段过滤
filename:readme.md             # 按文件名过滤
mtime:2025-01-01..2025-12-31   # 日期范围
size:10KB..5MB                 # 大小范围
path:/work/src                 # 路径前缀
sort:mtime                     # 按修改时间排序
```

说明：当你直接输入类似 `readme.md` 这种带扩展名的单词项时，系统会自动按文件名过滤处理。

## 性能指标

- **JMH 基准测试**：内置 OpenJDK JMH 基准测试框架
  - 索引吞吐：1,000 文件批量索引吞吐量（ops/s）
  - 查询延迟：10,000 文件规模下的简单 / 短语 / 布尔查询平均延迟（ms）
- **性能目标**：面向 10 万文件、5GB 文本量持续度量与优化
- **崩溃恢复**：WAL 保证索引元数据一致性与可恢复到最近提交点

## 项目结构

```
local-search-engine/
├── src/
│   ├── main/java/com/localengine/
│   │   ├── cli/          # CLI 层
│   │   ├── config/       # 配置
│   │   ├── document/     # 文档模型
│   │   ├── highlight/    # 高亮摘要
│   │   ├── index/        # 索引层
│   │   ├── query/        # 查询引擎
│   │   ├── scoring/      # 评分算法
│   │   ├── storage/      # 存储层
│   │   └── text/         # 分词器
│   ├── test/             # 测试
│   └── jmh/              # JMH 基准测试
├── docs/                 # 设计文档
├── build.gradle.kts      # Gradle 配置
└── README.md            # 本文件
```

## 测试

```bash
# 运行单元测试
./gradlew test

# 生成覆盖率报告
./gradlew jacocoTestReport

# 运行 JMH 基准测试
./gradlew jmh
```

## 许可证

MIT License
