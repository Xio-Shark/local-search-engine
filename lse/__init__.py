"""lse — 本地全文本搜索引擎（tantivy 后端）。

面向 career 知识库的本地检索：
- 索引目录/文件（含中文 bigram 分词）
- BM25 相关性排序 + 高亮 snippet
- CLI: index / search / status / rebuild
- 作为 Python 库被 rag 等调用
"""

__version__ = "0.1.0"
