"""查询期可配置选项。

这些开关用于消融检索质量与延迟，默认值来自公开数据集上的 dev split 调参：

- BEIR SciFact qrels/train.tsv（809 条）
- CoIR CosQA data/valid（500 条）

最终 test split 只用于报告，不参与默认值选择。
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import DEFAULT_SEARCH_FIELDS


@dataclass(frozen=True)
class SearchOptions:
    """一次检索的查询编译与字段选择策略。

    Attributes:
        natural_query: 对纯词项自然语言查询启用 lse 分词器重写，并编译为
            字段内的 OR-of-terms 查询。结构化语法（字段过滤、大写布尔
            操作符、引号短语、排序指令、通配符 ``*``）完全不受影响。
        idf_power: 自然语言查询下每个词项的 BM25 IDF 权重指数；设 ``None``
            关闭词项加权。dev split 调参值为 0.25。
        concept_expansion: 是否追加项目 / 基础概念图谱中的双向映射词项
            （仅扩展召回，自然查询与结构化查询均会生效）。
        query_fields: 传给 Tantivy query parser 的默认搜索字段。
        conjunction_by_default: 结构化查询的默认连接语义（默认 AND）。
    """

    natural_query: bool = True
    idf_power: float | None = 0.25
    concept_expansion: bool = True
    query_fields: tuple[str, ...] = DEFAULT_SEARCH_FIELDS
    conjunction_by_default: bool = True
