#!/bin/bash
# macOS Finder double‑click launcher
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="python3"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  PYTHON_BIN=python
fi

if [ ! -d .venv ]; then
  "$PYTHON_BIN" -m venv .venv
fi

source .venv/bin/activate
python -m pip install -U pip >/dev/null 2>&1 || true
if [ -f requirements.txt ]; then
  pip install -r requirements.txt
else
  pip install requests python-dotenv
fi

exec python fetch_figma_layout.py

