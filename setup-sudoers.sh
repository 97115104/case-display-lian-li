#!/usr/bin/env bash
# Install a sudoers rule so the current user can reset the LCD USB device
# without a password — needed for the "USB Sysfs Reset" button in the web UI.
#
# Run once with sudo:
#   sudo ./setup-sudoers.sh
#
# What it grants (and ONLY this):
#   • Write access to /sys/bus/usb/drivers/usb/unbind and /bind
#   • Write access to /sys/bus/usb/devices/*/authorized
#   • Execute access to reset-display.sh in this directory
#
# To remove later:  sudo rm /etc/sudoers.d/lianli-lcd-reset

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
USER="${SUDO_USER:-$(logname 2>/dev/null || whoami)}"
RESET_SCRIPT="$SCRIPT_DIR/reset-display.sh"
SUDOERS_FILE="/etc/sudoers.d/lianli-lcd-reset"

if [ "$(id -u)" -ne 0 ]; then
  echo "ERROR: Run this with sudo: sudo $0" >&2
  exit 1
fi

cat > "$SUDOERS_FILE" <<EOF
# Allow $USER to reset the Lian Li LCD USB device without a password.
# Installed by $SCRIPT_DIR/setup-sudoers.sh

# Kernel unbind/bind (strongest reset — survives pyusb failures)
$USER ALL=(root) NOPASSWD: /usr/bin/tee /sys/bus/usb/drivers/usb/unbind
$USER ALL=(root) NOPASSWD: /usr/bin/tee /sys/bus/usb/drivers/usb/bind

# authorized toggle fallback
$USER ALL=(root) NOPASSWD: /usr/bin/tee /sys/bus/usb/devices/*/authorized

# The convenience reset script
$USER ALL=(root) NOPASSWD: $RESET_SCRIPT
EOF

# Validate before leaving the file in place
if visudo -cf "$SUDOERS_FILE"; then
  chmod 440 "$SUDOERS_FILE"
  echo "Sudoers rule installed for user '$USER'."
  echo "  File: $SUDOERS_FILE"
  echo ""
  echo "USB Sysfs Reset in the web UI will now work without a password."
  echo "To also enable the no-password ioctl path, run:  sudo ./setup-udev.sh"
else
  rm -f "$SUDOERS_FILE"
  echo "ERROR: sudoers validation failed — file removed." >&2
  exit 1
fi
