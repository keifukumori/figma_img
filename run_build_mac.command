#!/usr/bin/env bash
# Double-click launcher for macOS to build HTML/CSS from saved Figma JSON

set -euo pipefail

# Move to repo root (this script's directory)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Pick Python
if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo "[ERROR] Python 3 が見つかりません。https://www.python.org/downloads/ からインストールしてください。"
  read -p "Enterキーで終了します..." _
  exit 1
fi

echo "[INFO] 実行ディレクトリ: $SCRIPT_DIR"
echo "[INFO] .env を読み込んでビルドします (figma_02_build_from_json.py)"

set +e
"$PY" figma_02_build_from_json.py
STATUS=$?
set -e

echo
if [ $STATUS -eq 0 ]; then
  echo "[DONE] ビルドが完了しました。出力先は .env の OUTPUT_DIR を参照してください。"
else
  echo "[FAIL] ビルドに失敗しました (exit code $STATUS)。.env や Python の導入状況をご確認ください。"
fi

read -p "Enterキーで閉じます..." _

