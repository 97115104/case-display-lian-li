#!/usr/bin/env bash
# Drive the Lian Li LANCOOL 207 Digital LCD.
#
# Usage:
#   ./test-locally.sh hello                               # Send "Hello World" to the LCD
#   ./test-locally.sh repeat --text "Hi" --interval 2
#   ./test-locally.sh dictionary --interval 5
#   ./test-locally.sh dashboard [--port 8008]             # Node.js dashboard (hot-reload)
#
# Dependencies (install once):
#   pip install pyusb Pillow pycryptodome
#   npm install

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

cmd=${1:-help}
shift 2>/dev/null || true

# Use the virtualenv python if present.
PYTHON=python3
if [ -x "$SCRIPT_DIR/.venv/bin/python" ]; then
  PYTHON="$SCRIPT_DIR/.venv/bin/python"
fi

case "$cmd" in
  hello)
    "$PYTHON" hello_lcd.py "$@"
    ;;
  repeat)
    "$PYTHON" display_runner.py repeat "$@"
    ;;
  dictionary)
    "$PYTHON" display_runner.py dictionary "$@"
    ;;
  dashboard)
    # Parse optional --port arg
    PORT=8008
    while [ $# -gt 0 ]; do
      case "$1" in
        --port) PORT="$2"; shift 2 ;;
        *)      shift ;;
      esac
    done
    # Install npm deps if needed
    if [ ! -d "$SCRIPT_DIR/node_modules" ]; then
      echo "node_modules not found — running npm install..."
      npm install
    fi
    echo "Starting dashboard on http://localhost:$PORT/ (hot-reload enabled)"
    exec PORT="$PORT" npx nodemon --watch 'server.js' --watch 'public' --ext js,html,css server.js
    ;;
  help|-h|--help)
    cat <<'EOF'
Usage: ./test-locally.sh <command> [args]

Commands:
  hello                                  Send "Hello World" to the LCD
  repeat     --text "Hello" --interval 2 Repeat text on the LCD
  dictionary --interval 5                Show random words on the LCD
  dashboard  [--port 8008]               Node.js web dashboard (auto-reloads on save)

Dependencies:
  pip install pyusb Pillow pycryptodome
  npm install
EOF
    ;;
  *)
    echo "Unknown command: $cmd" >&2
    exit 1
    ;;
esac
