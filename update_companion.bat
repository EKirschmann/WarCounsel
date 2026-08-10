@echo off
rem WarCounsel - updater. Close the companion windows before running.
rem Git installs update via git; ZIP installs update via the Python
rem downloader - no git needed either way. Relaunches under cmd /k so the
rem window never closes before it can be read.
if not "%~1"=="stay" (cmd /k ""%~f0" stay" & exit /b)
cd /d %~dp0

if exist .git goto gitpath

python update_companion.py
pause
exit /b 0

:gitpath
echo Pulling the latest version...
git pull --ff-only && goto pulled

rem A failed --ff-only pull has two quite different causes and the old
rem message only described one of them. Someone with unpushed COMMITS was
rem told to stash, which does nothing for them, and they stayed stuck.
rem Ask git which case it is instead of guessing.
echo.
git diff --quiet && git diff --cached --quiet || goto dirty
rem defaulted first: if the rev-list finds nothing (no origin/main, shallow
rem clone) the variable would keep whatever it had and mis-report a split
set AHEAD=0
for /f %%c in ('git rev-list --count origin/main..HEAD 2^>nul') do set AHEAD=%%c
if not "%AHEAD%"=="0" goto diverged
echo Update failed, and the reason is not one of the usual two.
echo Run "git pull" yourself to see what git says.
pause & exit /b 1

:dirty
echo Update failed - you have edited files that the update also changes.
echo.
echo   Keep your edits:  git stash        (then re-run this updater)
echo   Discard them:     git checkout -- .
pause & exit /b 1

:diverged
echo Update failed - you have %AHEAD% local commit(s) that are not on GitHub,
echo so your history and the release history have split apart. Stashing will
echo NOT help here; there is nothing to stash.
echo.
echo   Keep your commits: git rebase origin/main   (then re-run this updater)
echo   Throw them away:   git reset --hard origin/main
echo.
echo If you did not mean to commit anything, the second one is what you want.
pause & exit /b 1

:pulled

echo Refreshing Python dependencies...
pip install -q -r requirements.txt

echo Refreshing frontend dependencies...
pushd frontend
call npm install --silent
echo Rebuilding the interface (about a minute)...
set NEXT_DIST_DIR=.next-prod
call npm run build
set NEXT_DIST_DIR=
popd

echo.
echo Updated. Start it again with start_companion.bat
pause
