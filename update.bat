@echo off
rem Fetch the latest JARVIS from GitHub and install anything new. Your data and .env are untouched.
cd /d "%~dp0"
where git >nul 2>nul || (echo Git was not found. Install Git, then run this again. & pause & exit /b 1)
git pull --ff-only
if errorlevel 1 (echo. & echo Update failed. See the message above. & pause & exit /b 1)
where uv >nul 2>nul || (echo uv was not found. Run setup.bat first. & pause & exit /b 1)
uv sync
echo.
echo JARVIS is up to date.
if /i "%~1"=="/silent" exit /b 0
echo Start it with start.bat.
pause
