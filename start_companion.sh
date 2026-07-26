#!/usr/bin/env bash
# WarCounsel launcher for macOS and Linux — backend (:8000) + frontend (:3000).
#
# There is no native EQL client on either platform: people play under Wine
# (CrossOver, Whisky or osxEQL on Mac; Lutris, Bottles or plain Wine on
# Linux). That is fine for us — a bottle is an ordinary folder from the host
# side, so the log file is a normal file and the tailer needs no changes.
# The game folder is auto-detected; set EQL_GAME_DIR to override.
#
#   ./start_companion.sh          production (built UI, lighter)
#   ./start_companion.sh dev      hot reload
#
# NOT available off Windows: the in-game overlay and the screen-OCR position
# feed. Both are Win32-only (click-through windows, global hotkeys, tray).
# Everything else — HUD, War Ledger, Atlas 2D/3D, Advisor — works here.
set -euo pipefail
cd "$(dirname "$0")"

MODE="${1:-prod}"
PY="${PYTHON:-python3}"

command -v "$PY" >/dev/null || { echo "python3 not found — install Python 3.11+"; exit 1; }
command -v node >/dev/null || { echo "node not found — install Node 20+"; exit 1; }

if [ ! -d frontend/node_modules ]; then
  echo "Installing UI dependencies (first run only)..."
  (cd frontend && npm ci)
fi

cleanup() { jobs -p | xargs -r kill 2>/dev/null || true; }
trap cleanup EXIT INT TERM

if [ "$MODE" = "dev" ]; then
  "$PY" -m uvicorn backend.main:app --reload &
  (cd frontend && npm run dev) &
else
  # Rebuild only when a source file is newer than the last build, matching
  # what the .bat does on Windows.
  if [ ! -f frontend/.next-prod/BUILD_ID ] || \
     [ -n "$(find frontend/app frontend/components frontend/lib frontend/next.config.js \
              -newer frontend/.next-prod/BUILD_ID -type f -print -quit 2>/dev/null)" ]; then
    echo "Building the interface (source changed — about a minute)..."
    (cd frontend && NEXT_DIST_DIR=.next-prod npm run build)
  fi
  "$PY" -m uvicorn backend.main:app &
  (cd frontend && NEXT_DIST_DIR=.next-prod npm run start) &
fi

sleep 6
URL="http://localhost:3000"
if command -v open >/dev/null; then open "$URL"          # macOS
elif command -v xdg-open >/dev/null; then xdg-open "$URL" # Linux
else echo "Open $URL"; fi

wait
