@echo off
rem Launch JARVIS. Your browser opens automatically. Close this window (or press Ctrl+C) to shut down.
cd /d "%~dp0"
where uv >nul 2>nul || (echo uv was not found. Run setup.bat first. & pause & exit /b 1)
if not exist .env (echo No .env file found. Run setup.bat first. & pause & exit /b 1)
uv run jarvis
pause
