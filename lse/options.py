"""查询期可配置选项。

这些开关用于消融检索质量与延迟，默认值来自公开数据集上的 dev split 调参：

- BEIR SciFact qrels/train.tsv（809 条）+ NFCorpus qrels/train.tsv（2590 条）
- BEIR FiQA qrels/train.tsv（5500 条）
- CoIR CosQA data/valid（500 条）

最终 test split 只用于报告，不参与默认值选择；短查询连接语义的选择由
``bench/bench_query_policy.py`` 在 dev split 上扫描阈值网格得到。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .config import DEFAULT_SEARCH_FIELDS

# auto 模式的短查询阈值：内容词元数 <= 该值的纯词项查询走结构化 AND。
# 0 表示 auto 不再对纯词项查询使用 AND（等于 natural），这是
# bench/bench_query_policy.py 在四个 dev split 上的选择：阈值 0 在
# SciFact train / NFCorpus train / FiQA train / CosQA valid 上最优或并列最优，
# 任何 >0 的阈值都只会在 NFCorpus 上掉分（见 bench/PUBLIC_EVAL.md）。
DEFAULT_AUTO_STRUCTURED_MAX_TERMS = 0


@dataclass(frozen=True)
class SearchOptions:
    """一次检索的查询编译与字段选择策略。

    Attributes:
        query_mode: ``auto`` / ``natural`` / ``structured``。``auto`` 对短
            关键词查询保留 AND 精度，对长句 / claim 使用自然语言加权 OR；
            另外两个值分别强制走对应路径。
        auto_structured_max_terms: ``auto`` 模式下走结构化 AND 的纯词项查询
            内容词元上限；``0`` 表示 auto 不再对纯词项查询使用 AND（等价于
            natural）。dev split 调参值见 ``DEFAULT_AUTO_STRUCTURED_MAX_TERMS``。
        natural_query: 旧版显式开关；``None`` 表示使用 ``query_mode``。
            保留它用于兼容已有调用方与消融脚本。
        idf_power: 自然语言查询下每个词项的 BM25 IDF 权重指数；设 ``None``
            关闭词项加权。dev split 调参值为 0.25。
        concept_expansion: 是否追加项目 / 基础概念图谱中的双向映射词项
            （仅扩展召回，自然查询与结构化查询均会生效）。
        query_fields: 传给 Tantivy query parser 的默认搜索字段。
        conjunction_by_default: 结构化查询的默认连接语义（默认 AND）。
        include_spans: 是否读取正文并计算 evidence span / snippet。设为
            ``False`` 时只返回排序所需的文件元数据，用于 Agent 预筛与
            原生 BM25 同口径的延迟基准；排序结果本身不受影响。
    """

    query_mode: Literal["auto", "natural", "structured"] = "auto"
    natural_query: bool | None = None
    auto_structured_max_terms: int = DEFAULT_AUTO_STRUCTURED_MAX_TERMS
    idf_power: float | None = 0.25
    concept_expansion: bool = True
    query_fields: tuple[str, ...] = DEFAULT_SEARCH_FIELDS
    conjunction_by_default: bool = True
    include_spans: bool = True

    def __post_init__(self) -> None:
        if self.auto_structured_max_terms < 0:
            raise ValueError("auto_structured_max_terms must be >= 0")
