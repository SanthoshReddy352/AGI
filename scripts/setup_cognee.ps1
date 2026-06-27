# Namma Agent — Cognee memory setup (Windows / PowerShell).
# One command to make the optional Cognee memory feature work on a fresh machine.
# Cognee runs FULLY CONTAINERIZED — it adds NO Python dependencies to Namma.
# All this script needs is Docker Desktop. See docs/COGNEE.md for the full guide.
#
#   Run from the project root:  powershell -ExecutionPolicy Bypass -File scripts/setup_cognee.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "== Namma Agent · Cognee setup ==" -ForegroundColor Cyan

# 1. Docker must be running.
docker info *> $null
if ($LASTEXITCODE -ne 0) {
  Write-Host "Docker isn't running. Start Docker Desktop and re-run this script." -ForegroundColor Yellow
  exit 1
}

# 2. Start Ollama (free, local LLM + embedding server). Only container we run persistently.
Write-Host "-> Starting Ollama container..." -ForegroundColor Green
docker compose -f docker-compose.cognee.yml up -d

# 3. Pull the models (idempotent — skips if already present).
Write-Host "-> Pulling embedding model (nomic-embed-text, ~275 MB)..." -ForegroundColor Green
docker exec namma-cognee-ollama ollama pull nomic-embed-text
Write-Host "-> Pulling extraction model (llama3.2:3b, ~2 GB)..." -ForegroundColor Green
docker exec namma-cognee-ollama ollama pull llama3.2:3b

# 4. Pull the Cognee MCP server image (~28 GB — first time only).
Write-Host "-> Pulling Cognee MCP image (cognee/cognee-mcp:main, large)..." -ForegroundColor Green
docker pull cognee/cognee-mcp:main

# 5. Ensure a local env file exists.
if (-not (Test-Path ".env.cognee")) {
  Copy-Item ".env.cognee.example" ".env.cognee"
  Write-Host "-> Created .env.cognee from the example." -ForegroundColor Green
}

# 6. PERSISTENCE: create the cognee-data volume and pre-create its dirs with write
# perms. The volume is root-owned by default but Cognee runs non-root, so without
# this it can't write its DBs there and memory would reset every restart.
Write-Host "-> Preparing the cognee-data volume (persistent memory)..." -ForegroundColor Green
docker volume create cognee-data | Out-Null
docker run --rm -v cognee-data:/cognee-data busybox sh -c "mkdir -p /cognee-data/system /cognee-data/data /cognee-data/cache && chmod -R 777 /cognee-data"

Write-Host ""
Write-Host "Done. Now register Cognee in Namma -> Settings -> MCP -> Config and paste:" -ForegroundColor Cyan
Write-Host @'
{
  "servers": [
    {
      "name": "cognee",
      "command": ["docker","run","-i","--rm","--network","agi_default",
                  "--env-file","D:/AGI/.env.cognee",
                  "-v","cognee-data:/cognee-data","cognee/cognee-mcp:main"],
      "enabled": true,
      "connect_timeout": 90,
      "call_timeout": 900
    }
  ]
}
'@
Write-Host "Then click Save & reconnect. See docs/COGNEE.md for verification + troubleshooting." -ForegroundColor Cyan
