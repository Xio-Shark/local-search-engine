from __future__ import annotations

from pathlib import Path
import pytest

from lse.indexer import IndexEngine


@pytest.fixture
def sample_corpus(tmp_path: Path):
    """创建临时测试文档集。"""
    docs_dir = tmp_path / "corpus"
    docs_dir.mkdir()

    # 1. 中文 Markdown
    f1 = docs_dir / "doc1.md"
    f1.write_text("基于 tantivy 的本地全文本搜索引擎，用于检索知识库与个人文档。", encoding="utf-8")

    # 2. 英文与代码
    f2 = docs_dir / "doc2.txt"
    f2.write_text("distributed system architecture error timeout retry C++ Go", encoding="utf-8")

    # 3. Python 代码
    f3 = docs_dir / "doc3.py"
    f3.write_text("def interview():\n    print('美团 简历 算法')\n    # error retry\n", encoding="utf-8")

    # 4. 单字与短语
    f4 = docs_dir / "README.md"
    f4.write_text("# 知识库\n单字测试：人，AI，全文检索，分布式系统。", encoding="utf-8")

    index_dir = tmp_path / "index"
    engine = IndexEngine(index_dir)
    engine.build([docs_dir])

    return {"docs_dir": docs_dir, "index_dir": index_dir, "engine": engine}
