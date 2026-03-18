#!/usr/bin/env bash
# Setup a udev rule to allow non-root access to the LANCOOL 207 Digital display.
# Run this with sudo (or as root):
#   sudo ./setup-udev.sh

set -euo pipefail

cat > /etc/udev/rules.d/99-lianli-lcd.rules <<'EOF'
SUBSYSTEM=="usb", ATTR{idVendor}=="1cbe", ATTR{idProduct}=="a065", MODE="0666"
EOF

udevadm control --reload-rules
udevadm trigger --attr-match=idVendor=1cbe --attr-match=idProduct=0xa065

echo "udev rule installed. Reconnect the display or reboot if you see no effect."
