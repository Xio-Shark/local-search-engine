"""tantivy 索引 schema 与 tokenizer 注册。

字段：
- path      完整路径（stored + fast，raw 精确匹配，供命中回显）
- filename  文件名（stored，raw 精确匹配，支持 filename: 快速定位）
- extension 后缀（stored + fast，raw 匹配，扩展名过滤）
- content   全文内容（stored + indexed，多粒度分词倒排存储）
- size      字节大小（stored + fast，可排序与范围过滤）
- mtime     修改时间（stored + fast，datetime 存储，可排序与范围过滤）
- doc_type  类型标签（stored + fast）
"""

from __future__ import annotations

from datetime import datetime

import tantivy

TOKENIZER_CONTENT = "lse_content"
TOKENIZER_RAW = "lse_raw"
TOKENIZER_RAW_LOWER = "lse_raw_lower"
TOKENIZER_CJK = TOKENIZER_CONTENT  # 兼容别名


def build_schema() -> tantivy.Schema:
    """构建 schema。

    - content 采用 stored=False，基于磁盘原文实现零存储冗余，以 whitespace+lowercase 接收多流词元倒排
    - filename / extension / doc_type 用 raw + lowercase 分词，整值不区分大小写匹配
    - path 保持 raw 原生大小写并存储，供命中回显与零拷贝原文直读
    - size / mtime 开启 fast=True 与 indexed=True，支持范围过滤与快速排序
    """
    builder = tantivy.SchemaBuilder()
    builder.add_text_field("path", stored=True, tokenizer_name=TOKENIZER_RAW)
    builder.add_text_field("filename", stored=True, tokenizer_name=TOKENIZER_RAW_LOWER)
    builder.add_text_field("extension", stored=True, tokenizer_name=TOKENIZER_RAW_LOWER)
    builder.add_text_field("content", stored=False, tokenizer_name=TOKENIZER_CONTENT)
    builder.add_integer_field("size", stored=True, fast=True, indexed=True)
    builder.add_date_field("mtime", stored=True, fast=True, indexed=True)
    builder.add_text_field("doc_type", stored=True, tokenizer_name=TOKENIZER_RAW_LOWER)
    return builder.build()


def register_tokenizers(index: tantivy.Index) -> None:
    """在索引上注册自定义 tokenizer（必须在写入文档与查询解析前调用）。"""
    # content 使用 whitespace + lowercase，接收 Python 预先解离的代码与语义词元流
    content_analyzer = (
        tantivy.TextAnalyzerBuilder(tantivy.Tokenizer.whitespace())
        .filter(tantivy.Filter.lowercase())
        .build()
    )
    index.register_tokenizer(TOKENIZER_CONTENT, content_analyzer)
    index.register_tokenizer("lse_cjk", content_analyzer)

    raw_analyzer = tantivy.TextAnalyzerBuilder(tantivy.Tokenizer.raw()).build()
    index.register_tokenizer(TOKENIZER_RAW, raw_analyzer)

    raw_lower_analyzer = (
        tantivy.TextAnalyzerBuilder(tantivy.Tokenizer.raw())
        .filter(tantivy.Filter.lowercase())
        .build()
    )
    index.register_tokenizer(TOKENIZER_RAW_LOWER, raw_lower_analyzer)


def to_epoch_mtime(mtime: float) -> datetime:
    """epoch 秒 → datetime（tantivy date 字段用）。"""
    return datetime.fromtimestamp(mtime)


def doc_from_indexable(indexable) -> tantivy.Document:
    """把 IndexedDoc 转换为 tantivy Document。"""
    return tantivy.Document.from_dict(
        {
            "path": indexable.path,
            "filename": indexable.filename,
            "extension": indexable.extension,
            "content": indexable.content,
            "size": indexable.size,
            "mtime": indexable.mtime,
            "doc_type": indexable.doc_type,
        }
    )
