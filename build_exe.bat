@echo off
rem Build the single-file WarCounsel executable. No OCR (that would pull in
rem onnxruntime + numpy); LLM counsel IS included so the settings panel's API
rem key field works. Produces dist\WarCounsel.exe with no runtime deps.
rem Prereqs on the BUILD machine only: Python 3.11+, Node 18+.
if not "%~1"=="stay" (cmd /k ""%~f0" stay" & exit /b)
cd /d %~dp0

echo [1/5] Python build deps (lite set + pyinstaller + pywebview)...
pip install -r requirements-lite.txt pyinstaller pywebview || (echo pip failed & exit /b 1)

echo [2/5] Building the static UI...
pushd frontend
call npm install || (echo npm install failed & popd & exit /b 1)
set NEXT_EXPORT=1
call npm run build || (echo UI build failed & popd & exit /b 1)
set NEXT_EXPORT=
popd

echo [3/5] Bundling the eqlbuilds data snapshot (exact spell/AA levels)...
if not exist data\eqlbuilds mkdir data\eqlbuilds
if exist "%MCP_SERVER_DIR%\dist\data\eqlbuilds\classes.json" (
  copy /y "%MCP_SERVER_DIR%\dist\data\eqlbuilds\classes.json" data\eqlbuilds\ >nul
) else (
  echo   ^(no MCP snapshot found - the exe will fall back to wiki HTTP for levels^)
)

echo [4/5] Running PyInstaller...
rem Version lives INSIDE the exe (Properties -> Details), not in its
rem filename: the download name has to stay stable for GitHub's
rem /releases/latest/download/ permalink and for desktop shortcuts.
python scripts\make_version_file.py || (echo version file failed & exit /b 1)
rem --add-data entries are READ-ONLY assets resolved through paths.bundle_path().
rem Writable state never lives here: a one-file bundle is a temp dir that is
rem thrown away on exit (see backend/paths.py).
pyinstaller --noconfirm --onefile --windowed --name WarCounsel ^
  --add-data "frontend/out;frontend/out" ^
  --add-data "data/eqlbuilds;data/eqlbuilds" ^
  --add-data "class_guides;class_guides" ^
  --add-data "backend/spell_lines.json;backend" ^
  --add-data "backend/zem_levels.wiki;backend" ^
  --version-file build/version_info.txt ^
  --icon docs/warcounsel.ico ^
  --collect-submodules backend ^
  --hidden-import uvicorn.logging --hidden-import uvicorn.protocols ^
  --hidden-import uvicorn.protocols.http.auto ^
  --hidden-import uvicorn.protocols.http.h11_impl ^
  --hidden-import uvicorn.protocols.websockets.auto ^
  --hidden-import uvicorn.protocols.websockets.websockets_impl ^
  --hidden-import uvicorn.lifespan.on ^
  --hidden-import uvicorn.loops.asyncio ^
  --hidden-import pystray._win32 ^
  --exclude-module numpy --exclude-module matplotlib ^
  --exclude-module rapidocr --exclude-module rapidocr_onnxruntime ^
  --exclude-module mss --exclude-module cv2 --exclude-module torch ^
  --exclude-module langgraph --exclude-module onnxruntime ^
  run_companion.py || (echo PyInstaller failed & exit /b 1)

echo [5/5] Done -^> dist\WarCounsel.exe
echo Ship that single file. Users need nothing installed. First run creates
echo data\ beside it (or in %%LOCALAPPDATA%%\WarCounsel when that folder is
echo read-only) and finds the game via the Windows registry.
