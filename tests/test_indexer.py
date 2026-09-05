from __future__ import annotations

import time
from pathlib import Path
from lse.indexer import IndexEngine, _compute_content_hash
from lse.searcher import SearchEngine


def test_incremental_update_flow(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    idx_dir = tmp_path / "index"

    f1 = data_dir / "note.md"
    f1.write_text("第一版内容：初学者入门", encoding="utf-8")

    engine = IndexEngine(idx_dir)
    s1 = engine.build([data_dir])
    assert s1.doc_count == 1

    searcher = SearchEngine(idx_dir)
    assert searcher.search("初学者").total_matches == 1
    assert searcher.search("进阶").total_matches == 0

    # 1. 修改文件
    time.sleep(0.05)
    f1.write_text("第二版内容：高手进阶实战", encoding="utf-8")
    s2 = engine.update([data_dir])
    assert s2.doc_count == 1
    assert searcher.search("初学者").total_matches == 0
    assert searcher.search("进阶").total_matches == 1

    # 2. 新增文件
    f2 = data_dir / "extra.md"
    f2.write_text("附加文件内容", encoding="utf-8")
    s3 = engine.update([data_dir])
    assert s3.doc_count == 2

    # 3. 删除文件
    f2.unlink()
    s4 = engine.update([data_dir])
    assert s4.doc_count == 1
    assert searcher.search("附加文件").total_matches == 0


def test_multi_dir_preservation(tmp_path: Path):
    dir_a = tmp_path / "dir_a"
    dir_b = tmp_path / "dir_b"
    dir_a.mkdir()
    dir_b.mkdir()
    idx_dir = tmp_path / "index"

    (dir_a / "a.md").write_text("目录A文档内容", encoding="utf-8")
    (dir_b / "b.md").write_text("目录B文档内容", encoding="utf-8")

    engine = IndexEngine(idx_dir)
    # 同时索引 A 和 B
    engine.build([dir_a, dir_b])
    searcher = SearchEngine(idx_dir)
    assert searcher.search("目录A").total_matches == 1
    assert searcher.search("目录B").total_matches == 1

    # 仅增量更新 A，B 的文档决不能被删除
    engine.update([dir_a])
    assert searcher.search("目录A").total_matches == 1
    assert searcher.search("目录B").total_matches == 1


def test_gbk_encoding_reading(tmp_path: Path):
    data_dir = tmp_path / "gbk_data"
    data_dir.mkdir()
    idx_dir = tmp_path / "gbk_index"

    gbk_file = data_dir / "gbk_note.txt"
    gbk_file.write_bytes("美团架构师高频面试题解答".encode("gbk"))

    engine = IndexEngine(idx_dir)
    engine.build([data_dir])

    searcher = SearchEngine(idx_dir)
    res = searcher.search("架构师")
    assert res.total_matches == 1
    assert "gbk_note.txt" in res.hits[0].path


def test_extra_exclude(tmp_path: Path):
    data_dir = tmp_path / "exclude_data"
    data_dir.mkdir()
    skip_dir = data_dir / "skip_me"
    skip_dir.mkdir()
    idx_dir = tmp_path / "exclude_index"

    (data_dir / "keep.md").write_text("保留此文件", encoding="utf-8")
    (skip_dir / "drop.md").write_text("忽略此文件", encoding="utf-8")

    engine = IndexEngine(idx_dir)
    engine.build([data_dir], extra_exclude=["skip_me"])

    searcher = SearchEngine(idx_dir)
    assert searcher.search("保留").total_matches == 1
    assert searcher.search("忽略").total_matches == 0

def test_corrupted_file_handling(tmp_path: Path):
    data_dir = tmp_path / "corrupt_data"
    data_dir.mkdir()
    idx_dir = tmp_path / "corrupt_index"

    bad_file = data_dir / "bad.txt"
    bad_file.write_bytes(b"\xff\xfe\x00\x00\xaa\xbb\xcc\xdd")

    good_file = data_dir / "good.md"
    good_file.write_text("正常文本文件", encoding="utf-8")

    engine = IndexEngine(idx_dir)
    status = engine.build([data_dir])
    assert status.doc_count == 2

    searcher = SearchEngine(idx_dir)
    assert searcher.search("正常").total_matches == 1


def test_content_hash_and_atomic_state(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    idx_dir = tmp_path / "index"

    f = data_dir / "test.md"
    f.write_text("固定不变的文件内容", encoding="utf-8")
    orig_hash = _compute_content_hash(f)
    assert len(orig_hash) == 32

    engine = IndexEngine(idx_dir)
    status = engine.build([data_dir])
    assert status.doc_count == 1

    # 验证 state.json 原子写入与 content_hash 记录
    state_file = idx_dir / "state.json"
    assert state_file.exists()
    assert not (idx_dir / "state.json.tmp").exists()

    # 验证搜索结果包含 spans 证据区间
    searcher = SearchEngine(idx_dir)
    res = searcher.search("固定不变")
    assert res.total_matches == 1
    hit = res.hits[0]
    assert len(hit.spans) >= 1
    assert hit.spans[0].start_line == 1
    assert "固定不变" in hit.spans[0].text
