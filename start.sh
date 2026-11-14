#!/usr/bin/env bash
# SPHEREx Explorer development launcher (macOS / Linux).
# Starts the existing backend and frontend without changing their source files.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_PID=""
FRONTEND_PID=""

say() { printf '\n[SPHEREx] %s\n' "$*"; }
fail() { printf '\n[SPHEREx] ERROR: %s\n' "$*" >&2; exit 1; }

cleanup() {
  trap - EXIT INT TERM
  printf '\n[SPHEREx] Stopping servers...\n'
  if [ -n "$FRONTEND_PID" ]; then kill "$FRONTEND_PID" 2>/dev/null || true; fi
  if [ -n "$BACKEND_PID" ]; then kill "$BACKEND_PID" 2>/dev/null || true; fi
  if [ -n "$FRONTEND_PID" ]; then wait "$FRONTEND_PID" 2>/dev/null || true; fi
  if [ -n "$BACKEND_PID" ]; then wait "$BACKEND_PID" 2>/dev/null || true; fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

[ -f "$ROOT/backend/pyproject.toml" ] || fail "Expected backend/pyproject.toml next to start.sh. Run this launcher from the project root."
[ -f "$ROOT/backend/uv.lock" ] || fail "Missing backend/uv.lock."
[ -f "$ROOT/frontend/package.json" ] || fail "Missing frontend/package.json."
[ -f "$ROOT/frontend/package-lock.json" ] || fail "Missing frontend/package-lock.json."

command -v node >/dev/null 2>&1 || fail "Node.js is missing. Install Node.js 22 or newer: https://nodejs.org/"
command -v npm >/dev/null 2>&1 || fail "npm is missing. Install Node.js 22 or newer: https://nodejs.org/"

# A previous terminal may have installed uv but not added it to PATH yet.
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH:/opt/homebrew/bin:/usr/local/bin"

if ! command -v uv >/dev/null 2>&1; then
  command -v curl >/dev/null 2>&1 || fail "curl is required to install uv."
  say "Installing uv using the official Astral installer (one time)..."
  installer="$(mktemp "${TMPDIR:-/tmp}/spherex-uv-installer.XXXXXX")" || fail "Cannot create temporary installer file."
  if ! curl -fsSL https://astral.sh/uv/install.sh -o "$installer"; then
    rm -f "$installer"
    fail "Could not download uv. Check your connection: https://docs.astral.sh/uv/getting-started/installation/"
  fi
  if ! sh "$installer"; then
    rm -f "$installer"
    fail "uv installation failed. See https://docs.astral.sh/uv/getting-started/installation/"
  fi
  rm -f "$installer"
  hash -r
  command -v uv >/dev/null 2>&1 || fail "uv was installed but not found. Try restarting your terminal."
fi

say "Installing/syncing Python backend dependencies (uses Python 3.12)..."
(cd "$ROOT/backend" && uv sync --locked) || fail "Backend dependency installation failed."

# A stamp inside ignored node_modules avoids reinstalling npm packages every launch.
command -v shasum >/dev/null 2>&1 || fail "The macOS shasum command is required."
lock_hash="$(shasum -a 256 "$ROOT/frontend/package-lock.json" | awk '{print $1}')"
stamp="$ROOT/frontend/node_modules/.spherex-lock-hash"
if [ ! -x "$ROOT/frontend/node_modules/.bin/vite" ] || [ ! -f "$stamp" ] || [ "$(cat "$stamp" 2>/dev/null || true)" != "$lock_hash" ]; then
  say "Installing React frontend dependencies (first run or lockfile changed)..."
  (cd "$ROOT/frontend" && npm ci --no-audit --no-fund) || fail "Frontend dependency installation failed."
  printf '%s\n' "$lock_hash" > "$stamp"
else
  say "Frontend dependencies already installed."
fi

[ -x "$ROOT/backend/.venv/bin/python" ] || fail "Backend virtual environment was not created."
[ -x "$ROOT/frontend/node_modules/.bin/vite" ] || fail "Vite executable was not installed."

say "Starting FastAPI on http://127.0.0.1:8000 ..."
(
  cd "$ROOT/backend"
  exec "$ROOT/backend/.venv/bin/python" -m uvicorn spherex_api.app:app --reload --host 127.0.0.1 --port 8000
) &
BACKEND_PID=$!

say "Starting React/Vite on http://127.0.0.1:5173 ..."
(
  cd "$ROOT/frontend"
  exec "$ROOT/frontend/node_modules/.bin/vite" --host 127.0.0.1 --port 5173 --strictPort
) &
FRONTEND_PID=$!

printf '\n\033[1m[SPHEREx] Open http://127.0.0.1:5173\033[0m\n'
printf '[SPHEREx] Backend docs: http://127.0.0.1:8000/docs\n'
printf '[SPHEREx] Ctrl+C stops both servers.\n\n'

while :; do
  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    say "Backend stopped. Check the error above."
    exit 1
  fi
  if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
    say "Frontend stopped. Check the error above."
    exit 1
  fi
  sleep 1
done
