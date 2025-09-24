@echo off
REM Cross-platform Windows launcher (.bat)
REM - Creates local venv if missing
REM - Installs deps from requirements.txt
REM - Runs fetch_figma_layout.py (reads .env automatically)

setlocal ENABLEDELAYEDEXPANSION
cd /d "%~dp0\.."

set PY=
where py >nul 2>nul && set PY=py
if not defined PY (
  where python >nul 2>nul && set PY=python
)
if not defined PY (
  where python3 >nul 2>nul && set PY=python3
)
if not defined PY (
  echo Python was not found. Please install Python 3 and re-run.
  exit /b 1
)

if not exist .venv (
  %PY% -m venv .venv
)

call .venv\Scripts\activate.bat

REM Upgrade pip quietly (non-fatal)
python -m pip install -U pip >nul 2>nul

if exist requirements.txt (
  pip install -r requirements.txt
) else (
  pip install requests python-dotenv
)

python fetch_figma_layout.py

endlocal

