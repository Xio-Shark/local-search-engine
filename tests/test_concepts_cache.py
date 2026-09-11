"""概念图缓存与动态概念规模控制测试。"""

from __future__ import annotations

from pathlib import Path

from lse.concepts import (
    AdaptiveConceptMiner,
    clear_concepts_cache,
    load_project_concepts,
    save_project_concepts,
)
from lse.model import IndexableFile


def test_load_project_concepts_uses_mtime_keyed_cache(tmp_path: Path) -> None:
    clear_concepts_cache()
    save_project_concepts(tmp_path, {"结算": ["settlement", "checkout"]})
    first = load_project_concepts(tmp_path)
    assert "checkout" in first["结算"]

    # 同一文件、同一 mtime/size 时直接命中缓存对象
    assert load_project_concepts(tmp_path) is first

    # 重写概念图后缓存失效，并加载到新内容
    save_project_concepts(tmp_path, {"鉴权": ["auth", "jwt"]})
    second = load_project_concepts(tmp_path)
    assert second is not first
    assert "鉴权" in second
    clear_concepts_cache()


def test_adaptive_concept_miner_caps_entries() -> None:
    files = [
        IndexableFile(
            path=Path(f"/repo/root_component{index}/alpha_{index}/trainer.py"),
            extension=".py",
            size_bytes=100,
            mtime=1.0,
            doc_type="code",
        )
        for index in range(20)
    ]
    graph = AdaptiveConceptMiner().mine(files, max_entries=5)
    assert 0 < len(graph) <= 5
