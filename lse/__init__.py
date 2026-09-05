"""lse — 高性能现代本地全文搜索引擎。

具备：
- 连续流形波函数驱动的动态证据区间求解（消灭固定分块）
- 代码标识符 (camelCase/snake_case) 与 CJK 多粒度双轨分词体系
- 形式化 AST 递归下降语法解析器与自适应短语加权
- Tantivy Rust 原生底层索引与 BLAKE2b 内容指纹原子状态
- CLI: index / search / update / status / rebuild
"""

__version__ = "0.2.0"
