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
VENV="${WARCOUNSEL_VENV:-.venv}"
REQS="${WARCOUNSEL_REQS:-requirements-lite.txt}"

command -v "$PY" >/dev/null || { echo "python3 not found — install Python 3.11+"; exit 1; }
command -v node >/dev/null || { echo "node not found — install Node 20+"; exit 1; }

# Python dependencies. install_companion.bat has always done this on
# Windows and this script never did, so the three commands in INSTALL.md
# left Mac and Linux with no fastapi at all and a backend that died on
# import while the UI came up fine on :3000 -- which reads as a pathing
# problem rather than a missing install (issue #12).
#
# Into a PRIVATE venv rather than the system Python, because Arch, Fedora
# and Homebrew all mark theirs externally-managed (PEP 668) and refuse a
# plain pip install outright. requirements-lite.txt by choice: the OCR
# extras it omits are Win32-only anyway. Override with WARCOUNSEL_REQS.
#
# Skipped entirely when PYTHON is set or a venv is already active -- that
# is someone telling us which interpreter to use, and we should not
# quietly build a second one behind their back.
if [ -z "${VIRTUAL_ENV:-}" ] && [ -z "${PYTHON:-}" ]; then
  if [ ! -x "$VENV/bin/python" ]; then
    echo "Creating $VENV and installing Python dependencies (first run only)..."
    "$PY" -m venv "$VENV" || {
      echo "Could not create a virtualenv."
      echo "  Debian/Ubuntu: sudo apt install python3-venv"
      exit 1; }
    "$VENV/bin/python" -m pip install --quiet --upgrade pip
    "$VENV/bin/python" -m pip install -r "$REQS" || {
      echo "Installing $REQS failed."
      echo "  If a package has no wheel for your Python yet, try an older"
      echo "  interpreter:  PYTHON=python3.12 ./start_companion.sh"
      exit 1; }
  fi
  PY="$VENV/bin/python"
fi

# Say what is wrong instead of letting uvicorn raise ImportError forty
# frames deep, which is what #12 had to read.
"$PY" -c "import fastapi" 2>/dev/null || {
  echo "The backend dependencies are missing from $("$PY" -c "import sys; print(sys.executable)")."
  echo "  Install them with:  \"$PY\" -m pip install -r $REQS"
  exit 1; }

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
