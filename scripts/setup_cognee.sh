#!/usr/bin/env bash
# Namma Agent — Cognee memory setup (Linux / macOS / Git-Bash).
# Cognee runs FULLY CONTAINERIZED — it adds NO Python dependencies to Namma.
# The only prerequisite is Docker. See docs/COGNEE.md for the full guide.
#
#   Run from the project root:  bash scripts/setup_cognee.sh
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== Namma Agent · Cognee setup =="

if ! docker info >/dev/null 2>&1; then
  echo "Docker isn't running. Start Docker and re-run this script." >&2
  exit 1
fi

echo "-> Starting Ollama container..."
docker compose -f docker-compose.cognee.yml up -d

echo "-> Pulling embedding model (nomic-embed-text, ~275 MB)..."
docker exec namma-cognee-ollama ollama pull nomic-embed-text
echo "-> Pulling extraction model (llama3.2:3b, ~2 GB)..."
docker exec namma-cognee-ollama ollama pull llama3.2:3b

echo "-> Pulling Cognee MCP image (cognee/cognee-mcp:main, large)..."
docker pull cognee/cognee-mcp:main

if [ ! -f .env.cognee ]; then
  cp .env.cognee.example .env.cognee
  echo "-> Created .env.cognee from the example."
fi

# PERSISTENCE: create the cognee-data volume + pre-create its dirs with write perms.
# The volume is root-owned by default but Cognee runs non-root, so without this it
# can't write its DBs there and memory would reset on every restart.
echo "-> Preparing the cognee-data volume (persistent memory)..."
docker volume create cognee-data >/dev/null
docker run --rm -v cognee-data:/cognee-data busybox sh -c \
  "mkdir -p /cognee-data/system /cognee-data/data /cognee-data/cache && chmod -R 777 /cognee-data"

cat <<'EOF'

Done. Now register Cognee in Namma -> Settings -> MCP -> Config and paste
(adjust the --env-file absolute path for your OS):

{
  "servers": [
    {
      "name": "cognee",
      "command": ["docker","run","-i","--rm","--network","agi_default",
                  "--env-file","/ABSOLUTE/PATH/TO/.env.cognee",
                  "-v","cognee-data:/cognee-data","cognee/cognee-mcp:main"],
      "enabled": true,
      "connect_timeout": 90,
      "call_timeout": 900
    }
  ]
}

Then click Save & reconnect. See docs/COGNEE.md for verification + troubleshooting.
EOF
