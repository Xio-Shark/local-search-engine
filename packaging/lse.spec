# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec：跨平台构建 lse 单文件/单目录二进制。

用法（macOS / Windows 均适用）：
    pyinstaller packaging/lse.spec

产物：
    dist/lse/                    # 单目录（推荐分发）
    dist/lse(.exe)               # 单文件（可选）
"""

from pathlib import Path

project_root = Path(SPECPATH).parent

a = Analysis(
    [str(project_root / "packaging" / "entry.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=[],
    hiddenimports=[
        "tantivy",
        "lse.tokenizer",
        "lse.query_ast",
        "lse.resonance",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "unittest", "pydoc"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="lse",
    console=True,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="lse",
)
