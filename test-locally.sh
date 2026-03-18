#!/usr/bin/env bash
# Drive the Lian Li LANCOOL 207 Digital LCD.
#
# Usage:
#   ./test-locally.sh hello                          # Send "Hello World" to the LCD
#   ./test-locally.sh repeat --text "Hi" --interval 2
#   ./test-locally.sh dictionary --interval 5
#   ./test-locally.sh webui --port 8000
#
# Dependencies (install once):
#   .venv/bin/pip install pyusb Pillow pycryptodome

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

cmd=${1:-help}
shift 2>/dev/null || true

# Use the virtualenv python.
PYTHON=python
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
  webui)
    "$PYTHON" display_web_server.py "$@"
    ;;
  help|-h|--help)
    cat <<'EOF'
Usage: ./test-locally.sh <command> [args]

Commands:
  hello                              Send "Hello World" to the LCD
  repeat   --text "Hello" --interval 2   Repeat text on the LCD
  dictionary --interval 5            Show random words on the LCD
  webui    --port 8000               Web UI to send text to the LCD

Dependencies:
  .venv/bin/pip install pyusb Pillow pycryptodome
EOF
    ;;
  *)
    echo "Unknown command: $cmd" >&2
    exit 1
    ;;
esac
