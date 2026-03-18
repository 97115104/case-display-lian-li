#!/usr/bin/env python3
"""Simple local web UI for sending text to the LANCOOL 207 Digital display.

This is a minimal HTTP server that serves a static web page and exposes an
API endpoint that your code can call to send text to the display.

The display driver is NOT implemented here (because the protocol is unknown).
Instead this server calls `send_text_to_display()` which you can implement once
you know how to talk to the hardware.

Usage:
  python display_web_server.py

Then open http://localhost:8000/ in a browser.

Example API call (curl):
  curl -X POST http://localhost:8000/api/display \
    -H "Content-Type: application/json" \
    -d '{"text": "Hello from the API!", "meta": {"ip":"10.0.0.5"}}'
"""

from __future__ import annotations

import http.server
import json
import socketserver
import textwrap
from http import HTTPStatus
from typing import Any, Dict, Optional


def send_text_to_display(text: str, meta: Optional[Dict[str, Any]] = None) -> None:
    """Send text to the display.

    This function is a placeholder; implement the actual display protocol once
    you know how to communicate with the HW.

    Args:
        text: The text to render (plain text or a simple markup string).
        meta: Optional metadata (e.g., source IP, request path).
    """

    # TODO: Replace this with a real protocol implementation.
    #       A common approach is to open a USB/HID device and send a packet with
    #       a small header + UTF-8 payload.
    print("[display]", text)
    if meta:
        print("[display-meta]", json.dumps(meta, separators=(',', ':')))


INDEX_HTML = textwrap.dedent(
    """\
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="utf-8" />
      <title>Lian Li Display Tester</title>
      <style>
        body {font-family: system-ui, sans-serif; padding: 2rem;}
        textarea {width: 100%; height: 7rem; font-family: monospace;}
        button {padding: 0.6rem 1rem; margin-top: 0.75rem;}
        .status {margin-top: 1rem; white-space: pre-wrap;}
      </style>
    </head>
    <body>
      <h1>Lian Li Display Tester</h1>
      <p>Type some text and click <strong>Send</strong> to trigger the display API.</p>
      <textarea id="text" placeholder="Hello world!" spellcheck="false">Hello from the web UI!</textarea>
      <br />
      <button id="send">Send to display</button>
      <div class="status" id="status"></div>
      <script>
        const status = document.getElementById('status');
        const send = document.getElementById('send');
        const text = document.getElementById('text');

        send.addEventListener('click', async () => {
          status.textContent = 'Sending...';
          try {
            const resp = await fetch('/api/display', {
              method: 'POST',
              headers: {'Content-Type': 'application/json'},
              body: JSON.stringify({text: text.value}),
            });
            const data = await resp.json();
            if (!resp.ok) throw new Error(data.error || resp.statusText);
            status.textContent = 'Success: ' + (data.status || 'ok');
          } catch (err) {
            status.textContent = 'Error: ' + (err.message || err);
          }
        });
      </script>
    </body>
    </html>
    """
)


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(INDEX_HTML.encode("utf-8"))
            return
        super().do_GET()

    def do_POST(self) -> None:
        if self.path != "/api/display":
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return

        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            self.send_error(HTTPStatus.BAD_REQUEST, "Invalid JSON")
            return

        text = payload.get("text")
        if not isinstance(text, str) or not text.strip():
            self.send_error(HTTPStatus.BAD_REQUEST, "Missing text")
            return

        meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else None

        send_text_to_display(text, meta)

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "ok"}).encode("utf-8"))


def run_server(port: int = 8000) -> None:
    print(f"Starting web UI on http://localhost:{port}/")
    with socketserver.TCPServer(("127.0.0.1", port), Handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("Stopping server...")


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Start a tiny web UI to send text to the Lian Li display.")
    parser.add_argument("--port", type=int, default=8000, help="Port to listen on")
    args = parser.parse_args(argv)

    run_server(port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
