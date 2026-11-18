#!/usr/bin/env bash
# Start the Waffle Bros POS on macOS / Linux.
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is not installed. Install it with:"
  echo
  echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
  echo
  echo "then open a new terminal and run ./start-pos.sh again."
  exit 1
fi

echo "Checking Python packages..."
uv sync

if [ ! -f frontend/dist/index.html ]; then
  if command -v npm >/dev/null 2>&1; then
    echo "First run: building the screens, this takes a minute..."
    (cd frontend && npm ci && npm run build)
  else
    echo "WARNING: the screens are not built and Node.js is not installed."
    echo "Install Node.js 22 or newer from https://nodejs.org to build them."
  fi
fi

open_browser() {
  sleep 2
  if command -v open >/dev/null 2>&1; then
    open http://localhost:4000
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open http://localhost:4000 >/dev/null 2>&1
  fi
}
open_browser &

exec uv run waffle-pos
