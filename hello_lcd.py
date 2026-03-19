#!/usr/bin/env python3
"""Send 'Hello World' to the Lian Li LANCOOL 207 Digital LCD.

Uses the display_driver module for USB communication and protocol handling.
"""

import io
import sys
import time

from PIL import Image, ImageDraw, ImageFont
from display_driver import UsbDisplayDriver, DISPLAY_W, DISPLAY_H


def make_hello_world_jpeg() -> bytes:
    """Create a 1472x720 landscape image with 'Hello World', then rotate -90° for the display."""
    canvas_w, canvas_h = DISPLAY_W, DISPLAY_H
    img  = Image.new('RGB', (canvas_w, canvas_h), color=(20, 20, 30))
    draw = ImageDraw.Draw(img)

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

    # Gradient background
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

    draw.text((tx + 3, ty + 3), text, font=font_large, fill=(0, 0, 0))
    draw.text((tx, ty), text, font=font_large, fill=(255, 255, 255))

    sub = "Lian Li LANCOOL 207 Digital"
    bbox2 = draw.textbbox((0, 0), sub, font=font_small)
    sw = bbox2[2] - bbox2[0]
    draw.text(((canvas_w - sw) // 2, ty + th + 30), sub, font=font_small, fill=(140, 180, 255))

    img = img.rotate(-90, expand=True)

    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=95)
    jpg = buf.getvalue()
    assert len(jpg) <= 512000, f"JPEG too large: {len(jpg)} bytes"
    return jpg


def main():
    print("Looking for LANCOOL 207 LCD...")
    try:
        drv = UsbDisplayDriver()
    except Exception as e:
        print(f"ERROR: Could not connect to display: {e}")
        sys.exit(1)

    if drv.device is None:
        print("ERROR: Device not found. Is the display connected?")
        sys.exit(1)

    print("Found device, sending Hello World...")
    jpg = make_hello_world_jpeg()
    print(f"  JPEG size: {len(jpg)} bytes")
    drv.send_jpeg(jpg)
    print("Done! Check the display.")
    drv.close()


if __name__ == "__main__":
    main()
