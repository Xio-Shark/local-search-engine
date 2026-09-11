"""查询期可配置选项。

这些开关用于消融检索质量与延迟，默认值来自公开数据集上的 dev split 调参：

- BEIR SciFact qrels/train.tsv（809 条）
- CoIR CosQA data/valid（500 条）

最终 test split 只用于报告，不参与默认值选择。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .config import DEFAULT_SEARCH_FIELDS


@dataclass(frozen=True)
class SearchOptions:
    """一次检索的查询编译与字段选择策略。

    Attributes:
        query_mode: ``auto`` / ``natural`` / ``structured``。``auto`` 对短
            关键词查询保留 AND 精度，对长句 / claim 使用自然语言加权 OR；
            另外两个值分别强制走对应路径。
        natural_query: 旧版显式开关；``None`` 表示使用 ``query_mode``。
            保留它用于兼容已有调用方与消融脚本。
        idf_power: 自然语言查询下每个词项的 BM25 IDF 权重指数；设 ``None``
            关闭词项加权。dev split 调参值为 0.25。
        concept_expansion: 是否追加项目 / 基础概念图谱中的双向映射词项
            （仅扩展召回，自然查询与结构化查询均会生效）。
        query_fields: 传给 Tantivy query parser 的默认搜索字段。
        conjunction_by_default: 结构化查询的默认连接语义（默认 AND）。
    """

    query_mode: Literal["auto", "natural", "structured"] = "auto"
    natural_query: bool | None = None
    idf_power: float | None = 0.25
    concept_expansion: bool = True
    query_fields: tuple[str, ...] = DEFAULT_SEARCH_FIELDS
    conjunction_by_default: bool = True
