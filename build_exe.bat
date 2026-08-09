@echo off
rem Build the WarCounsel executable. Two variants:
rem
rem   build_exe.bat          -> dist\WarCounsel.exe, one file, NO screen OCR
rem   build_exe.bat heavy    -> dist\WarCounsel\, a FOLDER, WITH screen OCR
rem
rem LLM counsel is in both, so the settings panel's API key field works.
rem The OCR stack is 204 MB (see requirements-heavy.txt for the breakdown),
rem which is why it is a separate download -- and why the heavy one is
rem --onedir: a --onefile bundle re-extracts itself on EVERY launch, so
rem 200 MB of payload would tax every start for everyone.
rem Prereqs on the BUILD machine only: Python 3.11+, Node 18+.
rem NOTE: pass args through the relaunch, or "heavy" is lost when the script
rem re-enters under cmd /k.
if not "%~1"=="stay" (cmd /k ""%~f0" stay %*" & exit /b)
cd /d %~dp0

set "HEAVY="
if /i "%~2"=="heavy" set "HEAVY=1"
if defined HEAVY (echo === HEAVY build: screen OCR included ===) else (echo === standard build: no screen OCR ===)

echo [1/5] Python build deps + pyinstaller + pywebview...
rem `python -m pip`, not bare `pip`: pip's console script lives in a separate
rem PATH entry, so a working python routinely has an unreachable pip.
if defined HEAVY (
  python -m pip install -r requirements-heavy.txt pyinstaller pywebview || (echo pip failed & exit /b 1)
) else (
  python -m pip install -r requirements-lite.txt pyinstaller pywebview || (echo pip failed & exit /b 1)
)

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
if defined HEAVY goto heavybuild
pyinstaller --noconfirm --onefile --windowed --name WarCounsel ^
  --add-data "frontend/out;frontend/out" ^
  --add-data "data/eqlbuilds;data/eqlbuilds" ^
  --add-data "class_guides;class_guides" ^
  --add-data "backend/spell_lines.json;backend" ^
  --add-data "backend/zem_levels.wiki;backend" ^
  --add-data "maps;maps" ^
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
goto built

:heavybuild
rem Same bundle, minus the OCR excludes, plus --onedir. numpy stays in (the
rem OCR engine needs it), and torch/matplotlib/langgraph stay OUT -- nothing
rem imports them and they are enormous.
rem
rem --collect-all on the OCR package is REQUIRED, not tidiness: rapidocr's
rem models and default_models.yaml are package DATA, and PyInstaller bundles
rem only code unless told otherwise. Without it the build succeeds, the
rem import succeeds, and the engine dies with FileNotFoundError the first
rem time someone enables screen reading. The package renamed itself between
rem Python versions (rapidocr_onnxruntime <=3.12, rapidocr on 3.13+), so ask
rem which one is actually installed rather than guessing.
set "OCRPKG="
for /f "usebackq delims=" %%m in (`python -c "import importlib.util as u;print('rapidocr' if u.find_spec('rapidocr') else ('rapidocr_onnxruntime' if u.find_spec('rapidocr_onnxruntime') else ''))"`) do set "OCRPKG=%%m"
if not defined OCRPKG (echo No rapidocr installed - run pip install -r requirements-heavy.txt & exit /b 1)
echo   OCR package: %OCRPKG%
pyinstaller --noconfirm --onedir --windowed --name WarCounsel ^
  --collect-all %OCRPKG% ^
  --add-data "frontend/out;frontend/out" ^
  --add-data "data/eqlbuilds;data/eqlbuilds" ^
  --add-data "class_guides;class_guides" ^
  --add-data "backend/spell_lines.json;backend" ^
  --add-data "backend/zem_levels.wiki;backend" ^
  --add-data "maps;maps" ^
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
  --exclude-module matplotlib --exclude-module torch ^
  --exclude-module langgraph ^
  run_companion.py || (echo PyInstaller failed & exit /b 1)

rem opencv ships a 29.4 MB video codec DLL. OCR reads still screenshots, so
rem nothing can ever call it. CI asserts it is gone AND that OCR still
rem imports, because deleting the wrong file would fail soft.
for /r "dist\WarCounsel" %%f in (opencv_videoio_ffmpeg*.dll) do (
  echo   dropping %%~nxf ^(%%~zf bytes, video codecs - OCR reads still images^)
  del /q "%%f"
)

:built
if defined HEAVY (
  echo [5/5] Done -^> dist\WarCounsel\   ZIP THE FOLDER, not just the exe:
  echo      it is --onedir, so WarCounsel.exe needs its siblings to run.
) else (
  echo [5/5] Done -^> dist\WarCounsel.exe
  echo      Ship that single file. Users need nothing installed.
)
echo First run creates data\ beside it (or in %%LOCALAPPDATA%%\WarCounsel when
echo that folder is read-only) and finds the game via the Windows registry.
