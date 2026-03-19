#!/usr/bin/env bash
# Hard-reset the LANCOOL 207 Digital LCD without rebooting.
#
# Tries three escalating methods and stops at the first that works:
#   1. USBDEVFS_RESET ioctl  (no root needed if udev rule is installed)
#   2. Kernel unbind / bind  (needs root; most reliable when #1 fails)
#   3. authorized sysfs toggle (root)
#
# Usage:
#   ./reset-display.sh          # tries ioctl first, prompts for sudo if needed
#   sudo ./reset-display.sh     # run fully as root for best results

set -euo pipefail

VID="1cbe"
PID="f000"

# ── Find the device in sysfs ─────────────────────────────────────────────────
SYSFS_PATH=""
for d in /sys/bus/usb/devices/*/; do
  vid_file="$d/idVendor"
  pid_file="$d/idProduct"
  [ -r "$vid_file" ] && [ -r "$pid_file" ] || continue
  if [ "$(cat "$vid_file")" = "$VID" ] && [ "$(cat "$pid_file")" = "$PID" ]; then
    SYSFS_PATH="$d"
    break
  fi
done

if [ -z "$SYSFS_PATH" ]; then
  echo "ERROR: LCD device (${VID}:${PID}) not found in sysfs." >&2
  echo "  Is the display plugged in? Try 'lsusb | grep ${VID}'." >&2
  exit 1
fi

PORT_NAME="$(basename "$SYSFS_PATH")"
BUSNUM="$(cat "$SYSFS_PATH/busnum" 2>/dev/null || echo "")"
DEVNUM="$(cat "$SYSFS_PATH/devnum" 2>/dev/null || echo "")"

if [ -n "$BUSNUM" ] && [ -n "$DEVNUM" ]; then
  DEV_PATH="$(printf '/dev/bus/usb/%03d/%03d' "$BUSNUM" "$DEVNUM")"
else
  DEV_PATH=""
fi

echo "Found LCD at sysfs: $SYSFS_PATH"
echo "  USB port : $PORT_NAME"
[ -n "$DEV_PATH" ] && echo "  Dev node : $DEV_PATH"

# ── Method 1: USBDEVFS_RESET ioctl (no root if udev rule installed) ──────────
if [ -n "$DEV_PATH" ] && [ -w "$DEV_PATH" ]; then
  echo ""
  echo "[1/3] Trying USBDEVFS_RESET ioctl on $DEV_PATH ..."
  python3 - "$DEV_PATH" <<'PYEOF'
import sys, fcntl
USBDEVFS_RESET = 0x5514
with open(sys.argv[1], 'wb') as fh:
    fcntl.ioctl(fh, USBDEVFS_RESET, 0)
print("  ioctl OK")
PYEOF
  echo "Done. If the display is still frozen, try: sudo $0"
  exit 0
fi

# ── Method 2: kernel unbind / bind (root required) ───────────────────────────
UNBIND="/sys/bus/usb/drivers/usb/unbind"
BIND="/sys/bus/usb/drivers/usb/bind"

if [ -w "$UNBIND" ] && [ -w "$BIND" ]; then
  echo ""
  echo "[2/3] Trying kernel unbind/bind on port $PORT_NAME ..."
  echo "$PORT_NAME" > "$UNBIND"
  echo "  unbound — waiting 1 s..."
  sleep 1
  echo "$PORT_NAME" > "$BIND"
  sleep 0.5
  echo "  rebound OK"
  echo "Done — display should reinitialise."
  exit 0
fi

# ── Method 3: authorized toggle (root) ───────────────────────────────────────
AUTH="$SYSFS_PATH/authorized"
if [ -w "$AUTH" ]; then
  echo ""
  echo "[3/3] Trying authorized toggle on $AUTH ..."
  echo 0 > "$AUTH"
  sleep 0.5
  echo 1 > "$AUTH"
  echo "  toggle OK"
  echo "Done — display should reinitialise."
  exit 0
fi

# ── Need elevated privileges ─────────────────────────────────────────────────
echo ""
echo "No reset method succeeded without root access."
echo "Re-run with sudo:"
echo "  sudo $0"
if [ -n "$DEV_PATH" ]; then
  echo ""
  echo "Or install the udev rule so no sudo is needed in future:"
  echo "  sudo $(dirname "$0")/setup-udev.sh"
fi
exit 1
