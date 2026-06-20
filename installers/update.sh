#!/usr/bin/env bash
# Namma Agent - updater for macOS & Linux.
# Run it:  bash installers/update.sh   (pass --relaunch to reopen the app afterwards)
# Also invoked by the in-app "Update now" button (POST /api/update/apply).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
cd "$ROOT"
RELAUNCH=0; [ "${1:-}" = "--relaunch" ] && RELAUNCH=1
VPY="$ROOT/.venv/bin/python"

echo "== Updating Namma Agent =="

# Ask a running instance to close so files aren't locked (best effort).
curl -s -m 3 -X POST http://127.0.0.1:8000/api/shutdown >/dev/null 2>&1 || true
sleep 1

# 1. fetch the new source ----------------------------------------------------
if [ -d .git ]; then
  echo "Pulling latest source (git)…"
  git pull --ff-only || { echo "git pull failed (local changes?). Commit/stash and retry."; exit 1; }
else
  echo "This install is not a git checkout."
  echo "Download the latest release and unpack it over this folder:"
  echo "  https://github.com/SanthoshReddy352/Namma-Agent/releases/latest"
  exit 1
fi

# 2. reinstall deps (in case requirements changed) ---------------------------
echo "Updating dependencies…"
"$VPY" -m pip install -r namma_agent/requirements.txt

# 3. rebuild the web UI ------------------------------------------------------
if command -v npm >/dev/null 2>&1; then
  echo "Rebuilding the web UI…"
  ( cd namma_agent/webui && npm install && npm run build )
fi

echo "Updated to: $("$VPY" -m namma_agent --version)"
if [ "$RELAUNCH" = "1" ]; then exec "$VPY" -m namma_agent; fi
