#!/usr/bin/env python3
"""Display state and Ollama rendering for the Lian Li LANCOOL 207 Digital LCD.

This module owns the global display driver state and provides:
- Driver lifecycle management (_get_driver, _restart_driver)
- Ollama request monitor rendering to the LCD
- Background thread management

Used by display_service.py (the IPC subprocess) — NOT run standalone.
"""

from __future__ import annotations

import io
import sys
import threading
import time
from collections import deque
from datetime import datetime
from typing import Optional

from display_driver import (
    DISPLAY_H,
    DISPLAY_W,
    UsbDisplayDriver,
    make_driver,
    show_text,
    usb_diag,
    sysfs_reset_usb,
)
import display_driver as _dd

# ── State ────────────────────────────────────────────────────────────────────

_driver = None
_driver_lock = threading.Lock()

# Server-side log ring buffer (captures driver _log() calls + our own entries)
_server_log: deque = deque(maxlen=200)


def _slog(msg: str) -> None:
    """Append a timestamped entry to the server log ring buffer."""
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    _server_log.append(f"[{ts}] {msg}")


# Hook the driver's _log() into our ring buffer.
_dd._log_sink = _slog

# Ollama monitor state
_ollama_target: str = "http://localhost:11434"
_ollama_requests: deque = deque(maxlen=50)
_ollama_monitor_active: bool = False
_ollama_lock = threading.Lock()

# Background mode control
_bg_thread: Optional[threading.Thread] = None
_bg_stop = threading.Event()


def _get_driver():
    global _driver
    with _driver_lock:
        if _driver is None:
            _driver = make_driver()
        return _driver


def _restart_driver():
    """Hard-reset the USB device and return a fresh, initialised driver.

    Cascade:
      1. pyusb hard_reset()  (device.reset() + reconnect)
      2. sysfs USBDEVFS_RESET ioctl (works even if pyusb loses the device)
      3. Plain close + recreate with longer settle time
    """
    global _driver
    _stop_background()
    with _driver_lock:
        old = _driver
        _driver = None

        # ── Stage 1: pyusb hard reset ────────────────────────────────────
        if old is not None and hasattr(old, 'hard_reset'):
            _slog("[restart] trying pyusb hard_reset...")
            ok = old.hard_reset()
            if ok:
                _slog("[restart] pyusb hard_reset succeeded")
                _driver = old
                return _driver
            _slog("[restart] pyusb hard_reset failed, trying sysfs reset...")
        elif old is not None and hasattr(old, 'close'):
            old.close()

        # ── Stage 2: sysfs / USBDEVFS_RESET ioctl ───────────────────────
        sr = sysfs_reset_usb()
        _slog(f"[restart] sysfs_reset_usb: ok={sr['ok']} method={sr.get('method')} detail={sr.get('detail')}")
        if sr["ok"]:
            _slog("[restart] waiting for firmware after sysfs reset...")
            time.sleep(3.0)

        # ── Stage 3: recreate driver ─────────────────────────────────────
        _slog("[restart] recreating driver...")
        time.sleep(1.0)
        _driver = make_driver()
        ok2 = hasattr(_driver, 'device') and _driver.device is not None
        if ok2 and not getattr(_driver, '_initialized', False):
            _slog("[restart] running display init on new driver...")
            try:
                _driver._init_display()
            except Exception as e:
                _slog(f"[restart] init failed: {e}")
        _slog(f"[restart] driver recreated: usb_ok={ok2}")
        return _driver


def _stop_background():
    global _bg_thread
    _bg_stop.set()
    if _bg_thread and _bg_thread.is_alive():
        _bg_thread.join(timeout=5)
    _bg_thread = None
    _bg_stop.clear()


def _run_in_background(fn, *args):
    global _bg_thread
    _stop_background()
    _bg_thread = threading.Thread(target=fn, args=args, daemon=True)
    _bg_thread.start()


# ── Ollama request rendering ────────────────────────────────────────────────

# Cache fonts at module level so they're loaded once, not every 1.5s render.
_cached_fonts = None


def _load_fonts():
    """Load DejaVu Mono fonts, falling back to PIL default on failure."""
    global _cached_fonts
    if _cached_fonts is not None:
        return _cached_fonts

    from PIL import ImageFont
    bold_paths = [
        "/usr/share/fonts/TTF/DejaVuSansMono-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
        "/usr/share/fonts/dejavu-sans-fonts/DejaVuSansMono-Bold.ttf",
    ]
    regular_paths = [
        "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/dejavu-sans-fonts/DejaVuSansMono.ttf",
    ]
    default = ImageFont.load_default()
    font_title = font_label = default
    for path in bold_paths:
        try:
            font_title = ImageFont.truetype(path, 40)
            font_label = ImageFont.truetype(path, 30)
            break
        except (IOError, OSError):
            continue
    font_small = default
    for path in regular_paths:
        try:
            font_small = ImageFont.truetype(path, 24)
            break
        except (IOError, OSError):
            continue
    _cached_fonts = (font_title, font_label, font_small)
    return _cached_fonts


def _draw_rect(draw, box, radius, fill):
    """Draw a rectangle, using rounded_rectangle when available."""
    try:
        draw.rounded_rectangle(box, radius=radius, fill=fill)
    except AttributeError:
        draw.rectangle(box, fill=fill)


def _render_ollama_display():
    """Render the current Ollama request log onto the LCD."""
    from PIL import Image, ImageDraw

    canvas_w, canvas_h = DISPLAY_W, DISPLAY_H
    img = Image.new('RGB', (canvas_w, canvas_h), color=(10, 12, 30))
    draw = ImageDraw.Draw(img)

    for cy in range(canvas_h):
        t = cy / canvas_h
        r = int(10 + 8 * t)
        g = int(12 + 10 * t)
        b = int(30 + 25 * t)
        draw.line([(0, cy), (canvas_w, cy)], fill=(r, g, b))

    font_title, font_label, font_small = _load_fonts()

    pad = 20
    y = pad

    _draw_rect(draw, [0, y, canvas_w, y + 62], radius=0, fill=(0, 80, 140))
    draw.text((pad + 12, y + 10), "OLLAMA REQUEST MONITOR", font=font_title, fill=(255, 255, 255))
    ts = datetime.now().strftime("%H:%M:%S")
    ts_w = draw.textbbox((0, 0), ts, font=font_label)[2]
    draw.text((canvas_w - ts_w - pad - 12, y + 14), ts, font=font_label, fill=(180, 230, 255))
    y += 68

    with _ollama_lock:
        requests = list(_ollama_requests)

    if not requests:
        draw.text((pad + 12, y + 24), "Waiting for requests...", font=font_label, fill=(220, 220, 255))
        draw.text((pad + 12, y + 68), f"Proxy: /ollama/ -> {_ollama_target}", font=font_small, fill=(160, 180, 220))
    else:
        for req in reversed(requests):
            if y > canvas_h - 70:
                break

            card_h = 96
            _draw_rect(draw, [pad, y, canvas_w - pad, y + card_h], radius=6, fill=(25, 45, 90))
            draw.rectangle([pad, y, pad + 4, y + card_h], fill=(0, 160, 255))

            method = req.get("method", "?")
            rpath  = req.get("path", "")
            model  = req.get("model", "")
            ip     = req.get("ip", "?")
            status = req.get("status", "---")
            dur    = req.get("duration_ms", "")
            ts_str = req.get("time", "")

            if isinstance(status, int) and status < 300:
                status_color = (80, 255, 140)
            elif isinstance(status, int) and status < 500:
                status_color = (255, 220, 50)
            else:
                status_color = (255, 80, 80)

            method_colors = {
                "GET": (30, 140, 255), "POST": (40, 200, 100),
                "PUT": (220, 160, 30), "DELETE": (220, 60, 60),
            }
            mc = method_colors.get(method, (120, 120, 180))
            mw = draw.textbbox((0, 0), method, font=font_label)[2] + 24
            _draw_rect(draw, [pad + 14, y + 12, pad + 14 + mw, y + 46], radius=5, fill=mc)
            draw.text((pad + 26, y + 12), method, font=font_label, fill=(255, 255, 255))

            display_path = rpath if len(rpath) <= 45 else rpath[:45] + "..."
            draw.text((pad + 14 + mw + 12, y + 14), display_path, font=font_label, fill=(240, 240, 255))

            status_text = str(status)
            sw = draw.textbbox((0, 0), status_text, font=font_label)[2]
            draw.text((canvas_w - pad - sw - 16, y + 14), status_text, font=font_label, fill=status_color)

            line2_parts = [f"  {ip}"]
            if model:
                m = model if len(model) <= 28 else model[:28] + "..."
                line2_parts.append(f"model:{m}")
            if dur:
                line2_parts.append(f"{dur}ms")
            if ts_str:
                line2_parts.append(ts_str)
            draw.text((pad + 14, y + 60), "   ".join(line2_parts), font=font_small, fill=(190, 210, 255))

            y += card_h + 6

    img = img.rotate(-90, expand=True)
    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=92)
    return buf.getvalue()


def _ollama_display_loop():
    """Background loop that re-renders the Ollama monitor on the LCD."""
    driver = _get_driver()
    while not _bg_stop.is_set():
        try:
            jpg = _render_ollama_display()
            if hasattr(driver, 'send_jpeg'):
                driver.send_jpeg(jpg)
            else:
                driver.write_frame(["[Ollama Monitor Active]"])
        except Exception as e:
            print(f"[ollama-monitor] render error: {e}", file=sys.stderr)
        _bg_stop.wait(timeout=1.5)

