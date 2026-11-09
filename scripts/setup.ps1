# JARVIS one-time setup for Windows. Run via setup.bat.
# Installs uv (free, open-source Python project manager) if missing, then
# Python 3.12 and JARVIS's dependencies into a private .venv folder.
# Nothing is installed system-wide except uv itself.

$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)

function Write-Step($text) { Write-Host "`n>> $text" -ForegroundColor Cyan }
function Update-SessionPath {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [Environment]::GetEnvironmentVariable('Path', 'User')
}

Write-Host "=== J.A.R.V.I.S. setup ===" -ForegroundColor Cyan

Write-Step "Checking for uv"
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "winget isn't available. Install uv manually from https://docs.astral.sh/uv/ then run setup.bat again."
    }
    Write-Host "uv not found. Installing it with winget (free)..."
    winget install --id astral-sh.uv --exact --accept-source-agreements --accept-package-agreements
    Update-SessionPath
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        throw "uv was installed but this window can't see it yet. Close this window and run setup.bat again."
    }
}
uv --version

Write-Step "Installing Python 3.12 and dependencies (first run downloads roughly 50 MB)"
uv sync
if ($LASTEXITCODE -ne 0) { throw "uv sync failed. See the messages above." }

Write-Step "Preparing configuration"
if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
    Write-Host "Created .env from .env.example"
} else {
    Write-Host ".env already exists; left unchanged."
}
New-Item -ItemType Directory -Force data | Out-Null

Write-Step "Running the self-tests"
uv run pytest -q
if ($LASTEXITCODE -ne 0) { throw "Self-tests failed. Please report the output above." }

Write-Host "`nSetup complete." -ForegroundColor Green
Write-Host "Next steps:"
Write-Host "  1. Open .env in Notepad and paste your Groq key after GROQ_API_KEY="
Write-Host "  2. Double-click check.bat to test the connection"
Write-Host "  3. Double-click start.bat to launch JARVIS"
