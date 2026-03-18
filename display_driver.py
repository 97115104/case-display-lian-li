"""Display driver for the Lian Li LANCOOL 207 Digital LCD.

Protocol reverse-engineered by deyloop (https://github.com/deyloop/lianli_207_lcd).
The display uses DES-CBC encrypted USB bulk transfers.

Display: 720x1472 (landscape input rotated -90° for portrait).
"""

from __future__ import annotations

import io
import struct
import sys
import time
from typing import Iterable, List, Optional

# USB IDs for the LANCOOL 207 Digital.
_DISPLAY_VID = 0x1CBE
_DISPLAY_PID = 0xA065

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

    def _send_cmd(self, payload: bytes) -> None:
        self.ep_out.write(payload, timeout=200)
        try:
            self.ep_in.read(512, timeout=200)
        except Exception:
            pass

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
        self._send_cmd(_build_rotate(0))
        time.sleep(0.1)
        self._send_cmd(_build_clock(is_stop=False))
        time.sleep(0.1)
        self._send_cmd(_build_clock(is_stop=True))
        time.sleep(0.2)
        self._push_chunked(_build_png_packet(_make_blank_png()))
        time.sleep(0.1)
        self._push_chunked(_build_jpeg_packet(_make_blank_jpeg()))
        time.sleep(0.1)
        self._initialized = True

    def write_frame(self, lines: Iterable[str]) -> None:
        lines_list = list(lines)
        super().write_frame(lines_list)

        if self.device is None:
            return

        self._init_display()
        jpg = _render_text_jpeg(lines_list)
        self._push_chunked(_build_jpeg_packet(jpg))

    def send_jpeg(self, jpg_bytes: bytes) -> None:
        """Send a pre-rendered JPEG directly to the display."""
        if self.device is None:
            return
        self._init_display()
        self._push_chunked(_build_jpeg_packet(jpg_bytes))

    def send_png_overlay(self, png_bytes: bytes) -> None:
        """Send a PNG overlay to the display."""
        if self.device is None:
            return
        self._push_chunked(_build_png_packet(png_bytes))


def make_driver() -> DisplayDriver:
    """Create the display driver.

    Returns a USB-backed driver if the device is present, else console fallback.
    """
    try:
        drv = UsbDisplayDriver()
        if drv.device is not None:
            return drv
    except Exception:
        pass
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
