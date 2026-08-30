"""tantivy 索引 schema 与 tokenizer 注册。

字段：
- path      完整路径（stored + fast，raw 精确匹配，供命中回显）
- filename  文件名（stored，raw 精确匹配，支持 filename: 快速定位）
- extension 后缀（stored + fast，raw 匹配，扩展名过滤）
- content   全文内容（stored + indexed，ngram(2,2) 分词，支持中文 bigram）
- size      字节大小（stored + fast，可排序）
- mtime     修改时间（stored + fast，datetime 存储，可排序）
- doc_type  类型标签（stored + fast）
"""

from __future__ import annotations

from datetime import datetime

import tantivy

TOKENIZER_CJK = "lse_cjk_bigram"
TOKENIZER_RAW = "lse_raw"


def build_schema() -> tantivy.Schema:
    """构建 schema。

    - content 使用 ngram(2,2) 支持中文 bigram
    - 元数据字段（path/filename/extension/doc_type）用 raw 分词，
      整值精确匹配，支持 ext:md / filename:note2.md 等字段过滤
    - 注意：text 字段不要同时 fast=True，否则 fast 字段会用
      with_tokenizer 要求注册 fast field tokenizer，导致 writer 报错。
    """
    builder = tantivy.SchemaBuilder()
    builder.add_text_field("path", stored=True, tokenizer_name=TOKENIZER_RAW)
    builder.add_text_field("filename", stored=True, tokenizer_name=TOKENIZER_RAW)
    builder.add_text_field("extension", stored=True, tokenizer_name=TOKENIZER_RAW)
    builder.add_text_field("content", stored=True, tokenizer_name=TOKENIZER_CJK)
    builder.add_integer_field("size", stored=True, fast=True)
    builder.add_date_field("mtime", stored=True, fast=True)
    builder.add_text_field("doc_type", stored=True, tokenizer_name=TOKENIZER_RAW)
    return builder.build()


def register_tokenizers(index: tantivy.Index) -> None:
    """在索引上注册自定义 tokenizer（必须在写入文档前调用）。"""
    cjk_analyzer = tantivy.TextAnalyzerBuilder(
        tantivy.Tokenizer.ngram(2, 2, prefix_only=False)
    ).build()
    index.register_tokenizer(TOKENIZER_CJK, cjk_analyzer)
    raw_analyzer = tantivy.TextAnalyzerBuilder(tantivy.Tokenizer.raw()).build()
    index.register_tokenizer(TOKENIZER_RAW, raw_analyzer)


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
