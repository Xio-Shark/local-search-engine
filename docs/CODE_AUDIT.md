# 代码完备性与安全性检查报告

## 检查范围
- 构建与测试可执行性
- 关键模块完整性（索引层、查询层、CLI）
- 输入边界与资源消耗风险

## 结论摘要
1. **当前仓库不完整，无法直接构建测试**：存在引用 `com.localengine.index.*` 但源码目录中缺失 `src/main/java/com/localengine/index`，同时 Gradle Wrapper 的 `gradle-wrapper.jar` 缺失。
2. **构建配置存在外部依赖风险**：`me.champeau.jmh` 插件在当前环境解析失败，导致 `gradle test` 在配置阶段即中断。
3. **CLI 输入边界原先不足**：线程数、查询长度、结果上限缺乏强约束，存在资源耗尽风险。本次已加入安全边界与参数收敛。

## 发现详情

### 1) 完备性问题（阻塞构建）
- 缺少索引层源码目录：项目中大量类导入 `com.localengine.index.IndexManager` / `DiskSegment` / `IndexStatus`，但仓库无对应源码目录，属于结构性缺失。
- `./gradlew test` 失败：`org.gradle.wrapper.GradleWrapperMain` 找不到，说明 wrapper JAR 缺失。
- 使用系统 `gradle test` 继续验证时，JMH 插件解析失败，构建在配置阶段终止。

### 2) 安全性问题（已修复）
- `--threads` 可传入异常值（<=0 或极大值），可能导致性能异常或资源争抢。
- `search` 的 `--limit` 缺少上限控制，可能导致单次查询返回过大集合。
- 查询字符串未限制长度，极端输入会增大解析与执行耗时。

## 已实施修复
- 新增安全常量：
  - `MAX_INDEX_THREADS = 64`
  - `MAX_QUERY_LENGTH = 2048`
  - `MAX_SEARCH_LIMIT = 1000`
- 在 `MainCommand` 增加参数净化：
  - `resolveThreadCount()`：非法值回退、过大值限流
  - `sanitizeSearchLimit()`：负值归零、超限截断
  - `sanitizeQuery()`：长度超限时拒绝执行
- `index/status/search/rebuild` 子命令统一走线程数净化。
- `search` 子命令统一使用净化后的 `query` 与 `limit`。

## 建议后续动作（高优先）
1. 补齐 `src/main/java/com/localengine/index` 实现，或移除相关引用并调整功能范围。
2. 提交 `gradle/wrapper/gradle-wrapper.jar`，保证 `./gradlew` 可在 CI 与新环境直接运行。
3. 对 JMH 插件做可选化（如以 profile/task 开关控制），避免日常 `test` 被插件解析阻塞。
4. 增加参数边界相关单测（threads/limit/query-length）并在 CI 强制执行。
