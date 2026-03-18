#!/usr/bin/env bash
# Run the bundled display/testing utilities.
#
# Usage:
#   ./test-locally.sh repeat --text "Hello" --interval 2
#   ./test-locally.sh dictionary --interval 5
#   ./test-locally.sh proxy --target http://localhost:8080 --listen 8001
#   ./test-locally.sh webui --port 8000

set -euo pipefail

cmd=${1:-help}
shift 2>/dev/null || true

# Prefer the virtualenv python if present.
PYTHON=python
if [ -x "$(pwd)/.venv/bin/python" ]; then
  PYTHON="$(pwd)/.venv/bin/python"
fi

case "$cmd" in
  repeat)
    "$PYTHON" display_runner.py repeat "$@"
    ;;
  dictionary)
    "$PYTHON" display_runner.py dictionary "$@"
    ;;
  proxy)
    "$PYTHON" display_runner.py proxy "$@"
    ;;
  webui)
    "$PYTHON" display_web_server.py "$@"
    ;;
  help|-h|--help)
    cat <<'EOF'
Usage: ./test-locally.sh <command> [args]

Commands:
  repeat  --text "Hello" --interval 2
  dictionary  --interval 5
  proxy  --target http://localhost:8080 --listen 8001
  webui  --port 8000

Notes:
  - This script prefers the ./venv Python if it exists.
  - Install dependencies with: ./venv/bin/python -m pip install pyusb
EOF
    ;;
  *)
    echo "Unknown command: $cmd" >&2
    exit 1
    ;;
esac
