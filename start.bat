@echo off
rem Launch JARVIS. Its window opens automatically. Close this console (or press Ctrl+C) to shut down.
title JARVIS
cd /d "%~dp0"
where uv >nul 2>nul || (echo uv was not found. Run setup.bat first. & pause & exit /b 1)
uv run jarvis
echo.
echo JARVIS has stopped.
pause
