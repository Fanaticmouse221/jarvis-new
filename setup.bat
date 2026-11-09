@echo off
rem One-time setup. Safe to run again at any time (e.g. after pulling updates).
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup.ps1"
echo.
pause
