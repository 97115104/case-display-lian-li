#!/usr/bin/env python3
"""Utility runner for testing display output locally.

This script does *not* drive the real Lian Li display (protocol unknown), but it
provides a framework for:

- Repeatedly displaying a custom message
- Displaying random "esoteric" dictionary words
- Acting as a proxy that displays request progress + history

The display output is currently printed to stdout and written to ./display_output.txt.
Once you know the protocol, plug in a real implementation in `display_driver.py`.
"""

from __future__ import annotations

import argparse
import random
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, List, Optional

from display_driver import DisplayDriver, make_driver, show_dashboard, show_text


ESOTERIC_WORDS: Dict[str, str] = {
    "abecedarian": "A person who is learning the alphabet; someone very inexperienced.",
    "cymotrichous": "Having wavy hair.",
    "defenestrate": "To throw someone or something out of a window.",
    "eschatology": "The part of theology concerned with death, judgment, and the final destiny of the soul.",
    "floccinaucinihilipilification": "The act of estimating something as worthless.",
    "gargalesthesia": "The sensation produced by tickling.",
    "hiraeth": "A homesickness for a home to which you cannot return; nostalgia.",
    "ineffable": "Too great or extreme to be expressed or described in words.",
    "juxtaposition": "The fact of two things being seen or placed close together with contrasting effect.",
    "knismesis": "A light, tickling sensation.",
    "limerence": "The state of being infatuated with another person.",
    "mnemonic": "A device such as a pattern of letters used to aid memory.",
    "nemophilist": "One who loves the woods or forest; a haunter of the woods.",
    "obfuscate": "Render obscure, unclear, or unintelligible.",
    "palimpsest": "Something reused or altered but still bearing visible traces of its earlier form.",
    "querencia": "A place where one feels safe, a place from which one’s strength is drawn.",
    "recumbentibus": "A knockout punch, either verbal or physical.",
    "susurrus": "A whispering or rustling sound.",
    "threnody": "A lament, especially a song or poem of mourning.",
    "ultracrepidarian": "Someone who gives opinions on subjects they know nothing about.",
    "venustraphobia": "Fear of beautiful women.",
    "wyrd": "Fate or personal destiny.",
    "xenization": "The act of traveling as a stranger.",
    "yugen": "A profound, mysterious sense of the beauty of the universe.",
    "zoanthropy": "A delusion that one is an animal.",
}


def run_repeat(text: str, interval: float, driver: Optional[DisplayDriver] = None) -> None:
    if driver is None:
        driver = make_driver()

    try:
        while True:
            show_text(text, driver=driver)
            time.sleep(interval)
    except KeyboardInterrupt:
        print("Stopped repeating.")


def run_dictionary(interval: float, driver: Optional[DisplayDriver] = None) -> None:
    if driver is None:
        driver = make_driver()

    try:
        while True:
            word, definition = random.choice(list(ESOTERIC_WORDS.items()))
            show_text(f"{word}\n{definition}", driver=driver)
            time.sleep(interval)
    except KeyboardInterrupt:
        print("Stopped dictionary mode.")


class RequestHistoryItem:
    def __init__(self, client_ip: str, method: str, path: str):
        self.client_ip = client_ip
        self.method = method
        self.path = path
        self.start_ts = time.time()
        self.end_ts: Optional[float] = None
        self.status: Optional[int] = None

    def finish(self, status: int) -> None:
        self.status = status
        self.end_ts = time.time()

    def duration_ms(self) -> Optional[int]:
        if self.end_ts is None:
            return None
        return int((self.end_ts - self.start_ts) * 1000)

    def summary(self) -> str:
        dur = self.duration_ms()
        dur_s = f"{dur}ms" if dur is not None else "..."
        status = self.status if self.status is not None else "..."
        return f"{self.client_ip} {self.method} {self.path} {status} {dur_s}"


class ProxyHandler(BaseHTTPRequestHandler):
    history: List[RequestHistoryItem] = []
    target_host: str = ""
    target_port: int = 0
    driver: Optional[DisplayDriver] = None

    def _update_display(self, current: RequestHistoryItem) -> None:
        lines: List[str] = [
            "Proxy monitor",
            "--",
            f"{current.method} {current.path}",
            f"from {current.client_ip}",
            "",
            "Recent:",
        ]
        # show last 6 requests
        for it in list(self.history)[-6:]:
            lines.append(it.summary())
        show_dashboard("Proxy status", lines, driver=self.driver)

    def log_message(self, format: str, *args: Any) -> None:
        # suppress default logging
        return

    def do_GET(self) -> None:
        self._serve_request()

    def do_POST(self) -> None:
        self._serve_request()

    def _serve_request(self) -> None:
        client_ip = self.client_address[0]
        item = RequestHistoryItem(client_ip, self.command, self.path)
        self.history.append(item)
        self._update_display(item)

        # Forward the request to the target
        try:
            import http.client
            import urllib.parse

            parsed = urllib.parse.urlparse(self.target_host)
            conn = http.client.HTTPConnection(parsed.hostname, parsed.port or self.target_port, timeout=15)
            conn.putrequest(self.command, self.path, skip_host=True)

            # Copy headers
            for key, value in self.headers.items():
                if key.lower() == "host":
                    continue
                conn.putheader(key, value)
            conn.putheader("Host", parsed.hostname)
            conn.endheaders()

            length = int(self.headers.get("Content-Length", "0"))
            if length > 0:
                body = self.rfile.read(length)
                conn.send(body)

            resp = conn.getresponse()
            data = resp.read()

            self.send_response(resp.status)
            for key, value in resp.headers.items():
                # Avoid sending hop-by-hop headers
                if key.lower() in ("transfer-encoding", "connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers", "upgrade"):
                    continue
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(data)

            item.finish(resp.status)
        except Exception as e:
            item.finish(500)
            self.send_response(HTTPStatus.INTERNAL_SERVER_ERROR)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(str(e).encode("utf-8"))
        finally:
            self._update_display(item)


def run_proxy(target: str, listen_port: int, driver: Optional[DisplayDriver] = None) -> None:
    if driver is None:
        driver = make_driver()

    # If target doesn't include scheme, assume http://
    if "://" not in target:
        target = "http://" + target

    parsed = target

    ProxyHandler.target_host = target
    ProxyHandler.driver = driver

    server = HTTPServer(("", listen_port), ProxyHandler)
    print(f"Proxy listening on http://localhost:{listen_port}/ -> {target}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping proxy.")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Test display output on the console and (later) on actual hardware.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    rep = sub.add_parser("repeat", help="Repeat a message on the display at a regular interval.")
    rep.add_argument("--text", required=True, help="Text to display repeatedly.")
    rep.add_argument("--interval", type=float, default=2.0, help="Seconds between updates.")

    dictp = sub.add_parser("dictionary", help="Display random esoteric words on the display.")
    dictp.add_argument("--interval", type=float, default=3.0, help="Seconds between words.")

    prox = sub.add_parser("proxy", help="Run a proxy that displays request progress.")
    prox.add_argument("--target", required=True, help="Target server to proxy to (e.g., http://localhost:8080).")
    prox.add_argument("--listen", type=int, default=8001, help="Port to listen on locally.")

    args = parser.parse_args(argv)

    driver = make_driver()

    if args.cmd == "repeat":
        run_repeat(args.text, args.interval, driver=driver)
    elif args.cmd == "dictionary":
        run_dictionary(args.interval, driver=driver)
    elif args.cmd == "proxy":
        run_proxy(args.target, args.listen, driver=driver)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
