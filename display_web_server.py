#!/usr/bin/env python3
"""Web dashboard for the Lian Li LANCOOL 207 Digital LCD.

Serves a web UI on port 8008 that lets you:
- Send custom text to the LCD
- Run hello / repeat / dictionary modes
- Monitor Ollama API requests and display them on the LCD

The Ollama monitor acts as a reverse proxy: point your Ollama clients at this
server's /ollama/ path (e.g. http://localhost:8008/ollama/) and it will forward
requests to the real Ollama server while logging them on the LCD.
"""

from __future__ import annotations

import io
import json
import os
import struct
import sys
import textwrap
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, List, Optional

from display_driver import (
    DISPLAY_H,
    DISPLAY_W,
    UsbDisplayDriver,
    make_driver,
    show_text,
)

# ── State ────────────────────────────────────────────────────────────────────

_driver = None
_driver_lock = threading.Lock()

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
    """Tear down and re-create the USB driver."""
    global _driver
    _stop_background()
    with _driver_lock:
        old = _driver
        _driver = None
        if old and hasattr(old, 'device') and old.device is not None:
            import usb.util
            dev = old.device
            try:
                usb.util.release_interface(dev, 0)
            except Exception:
                pass
            try:
                usb.util.dispose_resources(dev)
            except Exception:
                pass
            old.device = None
            old.ep_out = None
            old.ep_in = None
            old._initialized = False
        time.sleep(1)
        _driver = make_driver()
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

def _render_ollama_display():
    """Render the current Ollama request log onto the LCD."""
    from PIL import Image, ImageDraw, ImageFont

    canvas_w, canvas_h = DISPLAY_W, DISPLAY_H  # 1472 x 720 landscape
    img = Image.new('RGB', (canvas_w, canvas_h), color=(15, 15, 25))
    draw = ImageDraw.Draw(img)

    # Gradient background
    for y in range(canvas_h):
        r = int(15 + 15 * (y / canvas_h))
        g = int(15 + 10 * (y / canvas_h))
        b = int(25 + 35 * (y / canvas_h))
        draw.line([(0, y), (canvas_w, y)], fill=(r, g, b))

    # Load fonts
    font_title = font_label = font_body = font_small = None
    for path in [
        "/usr/share/fonts/TTF/DejaVuSansMono-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
        "/usr/share/fonts/dejavu-sans-fonts/DejaVuSansMono-Bold.ttf",
    ]:
        try:
            font_title = ImageFont.truetype(path, 38)
            font_label = ImageFont.truetype(path, 28)
            break
        except (IOError, OSError):
            continue
    for path in [
        "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/dejavu-sans-fonts/DejaVuSansMono.ttf",
    ]:
        try:
            font_body = ImageFont.truetype(path, 24)
            font_small = ImageFont.truetype(path, 20)
            break
        except (IOError, OSError):
            continue
    if font_title is None:
        font_title = font_label = font_body = font_small = ImageFont.load_default()

    pad = 24
    y = pad

    # Title bar
    draw.rounded_rectangle(
        [pad, y, canvas_w - pad, y + 56], radius=10,
        fill=(25, 25, 45, 200)
    )
    draw.text((pad + 16, y + 8), "OLLAMA REQUEST MONITOR", font=font_title, fill=(100, 200, 255))
    ts = datetime.now().strftime("%H:%M:%S")
    ts_w = draw.textbbox((0, 0), ts, font=font_label)[2]
    draw.text((canvas_w - pad - ts_w - 16, y + 14), ts, font=font_label, fill=(120, 120, 160))
    y += 72

    with _ollama_lock:
        requests = list(_ollama_requests)

    if not requests:
        draw.text((pad + 16, y + 20), "Waiting for requests...", font=font_label, fill=(80, 80, 120))
        draw.text((pad + 16, y + 60), f"Proxy: /ollama/ -> {_ollama_target}", font=font_small, fill=(60, 60, 100))
    else:
        # Show recent requests, newest first, filling available space
        for req in reversed(requests):
            if y > canvas_h - 60:
                break

            # Card background
            card_h = 88
            draw.rounded_rectangle(
                [pad, y, canvas_w - pad, y + card_h], radius=8,
                fill=(20, 22, 38)
            )

            # Method + path
            method = req.get("method", "?")
            path = req.get("path", "")
            model = req.get("model", "")
            ip = req.get("ip", "?")
            status = req.get("status", "...")
            dur = req.get("duration_ms", "")
            ts_str = req.get("time", "")

            # Status color
            if isinstance(status, int) and status < 300:
                status_color = (80, 220, 130)
            elif isinstance(status, int) and status < 500:
                status_color = (255, 200, 60)
            else:
                status_color = (255, 80, 80)

            # Method pill
            method_colors = {
                "GET": (60, 160, 220), "POST": (100, 200, 100),
                "PUT": (220, 180, 60), "DELETE": (220, 80, 80),
            }
            mc = method_colors.get(method, (150, 150, 150))
            mw = draw.textbbox((0, 0), method, font=font_label)[2] + 20
            draw.rounded_rectangle(
                [pad + 12, y + 10, pad + 12 + mw, y + 42], radius=6, fill=mc
            )
            draw.text((pad + 22, y + 10), method, font=font_label, fill=(255, 255, 255))

            # Path (truncated)
            display_path = path
            if len(display_path) > 40:
                display_path = display_path[:40] + "..."
            draw.text((pad + 22 + mw + 10, y + 12), display_path, font=font_label, fill=(200, 200, 220))

            # Status code
            status_text = str(status)
            sw = draw.textbbox((0, 0), status_text, font=font_label)[2]
            draw.text((canvas_w - pad - sw - 16, y + 12), status_text, font=font_label, fill=status_color)

            # Second line: IP, model, duration, timestamp
            line2_parts = []
            line2_parts.append(f"IP: {ip}")
            if model:
                m = model if len(model) <= 25 else model[:25] + "..."
                line2_parts.append(f"Model: {m}")
            if dur:
                line2_parts.append(f"{dur}ms")
            if ts_str:
                line2_parts.append(ts_str)
            line2 = "   ".join(line2_parts)
            draw.text((pad + 16, y + 52), line2, font=font_small, fill=(110, 115, 145))

            y += card_h + 8

    # Rotate for portrait display
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
                from display_driver import _build_jpeg_packet
                driver.write_frame(["[Ollama Monitor Active]"])
        except Exception as e:
            print(f"[ollama-monitor] render error: {e}", file=sys.stderr)
        _bg_stop.wait(timeout=1.5)


# ── HTML Dashboard ───────────────────────────────────────────────────────────

INDEX_HTML = textwrap.dedent("""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LANCOOL 207 LCD Dashboard</title>
<style>
  :root {
    --bg: #0d0f1a; --surface: #161929; --border: #232840;
    --text: #e0e0e8; --muted: #6b7094; --accent: #4ea4f6;
    --green: #50dc82; --red: #f25f5c; --orange: #f2a65a;
  }
  * { margin:0; padding:0; box-sizing:border-box; }
  body {
    font-family: 'Inter', system-ui, -apple-system, sans-serif;
    background: var(--bg); color: var(--text);
    min-height: 100vh; padding: 2rem;
  }
  h1 { font-size: 1.6rem; font-weight: 700; margin-bottom: .3rem; }
  .subtitle { color: var(--muted); font-size: .85rem; margin-bottom: 2rem; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; max-width: 900px; }
  @media (max-width: 700px) { .grid { grid-template-columns: 1fr; } }
  .card {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 12px; padding: 1.4rem;
  }
  .card h2 { font-size: 1rem; font-weight: 600; margin-bottom: 1rem; color: var(--accent); }
  label { display: block; font-size: .8rem; color: var(--muted); margin-bottom: .3rem; margin-top: .8rem; }
  label:first-child { margin-top: 0; }
  input, textarea {
    width: 100%; padding: .55rem .7rem; font-size: .85rem;
    background: var(--bg); color: var(--text); border: 1px solid var(--border);
    border-radius: 8px; outline: none; font-family: 'JetBrains Mono', monospace;
  }
  input:focus, textarea:focus { border-color: var(--accent); }
  textarea { height: 5rem; resize: vertical; }
  .btn {
    display: inline-block; padding: .55rem 1.2rem; margin-top: .8rem;
    font-size: .85rem; font-weight: 600; border: none; border-radius: 8px;
    cursor: pointer; transition: opacity .15s;
  }
  .btn:hover { opacity: .85; }
  .btn-blue { background: var(--accent); color: #fff; }
  .btn-green { background: var(--green); color: #111; }
  .btn-orange { background: var(--orange); color: #111; }
  .btn-red { background: var(--red); color: #fff; }
  .btn-sm { padding: .4rem .9rem; font-size: .8rem; }
  .status {
    margin-top: .6rem; font-size: .8rem; color: var(--muted);
    min-height: 1.2rem; font-family: monospace;
  }
  .status.ok { color: var(--green); }
  .status.err { color: var(--red); }
  .log-box {
    background: var(--bg); border: 1px solid var(--border); border-radius: 8px;
    padding: .7rem; margin-top: .8rem; max-height: 300px; overflow-y: auto;
    font-family: 'JetBrains Mono', monospace; font-size: .75rem; line-height: 1.5;
  }
  .log-entry { padding: .25rem 0; border-bottom: 1px solid var(--border); }
  .log-entry:last-child { border-bottom: none; }
  .log-method { font-weight: 700; }
  .log-method.POST { color: var(--green); }
  .log-method.GET { color: var(--accent); }
  .log-ip { color: var(--orange); }
  .log-model { color: #c792ea; }
  .log-status { font-weight: 600; }
  .log-status.ok { color: var(--green); }
  .log-status.err { color: var(--red); }
  .log-time { color: var(--muted); }
  .wide { grid-column: 1 / -1; }
  .row { display: flex; gap: .6rem; flex-wrap: wrap; align-items: end; }
  .row > * { flex: 1; min-width: 120px; }
  .indicator { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: .4rem; }
  .indicator.on { background: var(--green); box-shadow: 0 0 6px var(--green); }
  .indicator.off { background: var(--muted); }
</style>
</head>
<body>
<h1>LANCOOL 207 LCD Dashboard</h1>
<p class="subtitle">Lian Li LANCOOL 207 Digital -- LCD Control Panel</p>

<div class="grid">

  <!-- Send Text -->
  <div class="card">
    <h2>Send Text</h2>
    <label for="text-input">Message</label>
    <textarea id="text-input" placeholder="Hello World!">Hello World!</textarea>
    <button class="btn btn-blue" onclick="sendText()">Send to LCD</button>
    <div class="status" id="text-status"></div>
  </div>

  <!-- Quick Actions -->
  <div class="card">
    <h2>Quick Actions</h2>
    <p style="font-size:.8rem;color:var(--muted);margin-bottom:.8rem">
      Run built-in display modes. Each mode takes over the LCD until stopped.
    </p>
    <button class="btn btn-green btn-sm" onclick="runAction('hello')">Hello World</button>
    <button class="btn btn-blue btn-sm" onclick="runAction('dictionary')">Random Words</button>
    <button class="btn btn-red btn-sm" onclick="runAction('stop')">Stop</button>
    <button class="btn btn-orange btn-sm" onclick="runAction('restart')" style="margin-left:.5rem">Restart Display</button>
    <div class="status" id="action-status"></div>
  </div>

  <!-- Ollama Monitor -->
  <div class="card wide">
    <h2><span class="indicator off" id="ollama-dot"></span>Ollama Request Monitor</h2>
    <p style="font-size:.8rem;color:var(--muted);margin-bottom:.8rem">
      Proxies requests to Ollama and displays them on the LCD in real time.
      Point your clients at <code style="color:var(--accent)">http://&lt;this-host&gt;:8008/ollama/</code>
    </p>
    <div class="row">
      <div>
        <label for="ollama-target">Ollama server URL</label>
        <input id="ollama-target" value="http://localhost:11434" placeholder="http://localhost:11434">
      </div>
      <div style="flex:0 0 auto">
        <button class="btn btn-green btn-sm" onclick="ollamaStart()" id="ollama-start-btn">Start Monitor</button>
        <button class="btn btn-red btn-sm" onclick="ollamaStop()">Stop</button>
      </div>
    </div>
    <div class="status" id="ollama-status"></div>
    <div class="log-box" id="ollama-log">
      <div style="color:var(--muted)">No requests yet.</div>
    </div>
  </div>

</div>

<script>
const API = '';

async function api(path, body) {
  const resp = await fetch(API + path, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  });
  return resp.json();
}

function setStatus(id, msg, ok) {
  const el = document.getElementById(id);
  el.textContent = msg;
  el.className = 'status ' + (ok ? 'ok' : (ok === false ? 'err' : ''));
}

async function sendText() {
  const text = document.getElementById('text-input').value;
  if (!text.trim()) return;
  setStatus('text-status', 'Sending...');
  try {
    const r = await api('/api/display', {text});
    setStatus('text-status', 'Sent', true);
  } catch (e) { setStatus('text-status', 'Error: ' + e.message, false); }
}

async function runAction(action) {
  setStatus('action-status', 'Running ' + action + '...');
  try {
    const r = await api('/api/action', {action});
    setStatus('action-status', r.status || 'ok', true);
  } catch (e) { setStatus('action-status', 'Error: ' + e.message, false); }
}

async function ollamaStart() {
  const target = document.getElementById('ollama-target').value.trim();
  setStatus('ollama-status', 'Starting...');
  try {
    const r = await api('/api/ollama/start', {target});
    setStatus('ollama-status', 'Monitor active -- proxy: /ollama/', true);
    document.getElementById('ollama-dot').className = 'indicator on';
  } catch (e) { setStatus('ollama-status', 'Error: ' + e.message, false); }
}

async function ollamaStop() {
  try {
    await api('/api/ollama/stop', {});
    setStatus('ollama-status', 'Stopped', false);
    document.getElementById('ollama-dot').className = 'indicator off';
  } catch (e) {}
}

// Poll for new Ollama request log entries
let lastLogLen = 0;
async function pollLog() {
  try {
    const r = await fetch('/api/ollama/log');
    const data = await r.json();
    const box = document.getElementById('ollama-log');
    if (data.requests && data.requests.length > 0) {
      // Render newest-first
      box.innerHTML = data.requests.slice().reverse().map(req => {
        const sc = (req.status && req.status < 300) ? 'ok' : 'err';
        const model = req.model ? `<span class="log-model">${req.model}</span> ` : '';
        return `<div class="log-entry">` +
          `<span class="log-method ${req.method}">${req.method}</span> ` +
          `${req.path} ` + model +
          `<span class="log-ip">${req.ip}</span> ` +
          `<span class="log-status ${sc}">${req.status || '...'}</span> ` +
          (req.duration_ms ? `${req.duration_ms}ms ` : '') +
          `<span class="log-time">${req.time || ''}</span>` +
          `</div>`;
      }).join('');
    }
    if (data.active) {
      document.getElementById('ollama-dot').className = 'indicator on';
    }
  } catch (e) {}
}
setInterval(pollLog, 2000);
pollLog();
</script>
</body>
</html>
""")


# ── HTTP Handler ─────────────────────────────────────────────────────────────

class DashboardHandler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        # Suppress default access logs
        pass

    def _json_response(self, data: dict, status: int = 200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error_json(self, status: int, msg: str):
        self._json_response({"error": msg}, status)

    # ── GET routes ──

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            body = INDEX_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path == "/api/ollama/log":
            with _ollama_lock:
                reqs = list(_ollama_requests)
            self._json_response({"requests": reqs, "active": _ollama_monitor_active})
            return

        # Ollama proxy (GET requests)
        if self.path.startswith("/ollama/"):
            self._proxy_ollama()
            return

        self.send_error(404)

    # ── POST routes ──

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length > 0 else b""

        # Ollama proxy
        if self.path.startswith("/ollama/"):
            self._proxy_ollama(raw)
            return

        # Parse JSON for API routes
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            self._error_json(400, "Invalid JSON")
            return

        if self.path == "/api/display":
            text = payload.get("text", "")
            if not isinstance(text, str) or not text.strip():
                self._error_json(400, "Missing text")
                return
            _stop_background()
            show_text(text.strip(), driver=_get_driver())
            self._json_response({"status": "ok"})
            return

        if self.path == "/api/action":
            action = payload.get("action", "")
            return self._handle_action(action)

        if self.path == "/api/ollama/start":
            return self._handle_ollama_start(payload)

        if self.path == "/api/ollama/stop":
            return self._handle_ollama_stop()

        self.send_error(404)

    def do_DELETE(self):
        if self.path.startswith("/ollama/"):
            self._proxy_ollama()
            return
        self.send_error(404)

    def do_PUT(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length > 0 else b""
        if self.path.startswith("/ollama/"):
            self._proxy_ollama(raw)
            return
        self.send_error(404)

    # ── Action handler ──

    def _handle_action(self, action: str):
        if action == "hello":
            _stop_background()
            def _hello():
                import subprocess
                script = os.path.join(os.path.dirname(__file__) or ".", "hello_lcd.py")
                env = os.environ.copy()
                subprocess.run([sys.executable, script], env=env, timeout=30)
            _run_in_background(_hello)
            self._json_response({"status": "Hello World sent"})
            return

        if action == "dictionary":
            _stop_background()
            def _dict_loop():
                import random
                from display_runner import ESOTERIC_WORDS
                driver = _get_driver()
                while not _bg_stop.is_set():
                    word, defn = random.choice(list(ESOTERIC_WORDS.items()))
                    show_text(f"{word}\n{defn}", driver=driver)
                    _bg_stop.wait(timeout=4)
            _run_in_background(_dict_loop)
            self._json_response({"status": "Dictionary mode started"})
            return

        if action == "stop":
            _stop_background()
            global _ollama_monitor_active
            _ollama_monitor_active = False
            self._json_response({"status": "Stopped"})
            return

        if action == "restart":
            drv = _restart_driver()
            ok = hasattr(drv, 'device') and drv.device is not None
            self._json_response({"status": "Display restarted" if ok else "Reconnected (console only - no USB device found)"})
            return

        self._error_json(400, f"Unknown action: {action}")

    # ── Ollama monitor ──

    def _handle_ollama_start(self, payload: dict):
        global _ollama_target, _ollama_monitor_active
        target = payload.get("target", "").strip()
        if target:
            _ollama_target = target.rstrip("/")
        _stop_background()
        _ollama_monitor_active = True
        with _ollama_lock:
            _ollama_requests.clear()
        _run_in_background(_ollama_display_loop)
        self._json_response({"status": "Monitor started", "target": _ollama_target})

    def _handle_ollama_stop(self):
        global _ollama_monitor_active
        _ollama_monitor_active = False
        _stop_background()
        self._json_response({"status": "Monitor stopped"})

    def _proxy_ollama(self, body: bytes = b""):
        """Forward a request to the Ollama server and log it."""
        # Build the target URL
        ollama_path = self.path[len("/ollama"):]  # strip /ollama prefix
        if not ollama_path:
            ollama_path = "/"
        target_url = _ollama_target + ollama_path

        client_ip = self.client_address[0]
        method = self.command

        # Try to extract model from JSON body
        model = ""
        if body:
            try:
                j = json.loads(body)
                model = j.get("model", "")
            except Exception:
                pass

        req_entry = {
            "method": method,
            "path": ollama_path,
            "ip": client_ip,
            "model": model,
            "status": None,
            "duration_ms": None,
            "time": datetime.now().strftime("%H:%M:%S"),
        }

        start = time.time()
        try:
            req = urllib.request.Request(target_url, data=body if body else None, method=method)
            # Copy relevant headers
            for key in ("Content-Type", "Accept", "Authorization"):
                val = self.headers.get(key)
                if val:
                    req.add_header(key, val)

            with urllib.request.urlopen(req, timeout=120) as resp:
                resp_body = resp.read()
                resp_status = resp.status

                req_entry["status"] = resp_status
                req_entry["duration_ms"] = int((time.time() - start) * 1000)

                self.send_response(resp_status)
                for key, val in resp.headers.items():
                    if key.lower() not in ("transfer-encoding", "connection"):
                        self.send_header(key, val)
                self.end_headers()
                self.wfile.write(resp_body)

        except urllib.error.HTTPError as e:
            req_entry["status"] = e.code
            req_entry["duration_ms"] = int((time.time() - start) * 1000)
            resp_body = e.read()
            self.send_response(e.code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(resp_body)

        except Exception as e:
            req_entry["status"] = 502
            req_entry["duration_ms"] = int((time.time() - start) * 1000)
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

        with _ollama_lock:
            _ollama_requests.append(req_entry)


# ── Server ───────────────────────────────────────────────────────────────────

class ThreadedHTTPServer(HTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def process_request(self, request, client_address):
        t = threading.Thread(target=self.process_request_thread,
                             args=(request, client_address), daemon=True)
        t.start()

    def process_request_thread(self, request, client_address):
        try:
            self.finish_request(request, client_address)
        except Exception:
            self.handle_error(request, client_address)
        finally:
            self.shutdown_request(request)


def run_server(port: int = 8008) -> None:
    server = ThreadedHTTPServer(("0.0.0.0", port), DashboardHandler)
    print(f"Dashboard: http://localhost:{port}/")
    print(f"Ollama proxy: http://localhost:{port}/ollama/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        _stop_background()
        print("\nStopped.")


def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="LANCOOL 207 LCD Dashboard")
    parser.add_argument("--port", type=int, default=8008, help="Port to listen on")
    args = parser.parse_args(argv)
    run_server(port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
