#!/usr/bin/env python3
"""Send 'Hello World' to the Lian Li LANCOOL 207 Digital LCD.

Protocol reverse-engineered by deyloop (https://github.com/deyloop/lianli_207_lcd).
Uses DES-CBC encryption with key/IV = b'slv3tuzx'.
"""

import struct
import sys
import time
import io

import usb.core
import usb.util
from PIL import Image, ImageDraw, ImageFont
from Crypto.Cipher import DES
from Crypto.Util.Padding import pad

# ── Constants ────────────────────────────────────────────────────────────────
VID       = 0x1CBE
PID       = 0xA065
DES_KEY   = b'slv3tuzx'
W, H      = 720, 1472        # display dimensions (landscape input)
CHUNK     = 4096
APP_START = time.time()


# ── Protocol helpers ─────────────────────────────────────────────────────────
def ts_ms() -> int:
    return int((time.time() - APP_START) * 1000) & 0xFFFFFFFF


def build_base_cmd(cmd: int) -> bytearray:
    hdr = bytearray(500)
    hdr[0] = cmd
    hdr[2] = 0x1A
    hdr[3] = 0x6D
    struct.pack_into('<I', hdr, 4, ts_ms())
    return hdr


def encrypt_header(hdr: bytearray) -> bytes:
    padded    = pad(bytes(hdr), DES.block_size, style='pkcs7')
    cipher    = DES.new(DES_KEY, DES.MODE_CBC, iv=DES_KEY)
    encrypted = cipher.encrypt(padded)
    result        = bytearray(512)
    result[0:504] = encrypted[:504]
    result[510]   = 0xA1
    result[511]   = 0x1A
    return bytes(result)


def build_rotate(rotation: int = 0) -> bytes:
    hdr = build_base_cmd(0x0D)
    hdr[8] = rotation
    return encrypt_header(hdr)


def build_clock(is_stop: bool) -> bytes:
    from datetime import datetime
    cmd = 0x34 if is_stop else 0x33
    hdr = build_base_cmd(cmd)
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
    return encrypt_header(hdr)


def build_jpeg_packet(jpg: bytes) -> bytes:
    hdr = build_base_cmd(0x65)
    struct.pack_into('>I', hdr, 8, len(jpg))
    return encrypt_header(hdr) + jpg


def build_png_packet(png: bytes) -> bytes:
    hdr = build_base_cmd(0x66)
    struct.pack_into('>I', hdr, 8, len(png))
    return encrypt_header(hdr) + png


def start_play() -> bytes:
    return encrypt_header(build_base_cmd(0x79))


# ── Image generators ─────────────────────────────────────────────────────────
def make_blank_png() -> bytes:
    img = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


def make_blank_jpeg() -> bytes:
    img = Image.new('RGB', (H, W), (0, 0, 0))
    img = img.rotate(-90, expand=True)
    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=95)
    return buf.getvalue()


def make_hello_world_jpeg() -> bytes:
    """Create a 1472x720 landscape image with 'Hello World', then rotate -90° for the display."""
    canvas_w, canvas_h = 1472, 720
    img  = Image.new('RGB', (canvas_w, canvas_h), color=(20, 20, 30))
    draw = ImageDraw.Draw(img)

    # Try to load a nice font, fall back to default
    font_large = None
    for path in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/noto/NotoSans-Bold.ttf",
    ]:
        try:
            font_large = ImageFont.truetype(path, 96)
            break
        except (IOError, OSError):
            continue

    font_small = None
    for path in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf",
        "/usr/share/fonts/noto/NotoSans-Regular.ttf",
    ]:
        try:
            font_small = ImageFont.truetype(path, 36)
            break
        except (IOError, OSError):
            continue

    if font_large is None:
        font_large = ImageFont.load_default()
    if font_small is None:
        font_small = ImageFont.load_default()

    # Draw a gradient-like background
    for y in range(canvas_h):
        r = int(20 + 40 * (y / canvas_h))
        g = int(20 + 20 * (y / canvas_h))
        b = int(40 + 60 * (y / canvas_h))
        draw.line([(0, y), (canvas_w, y)], fill=(r, g, b))

    # Center "Hello World"
    text = "Hello World"
    bbox = draw.textbbox((0, 0), text, font=font_large)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = (canvas_w - tw) // 2
    ty = (canvas_h - th) // 2 - 40

    # Text shadow
    draw.text((tx + 3, ty + 3), text, font=font_large, fill=(0, 0, 0))
    # Main text
    draw.text((tx, ty), text, font=font_large, fill=(255, 255, 255))

    # Subtitle
    sub = "Lian Li LANCOOL 207 Digital"
    bbox2 = draw.textbbox((0, 0), sub, font=font_small)
    sw = bbox2[2] - bbox2[0]
    draw.text(((canvas_w - sw) // 2, ty + th + 30), sub, font=font_small, fill=(140, 180, 255))

    # Rotate -90° for portrait display
    img = img.rotate(-90, expand=True)

    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=95)
    jpg = buf.getvalue()
    assert len(jpg) <= 512000, f"JPEG too large: {len(jpg)} bytes"
    return jpg


# ── USB communication ────────────────────────────────────────────────────────
def main():
    print("Looking for LANCOOL 207 LCD...")
    dev = usb.core.find(idVendor=VID, idProduct=PID)
    if dev is None:
        print("ERROR: Device not found. Is the display connected?")
        sys.exit(1)
    print(f"Found device: {VID:#06x}:{PID:#06x}")

    # Detach kernel drivers
    for cfg in dev:
        for intf in cfg:
            if dev.is_kernel_driver_active(intf.bInterfaceNumber):
                try:
                    dev.detach_kernel_driver(intf.bInterfaceNumber)
                    print(f"  Detached kernel driver from interface {intf.bInterfaceNumber}")
                except usb.core.USBError as e:
                    print(f"  Warning: could not detach kernel driver: {e}")

    # Set configuration
    try:
        dev.set_configuration()
    except usb.core.USBError as e:
        print(f"set_configuration failed ({e}) — trying soft cleanup")
        for cfg in dev:
            for intf in cfg:
                try:
                    usb.util.release_interface(dev, intf.bInterfaceNumber)
                except Exception:
                    pass
        usb.util.dispose_resources(dev)
        time.sleep(0.5)
        dev.set_configuration()

    usb.util.claim_interface(dev, 0)

    cfg  = dev.get_active_configuration()
    intf = cfg[(0, 0)]
    ep_out = usb.util.find_descriptor(intf, custom_match=lambda e:
        usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT and
        usb.util.endpoint_type(e.bmAttributes) == usb.util.ENDPOINT_TYPE_BULK)
    ep_in = usb.util.find_descriptor(intf, custom_match=lambda e:
        usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_IN and
        usb.util.endpoint_type(e.bmAttributes) == usb.util.ENDPOINT_TYPE_BULK)

    if not ep_out or not ep_in:
        print("ERROR: Could not find bulk endpoints")
        sys.exit(1)
    print(f"Endpoints — OUT: {ep_out.bEndpointAddress:#04x}  IN: {ep_in.bEndpointAddress:#04x}")

    def send_cmd(payload: bytes, name: str):
        ep_out.write(payload, timeout=200)
        print(f"  Sent {name} ({len(payload)} bytes)")
        try:
            ack = ep_in.read(512, timeout=200)
            print(f"  ACK {name}: {[hex(x) for x in ack[:4]]}")
        except usb.core.USBError:
            print(f"  No ACK for {name}")

    def push_chunked(payload: bytes, label: str):
        total = len(payload)
        n_chunks = (total + CHUNK - 1) // CHUNK
        print(f"  Pushing {label}: {total} bytes in {n_chunks} chunks")
        for i in range(0, total, CHUNK):
            chunk = payload[i:i + CHUNK]
            for attempt in range(3):
                try:
                    ep_out.write(chunk, timeout=5000)
                    break
                except usb.core.USBTimeoutError:
                    print(f"    Timeout on chunk {i//CHUNK}, attempt {attempt+1}/3")
                    try:
                        ep_out.clear_halt()
                        time.sleep(0.3)
                    except usb.core.USBError:
                        time.sleep(0.5)
            else:
                print(f"    Chunk {i//CHUNK} failed after 3 retries!")
                return
        time.sleep(0.3)
        send_cmd(start_play(), "StartPlay (0x79)")

    # ── Initialization sequence ──────────────────────────────────────────────
    print("\n=== Initializing display ===")
    send_cmd(build_rotate(0), "Rotate (0x0D)")
    time.sleep(0.1)
    send_cmd(build_clock(is_stop=False), "SyncClock (0x33)")
    time.sleep(0.1)
    send_cmd(build_clock(is_stop=True), "StopClock (0x34)")
    time.sleep(0.2)

    print("\n=== Clearing display ===")
    push_chunked(build_png_packet(make_blank_png()), "ClearPNG")
    time.sleep(0.1)
    push_chunked(build_jpeg_packet(make_blank_jpeg()), "ClearJPEG")
    time.sleep(0.1)

    print("\n=== Sending Hello World ===")
    jpg = make_hello_world_jpeg()
    print(f"  JPEG size: {len(jpg)} bytes")
    push_chunked(build_jpeg_packet(jpg), "HelloWorld")
    time.sleep(0.2)

    print("\n=== Done! Check the display. ===")

    # Release
    usb.util.release_interface(dev, 0)
    usb.util.dispose_resources(dev)


if __name__ == "__main__":
    main()
