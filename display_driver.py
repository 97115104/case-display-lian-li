"""Display driver for the Lian Li LANCOOL 207 Digital LCD.

Protocol reverse-engineered by deyloop (https://github.com/deyloop/lianli_207_lcd).
The display uses DES-CBC encrypted USB bulk transfers.

Display: 720x1472 (landscape input rotated -90° for portrait).
"""

from __future__ import annotations

import fcntl
import io
import os
import struct
import subprocess
import sys
import time
from typing import Callable, Iterable, List, Optional

# Optional external log sink.  Set to a callable(str) to capture log lines
# (e.g. from the web server into a ring buffer).
_log_sink: Optional[Callable[[str], None]] = None


def _log(msg: str) -> None:
    """Print to stderr and forward to any registered log sink."""
    print(msg, file=sys.stderr)
    try:
        if _log_sink is not None:
            _log_sink(msg)
    except Exception:
        pass

# USB IDs for the LANCOOL 207 Digital.
_DISPLAY_VID = 0x1CBE
_DISPLAY_PID = 0xF000

# DES-CBC key & IV (same 8-byte value).
_DES_KEY = b'slv3tuzx'

# Display dimensions (landscape, before -90° rotation).
DISPLAY_W = 1472
DISPLAY_H = 720

# Protocol constants.
_CHUNK_SIZE = 4096
_MAX_IMAGE  = 512000

_APP_START = time.time()


def _ts_ms() -> int:
    return int((time.time() - _APP_START) * 1000) & 0xFFFFFFFF


def _build_base_cmd(cmd: int) -> bytearray:
    hdr = bytearray(500)
    hdr[0] = cmd
    hdr[2] = 0x1A
    hdr[3] = 0x6D
    struct.pack_into('<I', hdr, 4, _ts_ms())
    return hdr


def _encrypt_header(hdr: bytearray) -> bytes:
    from Crypto.Cipher import DES
    from Crypto.Util.Padding import pad
    padded    = pad(bytes(hdr), DES.block_size, style='pkcs7')
    cipher    = DES.new(_DES_KEY, DES.MODE_CBC, iv=_DES_KEY)
    encrypted = cipher.encrypt(padded)
    result        = bytearray(512)
    result[0:504] = encrypted[:504]
    result[510]   = 0xA1
    result[511]   = 0x1A
    return bytes(result)


def _build_rotate(rotation: int = 0) -> bytes:
    hdr = _build_base_cmd(0x0D)
    hdr[8] = rotation
    return _encrypt_header(hdr)


def _build_clock(is_stop: bool) -> bytes:
    from datetime import datetime
    cmd = 0x34 if is_stop else 0x33
    hdr = _build_base_cmd(cmd)
    if not is_stop:
        now = datetime.now()
        hdr[8]  = (now.year >> 8) & 0xFF
        hdr[9]  = now.year & 0xFF
        hdr[10] = now.month
        hdr[11] = now.day
        hdr[12] = now.hour
        hdr[13] = now.minute
        hdr[14] = now.second
        hdr[15] = 2
    return _encrypt_header(hdr)


def _build_jpeg_packet(jpg: bytes) -> bytes:
    hdr = _build_base_cmd(0x65)
    struct.pack_into('>I', hdr, 8, len(jpg))
    return _encrypt_header(hdr) + jpg


def _build_png_packet(png: bytes) -> bytes:
    hdr = _build_base_cmd(0x66)
    struct.pack_into('>I', hdr, 8, len(png))
    return _encrypt_header(hdr) + png


def _start_play() -> bytes:
    return _encrypt_header(_build_base_cmd(0x79))


def _make_blank_png() -> bytes:
    from PIL import Image
    img = Image.new('RGBA', (720, 1472), (0, 0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


def _make_blank_jpeg() -> bytes:
    from PIL import Image
    img = Image.new('RGB', (DISPLAY_W, DISPLAY_H), (0, 0, 0))
    img = img.rotate(-90, expand=True)
    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=95)
    return buf.getvalue()


def _render_text_jpeg(lines: List[str]) -> bytes:
    """Render lines of text into a JPEG suitable for the display."""
    from PIL import Image, ImageDraw, ImageFont

    img  = Image.new('RGB', (DISPLAY_W, DISPLAY_H), color=(20, 20, 30))
    draw = ImageDraw.Draw(img)

    # Gradient background
    for y in range(DISPLAY_H):
        r = int(20 + 40 * (y / DISPLAY_H))
        g = int(20 + 20 * (y / DISPLAY_H))
        b = int(40 + 60 * (y / DISPLAY_H))
        draw.line([(0, y), (DISPLAY_W, y)], fill=(r, g, b))

    font = None
    for path in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/noto/NotoSans-Bold.ttf",
    ]:
        try:
            font = ImageFont.truetype(path, 64)
            break
        except (IOError, OSError):
            continue
    if font is None:
        font = ImageFont.load_default()

    text = "\n".join(lines)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = (DISPLAY_W - tw) // 2
    ty = (DISPLAY_H - th) // 2

    # Shadow + text
    draw.text((tx + 2, ty + 2), text, font=font, fill=(0, 0, 0))
    draw.text((tx, ty), text, font=font, fill=(255, 255, 255))

    img = img.rotate(-90, expand=True)
    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=95)
    jpg = buf.getvalue()
    assert len(jpg) <= _MAX_IMAGE
    return jpg


class DisplayDriver:
    """Console-only fallback driver."""

    def __init__(self, output_path: Optional[str] = "./display_output.txt"):
        self.output_path = output_path

    def write_frame(self, lines: Iterable[str]) -> None:
        payload = "\n".join(lines)
        sys.stdout.write("\n" + "=" * 60 + "\n")
        sys.stdout.write("DISPLAY:\n")
        sys.stdout.write(payload + "\n")
        sys.stdout.write("=" * 60 + "\n")
        sys.stdout.flush()

        if self.output_path:
            try:
                with open(self.output_path, "w", encoding="utf-8") as f:
                    f.write(payload)
            except Exception:
                pass


class UsbDisplayDriver(DisplayDriver):
    """USB-backed display driver using the DES-CBC encrypted protocol."""

    def __init__(self, output_path: Optional[str] = "./display_output.txt"):
        super().__init__(output_path=output_path)
        self.device = None
        self.ep_out = None
        self.ep_in = None
        self._initialized = False
        self._setup_usb()

    def close(self) -> None:
        """Release the USB interface and clean up resources."""
        import usb.util
        if self.device is not None:
            try:
                usb.util.release_interface(self.device, 0)
            except Exception:
                pass
            try:
                usb.util.dispose_resources(self.device)
            except Exception:
                pass
        self.device = None
        self.ep_out = None
        self.ep_in = None
        self._initialized = False

    def force_reinit(self) -> bool:
        """Force re-initialisation of the display protocol without a USB reset.

        Useful when the USB connection is fine but the display firmware is in
        an unknown state (e.g. after the process held a stale reference).
        """
        self._initialized = False
        if not self._ensure_connected():
            _log("[display] force_reinit: not connected, attempting setup...")
            self._setup_usb()
        if self.device is None:
            _log("[display] force_reinit: still no USB device")
            return False
        try:
            self._init_display()
            _log("[display] force_reinit: done")
            return True
        except Exception as e:
            _log(f"[display] force_reinit: _init_display raised {e}")
            return False

    def hard_reset(self) -> bool:
        """Send a USB-level reset to the device, then reconnect and re-init.

        Returns True if the device came back and initialised successfully.
        """
        import usb.core
        import usb.util

        _log("[display] hard_reset: sending USB reset...")

        # If we still have a handle, try a bus-level reset before releasing.
        if self.device is not None:
            try:
                self.device.reset()
            except Exception as e:
                _log(f"[display] hard_reset: reset() raised {e}")
            time.sleep(0.5)

        # Full resource release.
        self.close()

        # Wait for the device to re-enumerate on the bus (up to 10 s).
        deadline = time.time() + 10.0
        dev = None
        while time.time() < deadline:
            dev = usb.core.find(idVendor=_DISPLAY_VID, idProduct=_DISPLAY_PID)
            if dev is not None:
                break
            time.sleep(0.5)

        if dev is None:
            _log("[display] hard_reset: device did not re-enumerate via pyusb")
            return False

        # The display firmware needs significant time to boot after USB reset.
        _log("[display] hard_reset: device found, waiting for firmware...")
        time.sleep(3.0)

        # Try setup + init with retries (firmware may not be ready immediately).
        for attempt in range(3):
            self._setup_usb()
            if self.device is None:
                _log(f"[display] hard_reset: _setup_usb failed (attempt {attempt + 1}/3)")
                time.sleep(2.0)
                continue

            if not self._verify_endpoints():
                _log(f"[display] hard_reset: endpoints not functional (attempt {attempt + 1}/3)")
                self.close()
                time.sleep(2.0)
                continue

            try:
                self._init_display()
                _log("[display] hard_reset: device ready")
                return True
            except Exception as e:
                _log(f"[display] hard_reset: _init_display raised {e} (attempt {attempt + 1}/3)")
                self._initialized = False
                self.close()
                time.sleep(2.0)

        _log("[display] hard_reset: all attempts exhausted")
        return False

    def _setup_usb(self) -> None:
        import usb.core
        import usb.util

        dev = usb.core.find(idVendor=_DISPLAY_VID, idProduct=_DISPLAY_PID)
        if dev is None:
            return

        # Detach kernel drivers from all interfaces.
        for cfg in dev:
            for intf in cfg:
                if dev.is_kernel_driver_active(intf.bInterfaceNumber):
                    try:
                        dev.detach_kernel_driver(intf.bInterfaceNumber)
                    except usb.core.USBError:
                        pass

        # Release any previously claimed interface (e.g. stale session).
        try:
            usb.util.release_interface(dev, 0)
        except Exception:
            pass

        try:
            dev.set_configuration()
        except usb.core.USBError:
            # Release and re-find the device from scratch
            for cfg in dev:
                for intf in cfg:
                    try:
                        usb.util.release_interface(dev, intf.bInterfaceNumber)
                    except Exception:
                        pass
            usb.util.dispose_resources(dev)
            time.sleep(1)
            dev = usb.core.find(idVendor=_DISPLAY_VID, idProduct=_DISPLAY_PID)
            if dev is None:
                return
            for cfg in dev:
                for intf in cfg:
                    if dev.is_kernel_driver_active(intf.bInterfaceNumber):
                        try:
                            dev.detach_kernel_driver(intf.bInterfaceNumber)
                        except usb.core.USBError:
                            pass
            dev.set_configuration()

        usb.util.claim_interface(dev, 0)
        cfg  = dev.get_active_configuration()
        intf = cfg[(0, 0)]

        self.ep_out = usb.util.find_descriptor(intf, custom_match=lambda e:
            usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT and
            usb.util.endpoint_type(e.bmAttributes) == usb.util.ENDPOINT_TYPE_BULK)
        self.ep_in = usb.util.find_descriptor(intf, custom_match=lambda e:
            usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_IN and
            usb.util.endpoint_type(e.bmAttributes) == usb.util.ENDPOINT_TYPE_BULK)

        if not self.ep_out or not self.ep_in:
            return

        self.device = dev

    def _verify_endpoints(self) -> bool:
        """Verify USB endpoints are functional with a test control transfer."""
        if self.device is None or self.ep_out is None or self.ep_in is None:
            return False
        try:
            self.device.ctrl_transfer(0x80, 0x00, 0, 0, 2)
            return True
        except Exception:
            return False

    def _ensure_connected(self) -> bool:
        """Check the USB session is still alive, reconnect if needed."""
        if self.device is None:
            return False
        try:
            self.device.ctrl_transfer(0x80, 0x00, 0, 0, 2)
            return True
        except Exception:
            pass
        # Connection is stale -- try to re-establish.
        _log("[display] USB session lost, reconnecting...")
        self.close()
        time.sleep(1.0)
        self._setup_usb()
        connected = self.device is not None
        _log(f"[display] reconnect {'succeeded' if connected else 'failed'}")
        return connected

    def _send_cmd(self, payload: bytes) -> None:
        for attempt in range(3):
            try:
                self.ep_out.write(payload, timeout=500)
                try:
                    self.ep_in.read(512, timeout=500)
                except Exception:
                    pass
                return
            except Exception:
                if attempt < 2:
                    try:
                        self.ep_out.clear_halt()
                    except Exception:
                        pass
                    time.sleep(0.2)
                else:
                    raise

    def _push_chunked(self, payload: bytes) -> None:
        for i in range(0, len(payload), _CHUNK_SIZE):
            chunk = payload[i:i + _CHUNK_SIZE]
            for attempt in range(3):
                try:
                    self.ep_out.write(chunk, timeout=5000)
                    break
                except Exception:
                    try:
                        self.ep_out.clear_halt()
                    except Exception:
                        pass
                    time.sleep(0.3)
        time.sleep(0.3)
        self._send_cmd(_start_play())

    def _init_display(self) -> None:
        if self._initialized:
            return
        _log("[display] running init sequence...")
        self._send_cmd(_build_rotate(0))
        time.sleep(0.15)
        self._send_cmd(_build_clock(is_stop=False))
        time.sleep(0.15)
        self._send_cmd(_build_clock(is_stop=True))
        time.sleep(0.3)
        self._push_chunked(_build_png_packet(_make_blank_png()))
        time.sleep(0.15)
        self._push_chunked(_build_jpeg_packet(_make_blank_jpeg()))
        time.sleep(0.15)
        self._initialized = True
        _log("[display] init sequence complete")

    def write_frame(self, lines: Iterable[str]) -> None:
        lines_list = list(lines)
        super().write_frame(lines_list)

        if not self._ensure_connected():
            return

        self._init_display()
        jpg = _render_text_jpeg(lines_list)
        self._push_chunked(_build_jpeg_packet(jpg))

    def send_jpeg(self, jpg_bytes: bytes) -> None:
        """Send a pre-rendered JPEG directly to the display."""
        if not self._ensure_connected():
            return
        self._init_display()
        self._push_chunked(_build_jpeg_packet(jpg_bytes))

    def send_png_overlay(self, png_bytes: bytes) -> None:
        """Send a PNG overlay to the display."""
        if not self._ensure_connected():
            return
        self._push_chunked(_build_png_packet(png_bytes))


def usb_diag() -> dict:
    """Return a diagnostic snapshot of the USB device state."""
    vid_str = f"{_DISPLAY_VID:04x}"
    pid_str = f"{_DISPLAY_PID:04x}"
    info: dict = {
        "vid": f"0x{_DISPLAY_VID:04X}",
        "pid": f"0x{_DISPLAY_PID:04X}",
        "pyusb_found": False,
        "sysfs_path": None,
        "dev_path": None,
        "dev_writable": None,
        "lsusb": None,
        "kernel_driver_active": None,
        "errors": [],
    }
    # pyusb probe
    try:
        import usb.core
        dev = usb.core.find(idVendor=_DISPLAY_VID, idProduct=_DISPLAY_PID)
        info["pyusb_found"] = dev is not None
        if dev is not None:
            try:
                info["manufacturer"] = dev.manufacturer
            except Exception:
                pass
            try:
                info["product"] = dev.product
            except Exception:
                pass
            try:
                info["kernel_driver_active"] = dev.is_kernel_driver_active(0)
            except Exception:
                pass
    except Exception as e:
        info["errors"].append(f"pyusb: {e}")

    # sysfs probe
    sysfs_base = "/sys/bus/usb/devices"
    try:
        for name in sorted(os.listdir(sysfs_base)):
            path = os.path.join(sysfs_base, name)
            try:
                with open(os.path.join(path, "idVendor")) as f:
                    vid = f.read().strip()
                with open(os.path.join(path, "idProduct")) as f:
                    pid = f.read().strip()
                if vid == vid_str and pid == pid_str:
                    info["sysfs_path"] = path
                    try:
                        with open(os.path.join(path, "busnum")) as f:
                            busnum = int(f.read())
                        with open(os.path.join(path, "devnum")) as f:
                            devnum = int(f.read())
                        dev_path = f"/dev/bus/usb/{busnum:03d}/{devnum:03d}"
                        info["dev_path"] = dev_path
                        info["dev_writable"] = os.access(dev_path, os.W_OK)
                    except Exception as e:
                        info["errors"].append(f"sysfs busnum/devnum: {e}")
                    break
            except Exception:
                continue
    except Exception as e:
        info["errors"].append(f"sysfs scan: {e}")

    # lsusb
    try:
        r = subprocess.run(
            ["lsusb", "-d", f"{_DISPLAY_VID:04x}:{_DISPLAY_PID:04x}"],
            capture_output=True, text=True, timeout=5,
        )
        info["lsusb"] = r.stdout.strip() or "(not found by lsusb)"
        if r.returncode != 0 and not info["lsusb"]:
            info["lsusb"] = "(lsusb returned non-zero, device not found)"
    except FileNotFoundError:
        info["lsusb"] = "(lsusb not installed)"
    except Exception as e:
        info["lsusb"] = f"lsusb error: {e}"

    return info


def sysfs_reset_usb() -> dict:
    """Reset the display USB device via the kernel USBDEVFS_RESET ioctl.

    This works even when pyusb cannot find the device, as long as the process
    has write access to /dev/bus/usb/BUS/DEV (granted by udev rules).
    Returns a dict with keys: ok (bool), method (str), detail (str).
    """
    d = usb_diag()
    dev_path = d.get("dev_path")
    sysfs_path = d.get("sysfs_path")

    if dev_path is None and sysfs_path is None:
        return {"ok": False, "method": None,
                "detail": "device not found in sysfs or /dev/bus/usb"}

    # Method 1: USBDEVFS_RESET ioctl via /dev/bus/usb
    if dev_path and d.get("dev_writable"):
        USBDEVFS_RESET = 0x5514  # _IO('U', 20) from <linux/usbdevice_fs.h>
        try:
            with open(dev_path, "wb") as fh:
                fcntl.ioctl(fh, USBDEVFS_RESET, 0)
            _log(f"[display] sysfs_reset_usb: USBDEVFS_RESET OK on {dev_path}")
            return {"ok": True, "method": "ioctl_reset", "detail": dev_path}
        except Exception as e:
            _log(f"[display] sysfs_reset_usb: ioctl failed: {e}")

    # Method 2: kernel unbind/bind via sysfs (strongest; requires root)
    if sysfs_path:
        port_name = os.path.basename(sysfs_path)  # e.g. "1-2" or "1-1.4"
        unbind_path = "/sys/bus/usb/drivers/usb/unbind"
        bind_path   = "/sys/bus/usb/drivers/usb/bind"
        try:
            with open(unbind_path, "w") as fh:
                fh.write(port_name)
            time.sleep(1.0)
            with open(bind_path, "w") as fh:
                fh.write(port_name)
            time.sleep(0.5)
            _log(f"[display] sysfs_reset_usb: unbind/bind OK on {port_name}")
            return {"ok": True, "method": "unbind_bind", "detail": port_name}
        except Exception as e:
            _log(f"[display] sysfs_reset_usb: unbind/bind failed: {e}")

    # Method 3: toggle 'authorized' in sysfs (requires root or special perms)
    if sysfs_path:
        auth_path = os.path.join(sysfs_path, "authorized")
        try:
            with open(auth_path, "w") as fh:
                fh.write("0")
            time.sleep(0.5)
            with open(auth_path, "w") as fh:
                fh.write("1")
            _log(f"[display] sysfs_reset_usb: authorized toggle OK on {sysfs_path}")
            return {"ok": True, "method": "authorized_toggle", "detail": sysfs_path}
        except Exception as e:
            _log(f"[display] sysfs_reset_usb: authorized toggle failed: {e}")
            return {
                "ok": False, "method": "authorized_toggle",
                "detail": (
                    f"Failed: {e}. "
                    f"dev_path={dev_path!r} writable={d.get('dev_writable')} "
                    f"sysfs={sysfs_path!r}. "
                    "Check udev rules (setup-udev.sh) or run with sudo."
                ),
            }

    return {
        "ok": False, "method": None,
        "detail": (
            f"dev_path={dev_path!r} writable={d.get('dev_writable')} — "
            "no usable reset method. Check udev rules."
        ),
    }


def make_driver() -> DisplayDriver:
    """Create the display driver.

    Returns a USB-backed driver if the device is present, else console fallback.
    """
    try:
        drv = UsbDisplayDriver()
        if drv.device is not None:
            return drv
        _log("[display] make_driver: UsbDisplayDriver created but device is None (no USB)")
    except Exception as e:
        _log(f"[display] make_driver: exception creating UsbDisplayDriver: {e}")
    return DisplayDriver()


def format_for_display(lines: List[str], max_lines: int = 10, max_chars: int = 80) -> List[str]:
    out: List[str] = []
    for line in lines:
        line = line.rstrip("\n")
        if len(line) <= max_chars:
            out.append(line)
            continue
        start = 0
        while start < len(line) and len(out) < max_lines:
            out.append(line[start : start + max_chars])
            start += max_chars
        if start < len(line):
            out[-1] = out[-1][: max_chars - 3] + "..."
        if len(out) >= max_lines:
            break
    return out[:max_lines]


def show_text(text: str, driver: Optional[DisplayDriver] = None) -> None:
    """Show a block of text on the display."""
    if driver is None:
        driver = make_driver()

    lines = text.strip().splitlines() or [""]
    lines = format_for_display(lines)
    driver.write_frame(lines)


def show_dashboard(title: str, sections: List[str], driver: Optional[DisplayDriver] = None) -> None:
    """Show a simple dashboard-like display with a title + sections."""
    if driver is None:
        driver = make_driver()

    lines = [title, "-"]
    for sec in sections:
        lines.extend(sec.splitlines())
    lines = format_for_display(lines)
    driver.write_frame(lines)
