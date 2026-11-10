@echo off
rem Update JARVIS, then launch it. Close this console (or press Ctrl+C) to shut down.
title JARVIS
cd /d "%~dp0"
call "%~dp0update.bat" /silent
if errorlevel 1 (echo. & echo JARVIS could not update, so it was not started. & pause & exit /b 1)
where uv >nul 2>nul || (echo uv was not found. Run setup.bat first. & pause & exit /b 1)
uv run jarvis
echo.
echo JARVIS has stopped.
pause
