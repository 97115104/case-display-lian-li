#!/usr/bin/env python3
"""Probe and prepare for driving the Lian Li LANCOOL 207 Digital display.

This script helps you:
  1) Discover the USB device(s) that correspond to the integrated 6" LCD.
  2) Gather VID:PID, interface info, and candidate /dev/hidraw* (if available).
  3) Provide a small framework for sending commands once the protocol is known.

Usage examples:
  ./lianli_display_probe.py scan
  ./lianli_display_probe.py info --vid 0x1234 --pid 0xabcd
  ./lianli_display_probe.py show-candidates

Once you have the correct VID:PID and device path, you can capture USB traffic
(e.g. via usbmon/wireshark) or reverse-engineer the protocol.

NOTE: Accessing USB devices usually requires root (or a proper udev rule).
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import subprocess
import sys
from typing import Dict, List, Optional, Tuple


def _run(cmd: List[str], capture: bool = True) -> str:
    """Run a command and return stdout. Raises if command fails."""
    try:
        out = subprocess.run(cmd, capture_output=capture, text=True, check=True)
        return out.stdout
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Command failed: {cmd}\n{e.stderr or e.stdout}")


def parse_lsusb_line(line: str) -> Optional[Dict[str, str]]:
    # Example: Bus 001 Device 002: ID 0bda:5411 Realtek Semiconductor Corp.
    m = re.match(r"Bus (\d{3}) Device (\d{3}): ID ([0-9a-fA-F]{4}):([0-9a-fA-F]{4}) (.+)$", line)
    if not m:
        return None
    return {
        "bus": m.group(1),
        "device": m.group(2),
        "vid": m.group(3).lower(),
        "pid": m.group(4).lower(),
        "desc": m.group(5).strip(),
    }


def get_lsusb_devices() -> List[Dict[str, str]]:
    out = _run(["lsusb"])
    devices = []
    for line in out.splitlines():
        parsed = parse_lsusb_line(line)
        if parsed:
            devices.append(parsed)
    return devices


def find_lianli_candidates(devices: List[Dict[str, str]]) -> List[Dict[str, str]]:
    # Lian Li may show up under several different USB descriptors.
    # Modern "universal" displays often use a DisplayLink chipset, so include it here.
    keywords = [
        "lian",
        "lian-li",
        "lian li",
        "lconnect",
        "l-connect",
        "lcd",
        "displaylink",
        "display link",
    ]
    candidates = []
    for d in devices:
        desc = d.get("desc", "").lower()
        if any(k in desc for k in keywords):
            candidates.append(d)
    return candidates


def print_devices(title: str, devices: List[Dict[str, str]]) -> None:
    if not devices:
        print(f"{title}: none found")
        return
    print(title + ":")
    for d in devices:
        print(f"  {d['bus']}:{d['device']} {d['vid']}:{d['pid']} -- {d['desc']}")


def show_lsusb_verbose(vid: str, pid: str) -> None:
    # Requires root for full information in some cases.
    try:
        out = _run(["lsusb", "-v", "-d", f"{vid}:{pid}"])
    except RuntimeError as e:
        print("Failed to run lsusb -v. You probably need to run as root or add a udev rule.")
        print(str(e))
        return
    print(out)


def locate_hidraw_for_vidpid(vid: str, pid: str) -> List[str]:
    """Return /dev/hidraw* devices that match the given VID/PID."""
    devices: List[str] = []
    # On Linux, hidraw devices have a symlink under sysfs with idVendor/idProduct.
    # We'll scan /sys/class/hidraw.
    base = "/sys/class/hidraw"
    if not os.path.isdir(base):
        return devices

    for entry in os.listdir(base):
        dev_path = os.path.join(base, entry)
        # device -> ../devices/.../hidrawX
        try:
            link = os.path.realpath(os.path.join(dev_path, "device"))
        except OSError:
            continue
        # The symlink target contains something like usb-0000:00:14.0-1.4
        if "usb" not in link:
            continue
        # Walk up to find idVendor/idProduct
        u = link
        while u and u != "/":
            if os.path.exists(os.path.join(u, "idVendor")) and os.path.exists(os.path.join(u, "idProduct")):
                try:
                    vid_content = open(os.path.join(u, "idVendor")).read().strip().lower()
                    pid_content = open(os.path.join(u, "idProduct")).read().strip().lower()
                except OSError:
                    break
                if vid_content == vid.lower() and pid_content == pid.lower():
                    devices.append(f"/dev/{entry}")
                    break
            u = os.path.dirname(u)
    return devices


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Probe the Lian Li LANCOOL 207 Digital display and helper tooling.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    scan = sub.add_parser("scan", help="Scan for USB devices and highlight candidates.")
    scan.add_argument("--show-all", action="store_true", help="Show all lsusb results, not just candidates.")

    info = sub.add_parser("info", help="Show verbose lsusb info for a specific VID:PID.")
    info.add_argument("--vid", required=True, help="Vendor ID (like 0x1234)")
    info.add_argument("--pid", required=True, help="Product ID (like 0xabcd)")

    hid = sub.add_parser("hid", help="Locate /dev/hidraw* devices for a VID:PID.")
    hid.add_argument("--vid", required=True, help="Vendor ID (like 0x1234)")
    hid.add_argument("--pid", required=True, help="Product ID (like 0xabcd)")

    args = parser.parse_args(argv)

    if args.cmd == "scan":
        devices = get_lsusb_devices()
        if args.show_all:
            print_devices("All USB devices", devices)
        candidates = find_lianli_candidates(devices)
        print_devices("Candidate devices (likely Lian Li / Display USB devices)", candidates)
        if candidates:
            print("\nFor each candidate, run: ./lianli_display_probe.py info --vid <vid> --pid <pid>")
            print("If you want to locate a hidraw node: ./lianli_display_probe.py hid --vid <vid> --pid <pid>")
        else:
            print("No candidate looked like Lian Li / display hardware. If your display is connected,")
            print("try running as root or with --show-all, then identify the VID:PID manually.")

    elif args.cmd == "info":
        vid = args.vid.lower().replace("0x", "")
        pid = args.pid.lower().replace("0x", "")
        show_lsusb_verbose(vid, pid)

    elif args.cmd == "hid":
        vid = args.vid.lower().replace("0x", "")
        pid = args.pid.lower().replace("0x", "")
        matches = locate_hidraw_for_vidpid(vid, pid)
        if not matches:
            print("No /dev/hidraw* devices found for this VID:PID. You may need to run as root.")
        else:
            print("Potential hidraw devices:")
            for m in matches:
                print("  " + m)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
