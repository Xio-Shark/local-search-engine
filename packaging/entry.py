"""PyInstaller 打包入口：显式导入 lse.cli，避免相对导入问题。"""

from lse.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
