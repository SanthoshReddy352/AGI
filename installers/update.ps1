# Namma Agent - updater for Windows.
# Run it:  double-click "update.bat", or:
#   powershell -NoProfile -ExecutionPolicy Bypass -File installers\update.ps1 [-Relaunch]
# Also invoked by the in-app "Update now" button (POST /api/update/apply).
param([switch]$Relaunch)
$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $Here
Set-Location $Root
$VenvPy = Join-Path $Root ".venv\Scripts\python.exe"

Write-Host "== Updating Namma Agent =="

# Ask a running instance to close so files aren't locked (best effort).
try { Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/shutdown" -TimeoutSec 3 | Out-Null } catch {}
Start-Sleep -Seconds 1

# 1. fetch the new source ----------------------------------------------------
if (Test-Path ".git") {
    Write-Host "Pulling latest source (git)..."
    git pull --ff-only
    if ($LASTEXITCODE -ne 0) { Write-Host "git pull failed (local changes?). Commit/stash and retry."; exit 1 }
} else {
    Write-Host "This install is not a git checkout."
    Write-Host "Download the latest release and unpack it over this folder:"
    Write-Host "  https://github.com/SanthoshReddy352/Namma-Agent/releases/latest"
    exit 1
}

# 2. reinstall deps ----------------------------------------------------------
Write-Host "Updating dependencies..."
& $VenvPy -m pip install -r namma_agent\requirements.txt

# 3. rebuild the web UI ------------------------------------------------------
if (Get-Command npm -ErrorAction SilentlyContinue) {
    Write-Host "Rebuilding the web UI..."
    Push-Location namma_agent\webui; npm install; npm run build; Pop-Location
}

Write-Host "Updated to: $(& $VenvPy -m namma_agent --version)"
if ($Relaunch) { & $VenvPy -m namma_agent }
