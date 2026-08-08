@echo off
rem WarCounsel - one-shot installer: dependencies + guided setup.
rem Offers to install Python / Node.js automatically via winget when missing.
rem The first line relaunches under "cmd /k" so this window NEVER closes by
rem itself - whatever happens, the user can read it.
if not "%~1"=="stay" (cmd /k ""%~f0" stay" & exit /b)
cd /d %~dp0

rem ---- Python -------------------------------------------------------------
rem The Microsoft Store "App Execution Alias" is the trap here: a 0-BYTE stub
rem named python.exe ships on PATH by default (%LOCALAPPDATA%\Microsoft\
rem WindowsApps), and on current Windows 11 builds it EXITS 0 while doing
rem nothing at all. The old check was `python -c "import sys"` and a comment
rem claiming the stub failed it. Measured on 11 26220: errorlevel 0. So the
rem installer declared Python present, skipped the offer to install it, and
rem died 40 lines later on `pip` with 9009 -- reported as "no pip, python
rem probably not in path".
rem A real interpreter PRINTS its own path. The stub prints NOTHING, which is
rem the difference that cannot be faked by an exit code.
rem No `find` filter on the printed path: `find` is a System32 exe that Git
rem for Windows SHADOWS with GNU find, so any test built on it depends on PATH
rem order (measured -- GNU find errors out on `/i`). It is also unnecessary:
rem a Store-INSTALLED Python reports a WindowsApps path and works fine, so
rem filtering on the folder would reject a working interpreter.
:checkpy
set "PYEXE="
rem An existing eql-companion conda env wins: that is the environment
rem start_companion.bat runs the backend in, so installing anywhere else
rem would leave the launcher looking at a set of packages we never touched.
for %%e in ("%USERPROFILE%\.conda\envs\eql-companion" "%USERPROFILE%\miniconda3\envs\eql-companion" "%USERPROFILE%\anaconda3\envs\eql-companion" "C:\ProgramData\miniconda3\envs\eql-companion" "C:\ProgramData\anaconda3\envs\eql-companion" "%LOCALAPPDATA%\miniconda3\envs\eql-companion") do (
  if not defined PYEXE if exist "%%~e\python.exe" call :useenv "%%~e"
)
if defined PYEXE goto havepy
for /f "usebackq delims=" %%v in (`python -c "import sys;print(sys.executable)" 2^>nul`) do set "PYEXE=%%v"
if not defined PYEXE goto probepy
goto havepy

:useenv
echo Using the eql-companion environment in %~1
set "PATH=%~1;%~1\Scripts;%PATH%"
set "PYEXE=%~1\python.exe"
goto :eof

rem An interpreter that EXISTS but is not on PATH is the other half of the
rem same complaint (python.org without "Add to PATH", conda, or a Store stub
rem shadowing a real install). Look before asking the user to install a second
rem copy -- and put Scripts\ on too, or pip's console scripts stay invisible.
:probepy
if defined TRIED_PROBE goto offerpy
set TRIED_PROBE=1
set "PYDIRS="%LOCALAPPDATA%\Programs\Python\Python313" "%LOCALAPPDATA%\Programs\Python\Python312" "%LOCALAPPDATA%\Programs\Python\Python311" "C:\Python313" "C:\Python312" "C:\Python311" "%USERPROFILE%\miniconda3" "%USERPROFILE%\anaconda3" "C:\ProgramData\miniconda3" "C:\ProgramData\anaconda3""
for %%d in (%PYDIRS%) do if exist "%%~d\python.exe" (
  echo Found Python in %%~d - using it for this install.
  set "PATH=%%~d;%%~d\Scripts;%PATH%"
  goto checkpy
)

:offerpy
echo.
echo Python 3.11+ was not found on this PC.
where winget >nul 2>nul
if errorlevel 1 goto manualpy
if defined TRIED_PY goto manualpy
choice /c YN /m "Install Python automatically now (uses winget)"
if errorlevel 2 goto manualpy
set TRIED_PY=1
echo Installing Python via winget - this takes a minute...
winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements --override "/quiet InstallAllUsers=0 PrependPath=1"
call :refreshpath
goto checkpy
:manualpy
echo.
echo Please install Python yourself: https://www.python.org/downloads/
echo IMPORTANT: tick "Add python.exe to PATH" on the first screen.
echo Then run install_companion.bat again.
pause
exit /b 1
:havepy

rem ---- Node.js ------------------------------------------------------------
:checknode
call npm --version >nul 2>nul
if not errorlevel 1 goto havenode
rem Same "installed but invisible" case as Python above: Node's installer can
rem leave %ProgramFiles%\nodejs off PATH, and winget would then cheerfully
rem reinstall a copy that is already there.
if defined TRIED_NODEPROBE goto offernode
set TRIED_NODEPROBE=1
rem %ProgramFiles(x86)% is read into a plain name first: the parentheses in
rem its own name break the parser inside a block.
set "PF86=%ProgramFiles(x86)%"
for %%d in ("%ProgramFiles%\nodejs" "%PF86%\nodejs" "%LOCALAPPDATA%\Programs\nodejs") do if exist "%%~d\npm.cmd" (
  echo Found Node.js in %%~d - using it for this install.
  set "PATH=%%~d;%PATH%"
  goto checknode
)

:offernode
echo.
echo Node.js was not found on this PC.
where winget >nul 2>nul
if errorlevel 1 goto manualnode
if defined TRIED_NODE goto manualnode
choice /c YN /m "Install Node.js automatically now (uses winget)"
if errorlevel 2 goto manualnode
set TRIED_NODE=1
echo Installing Node.js LTS via winget - this takes a minute...
winget install -e --id OpenJS.NodeJS.LTS --accept-package-agreements --accept-source-agreements
call :refreshpath
goto checknode
:manualnode
echo.
echo Please install Node.js yourself: https://nodejs.org/ (the LTS version).
echo Then run install_companion.bat again.
pause
exit /b 1
:havenode

echo Installing Python dependencies...
rem `python -m pip`, never bare `pip`: pip's console script lives in Scripts\
rem which is a SEPARATE PATH entry, so a working python routinely comes with
rem an unreachable pip (conda and "just me" installs both do this). It also
rem guarantees the packages land in the interpreter we just verified rather
rem than some other one earlier on PATH.
python -m pip install -r requirements.txt || (echo pip install failed & pause & exit /b 1)

echo Installing frontend dependencies...
pushd frontend
call npm install || (echo npm install failed & pause & exit /b 1)
echo Building the interface (one time, about a minute)...
set NEXT_DIST_DIR=.next-prod
call npm run build || (echo interface build failed & pause & exit /b 1)
set NEXT_DIST_DIR=
popd

python setup_wizard.py

echo.
set /p LAUNCH="Launch the companion now? (Y/n): "
if /i not "%LAUNCH%"=="n" call start_companion.bat
echo.
echo All done - you can close this window.
exit /b 0

rem ---- re-read PATH from the registry so a just-installed tool is found
rem ---- in THIS window (a fresh install only lands on future consoles)
:refreshpath
for /f "usebackq delims=" %%p in (`powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')"`) do set "PATH=%%p"
exit /b 0
