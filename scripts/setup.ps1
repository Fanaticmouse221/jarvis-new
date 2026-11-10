# JARVIS one-time setup for Windows. Run via setup.bat. Safe to run again after updates.
# Installs uv (free, open-source Python project manager) if missing, then
# Python 3.12 and JARVIS's dependencies into a private .venv folder.
# Nothing is installed system-wide except uv itself.

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

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

Write-Step "Installing Python 3.12 and dependencies (first run downloads roughly 60 MB)"
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

Write-Step "Adding a JARVIS shortcut to your desktop"
try {
    $desktop = [Environment]::GetFolderPath('Desktop')
    $shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $desktop 'JARVIS.lnk'))
    $shortcut.TargetPath = Join-Path $root 'start.bat'
    $shortcut.WorkingDirectory = $root
    $shortcut.IconLocation = Join-Path $root 'jarvis\web\jarvis.ico'
    $shortcut.WindowStyle = 7   # start the console window minimised
    $shortcut.Description = 'Start JARVIS'
    $shortcut.Save()
    Write-Host "Created: $desktop\JARVIS.lnk"
} catch {
    Write-Host "Couldn't create the shortcut ($($_.Exception.Message)). You can still use start.bat." -ForegroundColor Yellow
}

Write-Host "`nSetup complete." -ForegroundColor Green
Write-Host "Next: double-click JARVIS on your desktop (or start.bat)."
Write-Host "The first screen asks for a free Groq key and checks it for you."
