@echo off
rem Save all work in this folder to GitHub: commits every change and pushes it.
rem Use this after another AI has given you new or changed files. Your .env and data are never uploaded.
cd /d "%~dp0"
where git >nul 2>nul || (echo Git was not found. Install Git, then run this again. & pause & exit /b 1)
git add -A
git diff --cached --quiet && (echo Nothing has changed, so there is nothing to save. & pause & exit /b 0)
set "MSG=Work saved on %DATE%"
set /p "NOTE=Describe what changed in a few words (or just press Enter): "
if not "%NOTE%"=="" set "MSG=%NOTE%"
git commit -m "%MSG%"
if errorlevel 1 (echo. & echo The save failed. See the message above. & pause & exit /b 1)
git push
if errorlevel 1 (echo. & echo Saved on this PC, but uploading to GitHub failed. See the message above. & pause & exit /b 1)
echo.
echo Saved and uploaded to GitHub.
pause
