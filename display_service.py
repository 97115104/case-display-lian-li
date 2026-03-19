#!/usr/bin/env python3
"""Display service IPC subprocess.

Reads newline-delimited JSON commands from stdin (sent by server.js).
Writes newline-delimited JSON responses to stdout.
All display state (driver, background threads, Ollama log) lives here,
so the Node.js server can hot-reload without disrupting the LCD or USB.

Protocol:
  Request:  {"id": <int>, "cmd": "<name>", "args": {...}}
  Response: {"id": <int>, "ok": true,  "result": {...}}
            {"id": <int>, "ok": false, "error":  "<msg>"}
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time

# ── Protocol I/O ─────────────────────────────────────────────────────────────
# Save the real stdout fd for the protocol BEFORE redirecting.
# Then redirect Python's stdout to stderr so print()/libraries never corrupt
# the JSON stream.
_PROTO_OUT = sys.stdout
sys.stdout = sys.stderr  # safe from here on: print() → stderr

# ── Imports (after redirect so any stray prints go to stderr) ─────────────────
import display_web_server as _ws  # brings in all display state + helpers
from display_driver import show_text, usb_diag, sysfs_reset_usb
import display_driver as _dd


# ── Sudo fallback for USB reset ───────────────────────────────────────────────

def _sysfs_reset_sudo() -> dict:
    """Try unbind/bind via 'sudo tee' (works after setup-sudoers.sh)."""
    import subprocess
    import glob

    VID, PID = "1cbe", "f000"
    sysfs_path = None
    for dev in glob.glob("/sys/bus/usb/devices/*/idVendor"):
        try:
            with open(dev) as f:
                if f.read().strip() != VID:
                    continue
            pid_file = dev.replace("idVendor", "idProduct")
            with open(pid_file) as f:
                if f.read().strip() == PID:
                    sysfs_path = os.path.dirname(dev)
                    break
        except OSError:
            continue

    if sysfs_path is None:
        return {"ok": False, "method": "sudo_tee", "detail": "device not found in sysfs"}

    port = os.path.basename(sysfs_path)
    try:
        subprocess.run(
            ["sudo", "tee", "/sys/bus/usb/drivers/usb/unbind"],
            input=port.encode(), capture_output=True, check=True, timeout=5,
        )
        time.sleep(1.0)
        subprocess.run(
            ["sudo", "tee", "/sys/bus/usb/drivers/usb/bind"],
            input=port.encode(), capture_output=True, check=True, timeout=5,
        )
        time.sleep(0.5)
        return {"ok": True, "method": "sudo_tee_unbind_bind", "detail": port}
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode(errors="replace").strip()
        return {
            "ok": False, "method": "sudo_tee",
            "detail": f"sudo tee failed: {stderr} — run: sudo ./setup-sudoers.sh",
        }
    except Exception as e:
        return {"ok": False, "method": "sudo_tee", "detail": str(e)}


# ── Response helper ───────────────────────────────────────────────────────────

def _respond(rid: int, ok: bool, result=None, error=None) -> None:
    msg: dict = {"id": rid, "ok": ok}
    if ok:
        msg["result"] = result if result is not None else {}
    else:
        msg["error"] = str(error)
    _PROTO_OUT.write(json.dumps(msg) + "\n")
    _PROTO_OUT.flush()


# ── Command dispatcher ────────────────────────────────────────────────────────

def _dispatch(cmd: str, args: dict):  # noqa: C901
    # ── show_text ──────────────────────────────────────────────────────────
    if cmd == "show_text":
        text = args.get("text", "")
        if not text.strip():
            raise ValueError("empty text")
        _ws._stop_background()
        show_text(text.strip(), driver=_ws._get_driver())
        return {"status": "ok"}

    # ── action ─────────────────────────────────────────────────────────────
    if cmd == "action":
        return _handle_action(args)

    # ── diag ───────────────────────────────────────────────────────────────
    if cmd == "diag":
        d = usb_diag()
        drv = _ws._driver
        d["driver_type"] = type(drv).__name__
        d["driver_initialized"] = getattr(drv, "_initialized", None)
        d["driver_has_device"] = getattr(drv, "device", None) is not None
        d["bg_thread_alive"] = _ws._bg_thread is not None and _ws._bg_thread.is_alive()
        return d

    # ── log ────────────────────────────────────────────────────────────────
    if cmd == "get_log":
        return {"log": list(_ws._server_log)}

    # ── ollama ─────────────────────────────────────────────────────────────
    if cmd == "ollama_start":
        target = args.get("target", "").strip()
        if target:
            _ws._ollama_target = target.rstrip("/")
        _ws._stop_background()
        _ws._ollama_monitor_active = True
        with _ws._ollama_lock:
            _ws._ollama_requests.clear()
        _ws._run_in_background(_ws._ollama_display_loop)
        return {"status": "Monitor started", "target": _ws._ollama_target}

    if cmd == "ollama_stop":
        _ws._ollama_monitor_active = False
        _ws._stop_background()
        return {"status": "Monitor stopped"}

    if cmd == "ollama_get_log":
        with _ws._ollama_lock:
            reqs = list(_ws._ollama_requests)
        return {"requests": reqs, "active": _ws._ollama_monitor_active}

    if cmd == "ollama_log_request":
        entry = args.get("entry", {})
        with _ws._ollama_lock:
            _ws._ollama_requests.append(entry)
        return {}

    raise ValueError(f"Unknown command: {cmd!r}")


def _handle_action(args: dict):  # noqa: C901
    import subprocess

    action = args.get("action", "")

    if action == "hello":
        _ws._stop_background()
        script = os.path.join(os.path.dirname(__file__) or ".", "hello_lcd.py")

        def _hello():
            subprocess.run([sys.executable, script], timeout=30)

        _ws._run_in_background(_hello)
        return {"status": "Hello World sent"}

    if action == "dictionary":
        _ws._stop_background()
        _ws._run_in_background(_ws._dictionary_display_loop)
        return {"status": "Dictionary mode started"}

    if action == "pictures":
        image_dir = args.get("dir", "")
        interval = float(args.get("interval", 5))
        if not image_dir or not os.path.isdir(image_dir):
            return {"status": f"Directory not found: {image_dir}", "error": True}
        _ws._stop_background()

        def _pics():
            _ws._pictures_display_loop(image_dir, interval)

        _ws._run_in_background(_pics)
        return {"status": f"Slideshow started: {image_dir} ({interval}s)"}

    if action == "text":
        text = args.get("text", "").strip()
        if not text:
            return {"status": "No text provided", "error": True}
        _ws._stop_background()
        show_text(text, driver=_ws._get_driver())
        return {"status": f"Displayed: {text}"}

    if action == "stop":
        _ws._stop_background()
        _ws._ollama_monitor_active = False
        return {"status": "Stopped"}

    if action == "restart":
        _ws._slog("[restart] starting hard reset...")
        drv = _ws._restart_driver()
        ok = hasattr(drv, "device") and drv.device is not None
        if ok:
            try:
                show_text("LANCOOL 207\nReady", driver=drv)
            except Exception as e:
                _ws._slog(f"[restart] post-reset display write failed: {e}")
        msg = "Display reset and ready" if ok else "Reset attempted — no USB device found"
        _ws._slog(f"[restart] done: ok={ok}")
        return {"status": msg, "usb_ok": ok}

    if action == "force_reinit":
        _ws._slog("[force_reinit] starting...")
        drv = _ws._get_driver()
        ok = drv.force_reinit() if hasattr(drv, "force_reinit") else False
        if ok:
            try:
                show_text("LANCOOL 207\nReady", driver=drv)
            except Exception:
                pass
        _ws._slog(f"[force_reinit] done: ok={ok}")
        return {
            "status": "Force reinit OK" if ok else "Force reinit failed",
            "usb_ok": ok,
        }

    if action == "sysfs_reset":
        _ws._slog("[sysfs_reset] attempting kernel USB reset...")
        result = sysfs_reset_usb()
        _ws._slog(
            f"[sysfs_reset] result: ok={result['ok']} method={result.get('method')} "
            f"detail={result.get('detail')}"
        )

        # If permission denied, try via sudo (works after setup-sudoers.sh)
        if not result["ok"] and "Permission denied" in result.get("detail", ""):
            _ws._slog("[sysfs_reset] permission denied — trying sudo fallback...")
            result = _sysfs_reset_sudo()
            _ws._slog(
                f"[sysfs_reset] sudo result: ok={result['ok']} detail={result.get('detail')}"
            )

        if result["ok"]:
            time.sleep(3.0)
            _ws._slog("[sysfs_reset] re-enumerating driver...")
            drv = _ws._restart_driver()
            ok = hasattr(drv, "device") and drv.device is not None
            _ws._slog(f"[sysfs_reset] driver ok={ok}")
            result["driver_ok"] = ok
            if ok:
                try:
                    show_text("LANCOOL 207\nReady", driver=drv)
                except Exception:
                    pass
            result["status"] = (
                "USB reset OK, driver ready" if ok else "USB reset OK but driver not found"
            )
        else:
            need_setup = "Permission denied" in result.get("detail", "")
            result["status"] = (
                "Permission denied — run: sudo ./setup-sudoers.sh  (once, then retry)"
                if need_setup
                else f"sysfs reset failed: {result.get('detail', '')}"
            )
        return result

    raise ValueError(f"Unknown action: {action!r}")


# ── Request handler (runs in a worker thread) ─────────────────────────────────

def _handle(req: dict) -> None:
    rid = req.get("id")
    try:
        result = _dispatch(req.get("cmd", ""), req.get("args", {}))
        _respond(rid, True, result)
    except Exception as exc:
        _respond(rid, False, error=exc)


# ── Main loop ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("[display_service] started, waiting for commands...", file=sys.stderr, flush=True)
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            req = json.loads(raw)
        except json.JSONDecodeError as exc:
            print(f"[display_service] bad JSON: {exc}", file=sys.stderr, flush=True)
            continue
        threading.Thread(target=_handle, args=(req,), daemon=True).start()
