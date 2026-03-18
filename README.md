# LANCOOL 207 Digital Display - Linux Exploration

This repository contains helper tooling to identify and (eventually) drive the
6" LCD display inside the Lian Li LANCOOL 207 Digital case from Linux.

## What this display is

- **Model:** Lian Li LANCOOL 207 Digital
- **Screen:** 6" LCD, 720×1600 @ 60Hz, 500 nits
- **Control:** Via Lian Li "L-Connect 3" software on Windows (supports templates + monitor overlays + secondary screen)
- **Connection:** The case provides a **Type-A** USB cable (and an internal 9-pin header option) to power/control the screen.

## Goals

1. Identify the USB device (VID/PID, interface type) that drives the screen.
2. Capture or reverse-engineer the protocol used by L-Connect 3 to send templates / text.
3. Build a small Linux tool that can display custom text (e.g., API request info) on the screen.

## Quick Start

**Discovered device:** `1cbe:a065` (Luminary Micro Inc. / lianli-207LCD-1.0)

This device enumerates as a vendor-specific USB bulk device with two bulk endpoints (OUT 0x01, IN 0x81). The driver in this repo attempts to talk to that device when `pyusb` is available.


### 1) Scan for candidate USB devices

Run:

```sh
./lianli_display_probe.py scan
```

If you want to see *all* USB devices, including ones that don't look like Lian Li:

```sh
./lianli_display_probe.py scan --show-all
```

### 2) Inspect a specific device

Once you have a VID/PID from `scan`, show the verbose USB descriptor:

```sh
sudo ./lianli_display_probe.py info --vid 0x1234 --pid 0xabcd
```

### 3) Locate a hidraw device (useful if the display is a HID device)

```sh
sudo ./lianli_display_probe.py hid --vid 0x1234 --pid 0xabcd
```

## Next steps (once you have the VID/PID)

1. Capture traffic from the Windows L-Connect 3 app while it updates the display.
   - On Linux: use `usbmon` + `wireshark` (requires root).
   - On Windows: use `USBPcap` + `Wireshark`.

2. While you are working out the protocol, run the built-in debug mode:

```sh
./test-locally.sh repeat --text "Hello" --interval 2
```

The driver will now attempt a few heuristic packet formats and will print:
- which packet format it tried
- any bytes read back from the device (if the device responds)

That output is the best clue for reverse-engineering the protocol.

2. Use the captured packets to understand the command format. Typically you will see:
   - Command header (e.g., `0xA5`), length, and payload.
   - Pixel/bitmap data, text drawing commands, or template references.

3. Implement a small driver (Python/Node) that sends a minimal command to show text.

## Notes

- Accessing USB hardware usually requires root privileges (or a suitable udev rule).
- The driver in this repo currently defaults to printing to the console. If you install `pyusb` + libusb, it will attempt to talk to the actual display.

  To install in this repo (no root required):

  ```sh
  python3 -m venv .venv
  ./venv/bin/python -m pip install --upgrade pip pyusb
  ```

  On CatchyOS (Arch-based), you also need the system libusb library:

  ```sh
  sudo pacman -S libusb
  ```

  Then run the test scripts with the venv python:

  ```sh
  ./test-locally.sh repeat --text "Hello" --interval 2
  ```

- This script is *not* yet a full working display driver; it is a framework to locate the device and send commands once the protocol is known.

---

If you run the script and share any additional device output (especially `lsusb -v` for the device), I can help reverse-engineer the packet format so the display actually shows text.

## Granting access to the display on Linux

The device is a vendor-specific USB device, so standard non-root users cannot open it by default. You can either run the display scripts with `sudo` or add a udev rule.

To add a udev rule (recommended):

```sh
sudo ./setup-udev.sh
```

Then reconnect the display (unplug/replug the USB cable) or reboot.

After that, run:

```sh
./test-locally.sh repeat --text "Hello" --interval 2
```

If you see an error like `Resource busy` or `USB device busy`, it usually means the kernel / another process has the device claimed. You can unbind it (as root) like this:

```sh
# Replace the device string with the one matching your system (lsusb shows Bus/Device)
sudo sh -c 'echo 3-2.3 > /sys/bus/usb/drivers/usb/unbind'
```

Then retry running the demo (or run it as root to avoid permission issues):

```sh
sudo ./test-locally.sh repeat --text "Hello" --interval 2
```

If it still doesn't work, share the output of the probe command again:

```sh
./lianli_display_probe.py scan
./lianli_display_probe.py info --vid 0x1cbe --pid 0xa065
```
