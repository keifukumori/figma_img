#!/usr/bin/env bash
set -euo pipefail

# Cross-platform bash launcher (macOS/Linux)
# - Creates a local venv if missing
# - Installs deps from requirements.txt
# - Runs fetch_figma_layout.py (reads .env automatically)

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN=""
if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN=python3
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN=python
else
  echo "Python not found. Please install Python 3 and re-run." >&2
  exit 1
fi

# Setup venv
if [ ! -d .venv ]; then
  "$PYTHON_BIN" -m venv .venv
fi

# Activate venv
if [ -f .venv/bin/activate ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
else
  echo "Virtualenv activation script not found (.venv/bin/activate)." >&2
  exit 1
fi

# Install requirements
pip install -U pip >/dev/null 2>&1 || true
if [ -f requirements.txt ]; then
  pip install -r requirements.txt
else
  pip install requests python-dotenv
fi

# Run
exec python fetch_figma_layout.py

