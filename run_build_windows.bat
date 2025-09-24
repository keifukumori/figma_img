@echo off
REM Double-click launcher for Windows to build HTML/CSS from saved Figma JSON
setlocal
cd /d "%~dp0"

echo [INFO] 実行ディレクトリ: %cd%
echo [INFO] .env を読み込んでビルドします (figma_02_build_from_json.py)

REM Prefer Python launcher
where py >nul 2>nul
if %ERRORLEVEL%==0 (
  py -3 figma_02_build_from_json.py
) else (
  where python >nul 2>nul
  if %ERRORLEVEL%==0 (
    python figma_02_build_from_json.py
  ) else (
    echo [ERROR] Python 3 が見つかりません。https://www.python.org/ からインストールしてください。
    pause
    exit /b 1
  )
)

set ERR=%ERRORLEVEL%
echo.
if %ERR%==0 (
  echo [DONE] ビルドが完了しました。出力先は .env の OUTPUT_DIR を参照してください。
) else (
  echo [FAIL] ビルドに失敗しました (exit code %ERR%)。.env や Python の導入状況をご確認ください。
)

pause
endlocal

