#!/usr/bin/env python3.11
"""
SPY Auto Trader — macOS Desktop App
====================================

Standalone launcher that:
  1. Spawns the Flask + Socket.IO server (scripts/app.py) as a child process.
  2. Waits until the server responds on http://127.0.0.1:5000/health.
  3. Opens a native macOS window (WebKit via pywebview) pointed at the server.
  4. Cleanly terminates the server when the window is closed.

Run:
    venv/bin/python3.11 desktop.py

Notes:
- This file is INTENTIONALLY separate from scripts/app.py. The webapp is
  unchanged and can still be run standalone via `venv/bin/python3.11 scripts/app.py`.
- For a distributable .app bundle, see setup_py2app.py (separate effort).
"""

import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
HOST              = "127.0.0.1"
PORT              = 5000
HEALTH_URL        = f"http://{HOST}:{PORT}/health"
DASHBOARD_URL     = f"http://{HOST}:{PORT}/"
STARTUP_TIMEOUT_S = 20      # seconds to wait for Flask to start serving
WINDOW_TITLE      = "SPY Auto Trader"
WINDOW_WIDTH      = 1500
WINDOW_HEIGHT     = 950
WINDOW_MIN_W      = 1100
WINDOW_MIN_H      = 700

REPO_ROOT  = Path(__file__).resolve().parent
APP_SCRIPT = REPO_ROOT / "scripts" / "app.py"
PYTHON_BIN = REPO_ROOT / "venv" / "bin" / "python3.11"


# ── Helpers ───────────────────────────────────────────────────────────────────
def _port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        try:
            s.connect((host, port))
            return True
        except (ConnectionRefusedError, OSError):
            return False


def _wait_for_health(timeout_s: int) -> bool:
    """Poll /health until 200 or timeout. Returns True on success."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(HEALTH_URL, timeout=1.0) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.4)
    return False


def _spawn_flask() -> subprocess.Popen:
    """Spawn scripts/app.py as a child process in a new process group so we
    can SIGTERM the whole thing cleanly on exit."""
    if not APP_SCRIPT.exists():
        print(f"ERROR: app script not found at {APP_SCRIPT}", file=sys.stderr)
        sys.exit(1)
    if not PYTHON_BIN.exists():
        print(f"ERROR: venv python not found at {PYTHON_BIN}", file=sys.stderr)
        print("Run: python3.11 -m venv venv && venv/bin/pip install -r requirements.txt",
              file=sys.stderr)
        sys.exit(1)

    # Log Flask stdout/stderr to a file so we don't lose it
    log_path = REPO_ROOT / "desktop_flask.log"
    log_fp = open(log_path, "a", buffering=1)  # line-buffered
    log_fp.write(f"\n\n--- desktop.py spawning Flask at {time.ctime()} ---\n")

    proc = subprocess.Popen(
        [str(PYTHON_BIN), str(APP_SCRIPT)],
        cwd=str(REPO_ROOT),
        stdout=log_fp,
        stderr=subprocess.STDOUT,
        start_new_session=True,   # new process group so we can kill children too
    )
    print(f"Spawned Flask PID {proc.pid} (logs → {log_path})")
    return proc


def _shutdown_flask(proc: subprocess.Popen) -> None:
    """Terminate the Flask process group cleanly. Falls back to SIGKILL."""
    if proc is None or proc.poll() is not None:
        return
    try:
        # Kill the whole process group (Flask + any background threads)
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        print("Flask didn't exit on SIGTERM — sending SIGKILL")
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> int:
    import webview   # imported here so import errors surface AFTER spawn check

    # If the server is already running (e.g. you launched scripts/app.py
    # in another terminal), just open the window — don't double-spawn.
    flask_proc = None
    if _port_in_use(HOST, PORT):
        print(f"Flask already running on {HOST}:{PORT} — using existing instance")
    else:
        flask_proc = _spawn_flask()
        print(f"Waiting up to {STARTUP_TIMEOUT_S}s for Flask to come up…")
        if not _wait_for_health(STARTUP_TIMEOUT_S):
            print(f"ERROR: Flask did not respond on {HEALTH_URL} within "
                  f"{STARTUP_TIMEOUT_S}s. Check desktop_flask.log.", file=sys.stderr)
            _shutdown_flask(flask_proc)
            return 1
        print(f"Flask healthy at {HEALTH_URL}")

    # Create the native macOS window
    window = webview.create_window(
        title=WINDOW_TITLE,
        url=DASHBOARD_URL,
        width=WINDOW_WIDTH,
        height=WINDOW_HEIGHT,
        min_size=(WINDOW_MIN_W, WINDOW_MIN_H),
        background_color="#04070e",   # match dashboard dark theme
        confirm_close=False,
        text_select=True,
    )

    # Cleanup when window closes — only kill the Flask process WE spawned;
    # leave any pre-existing instance alone.
    def _on_closed():
        if flask_proc is not None:
            print("Window closed — shutting down spawned Flask process")
            _shutdown_flask(flask_proc)

    window.events.closed += _on_closed

    # Block until the window is closed
    try:
        webview.start(debug=False)
    finally:
        if flask_proc is not None:
            _shutdown_flask(flask_proc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
