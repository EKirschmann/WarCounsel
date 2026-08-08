@echo off
rem WarCounsel launcher - backend (:8000) + frontend (:3000).
rem Default = production mode (fast, light). It auto-rebuilds the UI when
rem source changed since the last build, so you never see a stale version.
rem Developers iterating rapidly: start_companion.bat dev  (hot reload)
cd /d %~dp0

rem --- make python/node reachable even when the installers left them off PATH
rem The Microsoft Store stub named python.exe is on PATH by DEFAULT and exits
rem 0 while doing nothing, so "is python on PATH" is not the question -- "does
rem it print its own path" is. See install_companion.bat for the full story.
rem Everything set here is inherited by the two windows started below.
call :ensurepy
call :ensurenode

if /i "%~1"=="dev" goto devmode

rem --- rebuild the production UI only if source is newer than the last build
set NEED=0
if not exist frontend\.next-prod\BUILD_ID set NEED=1
if "%NEED%"=="0" (
  powershell -NoProfile -Command "$b=(Get-Item 'frontend/.next-prod/BUILD_ID').LastWriteTime; $n=Get-ChildItem -Recurse frontend/app,frontend/components,frontend/lib,frontend/next.config.js -File -ErrorAction SilentlyContinue | Where-Object { $_.LastWriteTime -gt $b } | Select-Object -First 1; if($n){exit 1}else{exit 0}"
  if errorlevel 1 set NEED=1
)
if "%NEED%"=="1" (
  echo Building the interface ^(source changed - about a minute^)...
  pushd frontend
  set NEXT_DIST_DIR=.next-prod
  call npm run build || (echo UI build failed & popd & pause & exit /b 1)
  set NEXT_DIST_DIR=
  popd
)

start "WarCounsel - Backend" cmd /k "cd /d %~dp0 && (call conda activate eql-companion 2>nul) & python -m uvicorn backend.main:app"
start "WarCounsel - Frontend" cmd /k "cd /d %~dp0frontend && set NEXT_DIST_DIR=.next-prod&& npm run start"
goto open

:devmode
start "WarCounsel - Backend (dev)" cmd /k "cd /d %~dp0 && (call conda activate eql-companion 2>nul) & python -m uvicorn backend.main:app --reload"
start "WarCounsel - Frontend (dev)" cmd /k "cd /d %~dp0frontend && npm run dev"

:open
timeout /t 6 /nobreak >nul
start "" http://localhost:3000
exit /b 0

rem ---- PATH repair --------------------------------------------------------
rem Both tools are routinely INSTALLED yet invisible: python.org without "Add
rem to PATH", conda, and Node leaving %ProgramFiles%\nodejs off. Whatever is
rem set here is inherited by the windows started above, so the fix reaches
rem uvicorn and npm without touching the user's real PATH.
rem Each check is written as a separate statement on purpose: `if cond set A &
rem set B` runs B UNCONDITIONALLY (& splits the line, the if guards only A),
rem which silently pointed PYEXE at the last directory in the list.
:ensurepy
set "PYEXE="
rem The eql-companion conda env FIRST, when it exists. The backend windows
rem below have always tried `conda activate eql-companion`, but that is a
rem silent no-op in a plain cmd (conda is not initialised there, and the
rem 2>nul hides it saying so) -- measured: the window kept BASE python and
rem died on `import fastapi`, because the dependencies are in the env. Naming
rem the env's interpreter directly does not care whether conda ever ran.
for %%e in ("%USERPROFILE%\.conda\envs\eql-companion" "%USERPROFILE%\miniconda3\envs\eql-companion" "%USERPROFILE%\anaconda3\envs\eql-companion" "C:\ProgramData\miniconda3\envs\eql-companion" "C:\ProgramData\anaconda3\envs\eql-companion" "%LOCALAPPDATA%\miniconda3\envs\eql-companion") do (
  if not defined PYEXE if exist "%%~e\python.exe" call :usepy "%%~e"
)
if defined PYEXE goto :eof
for /f "usebackq delims=" %%v in (`python -c "import sys;print(sys.executable)" 2^>nul`) do set "PYEXE=%%v"
rem A real interpreter prints its path. The 0-byte Microsoft Store alias --
rem on PATH by default -- prints NOTHING and still exits 0, so an exit code
rem cannot tell them apart but this can. See install_companion.bat.
rem Deliberately no `find` filter on the path it prints: `find` is a System32
rem exe that Git for Windows SHADOWS with GNU find, so the test would depend
rem on PATH order. It is also not needed -- a Store-INSTALLED Python does live
rem under WindowsApps and works fine, and the empty-output test already
rem rejects the alias.
if defined PYEXE goto :eof
for %%d in ("%LOCALAPPDATA%\Programs\Python\Python313" "%LOCALAPPDATA%\Programs\Python\Python312" "%LOCALAPPDATA%\Programs\Python\Python311" "C:\Python313" "C:\Python312" "C:\Python311" "%USERPROFILE%\miniconda3" "%USERPROFILE%\anaconda3" "C:\ProgramData\miniconda3" "C:\ProgramData\anaconda3") do (
  if not defined PYEXE if exist "%%~d\python.exe" call :usepy "%%~d"
)
goto :eof
:usepy
set "PATH=%~1;%~1\Scripts;%PATH%"
set "PYEXE=%~1\python.exe"
echo Using Python from %~1
goto :eof

:ensurenode
call npm --version >nul 2>nul
if not errorlevel 1 goto :eof
set "PF86=%ProgramFiles(x86)%"
for %%d in ("%ProgramFiles%\nodejs" "%PF86%\nodejs" "%LOCALAPPDATA%\Programs\nodejs") do (
  if exist "%%~d\npm.cmd" call :usenode "%%~d"
)
goto :eof
:usenode
call npm --version >nul 2>nul
if not errorlevel 1 goto :eof
set "PATH=%~1;%PATH%"
echo Using Node.js from %~1
goto :eof
