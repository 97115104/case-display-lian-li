#!/usr/bin/env bash
# Launch the LANCOOL 207 LCD Dashboard.
#
# Starts the web server and opens the dashboard in the default browser.
#
# Usage:
#   ./display-screen.sh              # default port 8008
#   ./display-screen.sh --port 9000  # custom port

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

PORT=8008

# Parse --port arg
for arg in "$@"; do
  if [ "$prev_was_port" = "1" ] 2>/dev/null; then
    PORT="$arg"
    prev_was_port=0
  fi
  if [ "$arg" = "--port" ]; then
    prev_was_port=1
  fi
done

PYTHON=python
if [ -x "$SCRIPT_DIR/.venv/bin/python" ]; then
  PYTHON="$SCRIPT_DIR/.venv/bin/python"
fi

echo "Starting LANCOOL 207 LCD Dashboard on port $PORT..."

# Open browser after a short delay
(sleep 1 && xdg-open "http://localhost:$PORT" 2>/dev/null || true) &

exec "$PYTHON" display_web_server.py --port "$PORT"
