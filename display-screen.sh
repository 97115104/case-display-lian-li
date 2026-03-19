#!/usr/bin/env bash
# Launch the LANCOOL 207 LCD Dashboard (Node.js + Express).
#
# The Node.js server hot-reloads on JS/HTML changes via nodemon.
# The Python display_service.py subprocess keeps running across reloads,
# so the LCD stays alive while you develop.
#
# Usage:
#   ./display-screen.sh              # default port 8008
#   ./display-screen.sh --port 9000  # custom port
#
# First run: install dependencies with:
#   npm install

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

PORT=8008

# Parse --port arg
prev_was_port=0
for arg in "$@"; do
  if [ "$prev_was_port" = "1" ]; then
    PORT="$arg"
    prev_was_port=0
  fi
  if [ "$arg" = "--port" ]; then
    prev_was_port=1
  fi
done

# Ensure npm dependencies are installed
if [ ! -d "$SCRIPT_DIR/node_modules" ]; then
  echo "node_modules not found — running npm install..."
  npm install
fi

echo "Starting LANCOOL 207 LCD Dashboard on port $PORT..."

# Open browser after a short delay
(sleep 1 && xdg-open "http://localhost:$PORT" 2>/dev/null || true) &

exec PORT="$PORT" npx nodemon --watch 'server.js' --watch 'public' --ext js,html,css server.js

