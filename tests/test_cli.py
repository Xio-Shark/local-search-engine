from __future__ import annotations

import json
from pathlib import Path
from lse.cli import main


def test_cli_index_and_search(tmp_path: Path, capsys):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    idx_dir = tmp_path / "index"

    (data_dir / "note.md").write_text("本地全文本搜索引擎 CLI 测试", encoding="utf-8")

    # 1. index
    ret_index = main(["--index-dir", str(idx_dir), "index", str(data_dir)])
    assert ret_index == 0
    captured = capsys.readouterr()
    assert "索引状态" in captured.out

    # 2. search text format
    ret_search = main(["--index-dir", str(idx_dir), "search", "全文本"])
    assert ret_search == 0
    captured = capsys.readouterr()
    assert "note.md" in captured.out
    assert "共 1 条匹配" in captured.out

    # 3. search json format
    ret_json = main(["--index-dir", str(idx_dir), "search", "-f", "json", "全文本"])
    assert ret_json == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["total_matches"] == 1
    assert data["hits"][0]["filename"] == "note.md"

    # 4. status
    ret_status = main(["--index-dir", str(idx_dir), "status"])
    assert ret_status == 0
    captured = capsys.readouterr()
    assert "文档数: 1" in captured.out

    # 5. update without paths (auto using last indexed roots)
    ret_update = main(["--index-dir", str(idx_dir), "update"])
    assert ret_update == 0
    captured = capsys.readouterr()
    assert "增量更新" in captured.out

    # 6. rebuild with --yes
    ret_rebuild = main(["--index-dir", str(idx_dir), "rebuild", "--yes", str(data_dir)])
    assert ret_rebuild == 0

def test_cli_ansi_highlight(tmp_path: Path, capsys):
    data_dir = tmp_path / "hl_data"
    data_dir.mkdir()
    idx_dir = tmp_path / "hl_index"

    (data_dir / "doc.md").write_text("高亮测试：美团外卖架构", encoding="utf-8")
    main(["--index-dir", str(idx_dir), "index", str(data_dir)])
    capsys.readouterr()

    main(["--index-dir", str(idx_dir), "search", "美团"])
    captured = capsys.readouterr()
    assert "\033[1;33m美团\033[0m" in captured.out
