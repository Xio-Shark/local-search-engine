#!/usr/bin/env bash
# 跨平台打包脚本：PyInstaller 产出 → 平台安装包
#
# macOS:  dist/lse/  →  lse-macos-arm64.tar.gz（或 .dmg）
# Windows: dist/lse/ →  lse-windows-amd64.zip
#
# 用法: bash packaging/build_release.sh [version]
set -euo pipefail

VERSION="${1:-0.2.0}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIST="$ROOT/dist"
OUT="$ROOT/release"

command -v pyinstaller >/dev/null 2>&1 || {
    echo "缺少 pyinstaller，请先: uv pip install pyinstaller"
    exit 1
}

echo "==> 构建 PyInstaller 产物"
pyinstaller --clean --noconfirm "$ROOT/packaging/lse.spec"

mkdir -p "$OUT"

if [[ "$(uname -s)" == "Darwin" ]]; then
    ARCH="$(uname -m)"          # arm64 或 x86_64
    echo "==> macOS ($ARCH) 打包"
    tar -czf "$OUT/lse-macos-$ARCH-v$VERSION.tar.gz" -C "$DIST" lse
    # 可选 dmg：需要 hdiutil
    # hdiutil create -volname "lse" -srcfolder "$DIST/lse" -ov -format UDZO \
    #     "$OUT/lse-macos-$ARCH-v$VERSION.dmg"
    echo "✅ 产物: $OUT/lse-macos-$ARCH-v$VERSION.tar.gz"
else
    echo "==> Windows 打包"
    powershell.exe -NoProfile -Command \
        "Compress-Archive -Path '$DIST\\lse\\*' -DestinationPath '$OUT\\lse-windows-amd64-v$VERSION.zip'"
    echo "✅ 产物: $OUT/lse-windows-amd64-v$VERSION.zip"
fi

echo "==> 完成"
