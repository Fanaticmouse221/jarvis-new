@echo off
rem Test each configured model and API key without starting the server.
cd /d "%~dp0"
where uv >nul 2>nul || (echo uv was not found. Run setup.bat first. & pause & exit /b 1)
uv run jarvis check
echo.
pause
