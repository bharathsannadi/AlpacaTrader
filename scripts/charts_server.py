#!/usr/bin/env python3
"""
charts_server.py — standalone CHARTS-ONLY web server (default port 5001).

Decoupled from the main trading app (:5000) per operator request 2026-06-01.
Serves the same charts UI with **no Alpaca login and no trading**: bars and
indicator overlays come from yfinance via spy_auto_trader (importing that module
does NOT construct a TradingClient — login only happens in its `login()` fn).

Why a separate server: charts must be viewable independently of trading-app
state or login. The full universe (scripts/universe.py ALL) is selectable.

Run:
  PYTHONPATH=venv/lib/python3.11/site-packages \
    venv/bin/python3.11 scripts/charts_server.py        # → http://localhost:5001/charts
"""
from __future__ import annotations

import eventlet
eventlet.monkey_patch()

import os
import sys
import time
import logging
import threading

from flask import Flask, render_template, redirect
from flask_socketio import SocketIO

sys.path.insert(0, os.path.dirname(__file__))
import spy_auto_trader as trader          # yfinance data path; no Alpaca connect at import
from universe import ALL as UNIVERSE      # full tradable universe (74 symbols)

log = logging.getLogger("charts_server")

PORT                = int(os.environ.get("CHARTS_PORT", "5001"))
CHART_CACHE_TTL_SEC = 60
_VALID_INTERVALS    = frozenset({"1m", "5m", "15m", "30m", "1h", "1d"})
_VALID_RANGES       = frozenset({"1D", "5D", "1M", "3M", "1Y", "5Y"})
VALID_SYMBOLS       = frozenset(UNIVERSE)

app = Flask(
    __name__,
    template_folder=os.path.join(os.path.dirname(__file__), "..", "templates"),
    static_folder=os.path.join(os.path.dirname(__file__), "..", "static"),
)
socketio = SocketIO(app, async_mode="eventlet", cors_allowed_origins="*")

# ── bar / overlay cache (mirrors the main app, simplified, yfinance-only) ──────
_chart_cache: dict = {}
_overlay_cache: dict = {}
_cache_lock = threading.Lock()
_active_symbol = "SPY"


def _bars(interval: str, range_: str, symbol: str, force: bool = False) -> list:
    key = (symbol, interval, range_)
    now = time.monotonic()
    if not force:
        with _cache_lock:
            c = _chart_cache.get(key)
            if c and now - c[1] < CHART_CACHE_TTL_SEC:
                return c[0]
    bars = trader.fetch_chart_bars(interval, range_, symbol)
    with _cache_lock:
        _chart_cache[key] = (bars, now)
        _overlay_cache.pop(key, None)
    return bars


def _overlays(interval: str, range_: str, symbol: str, bars: list) -> dict:
    if not bars:
        return {}
    key = (symbol, interval, range_)
    now = time.monotonic()
    with _cache_lock:
        c = _overlay_cache.get(key)
        if c and now - c[1] < CHART_CACHE_TTL_SEC:
            return c[0]
    try:
        ov = trader.chart_overlays(bars, symbol)
    except Exception as e:                # prior-levels API needs login; degrade gracefully
        log.warning(f"overlays {symbol} {interval}/{range_}: {e}")
        ov = {}
    with _cache_lock:
        _overlay_cache[key] = (ov, now)
    return ov


def _min_state() -> dict:
    """Minimal state for the SPA. The client guards every field, and guest-charts
    mode (path == /charts) skips the login modal regardless of logged_in."""
    return {
        "logged_in":      False,
        "guest_charts":   True,
        "active_symbol":  _active_symbol,
        "symbols":        list(UNIVERSE),
        "paper_mode":     True,
    }


# ── routes ────────────────────────────────────────────────────────────────────
@app.route("/")
def _root():
    return redirect("/charts")           # so guest-charts mode (path==/charts) triggers


@app.route("/charts")
def _charts():
    return render_template("index.html")


@app.route("/health")
def _health():
    return {"status": "ok", "mode": "charts-only", "port": PORT,
            "symbols": len(UNIVERSE), "login_required": False}


# ── socket protocol (charts subset only) ──────────────────────────────────────
@socketio.on("connect")
def _on_connect():
    socketio.emit("state", _min_state())


@socketio.on("get_chart_data")
def _on_get_chart_data(data=None):
    data = data or {}
    interval = data.get("interval", "15m")
    range_   = data.get("range", "1D")
    if interval not in _VALID_INTERVALS:
        interval = "15m"
    if range_ not in _VALID_RANGES:
        range_ = "1D"
    symbol = (data.get("symbol") or _active_symbol).upper()
    if symbol not in VALID_SYMBOLS:
        symbol = "SPY"
    seq, pane = data.get("_seq"), data.get("pane_id")
    try:
        bars = _bars(interval, range_, symbol, bool(data.get("force_refresh")))
        ov   = _overlays(interval, range_, symbol, bars)
        socketio.emit("chart_data", {
            "bars": bars, "signals": [], "interval": interval, "range": range_,
            "symbol": symbol, "_seq": seq, "pane_id": pane,
            "overlays": ov, "position_overlay": [], "blocked_windows": [],
        })
    except Exception as e:
        log.warning(f"chart data {symbol}: {e}", exc_info=True)
        socketio.emit("chart_data", {
            "bars": [], "signals": [], "interval": interval, "range": range_,
            "symbol": symbol, "_seq": seq, "pane_id": pane,
        })


@socketio.on("set_active_symbol")
def _on_set_active_symbol(data=None):
    global _active_symbol
    sym = ((data or {}).get("symbol", "SPY")).upper()
    if sym in VALID_SYMBOLS:
        _active_symbol = sym
    socketio.emit("state", _min_state())


# Trading/account events the SPA may emit — accepted and ignored in charts-only mode.
def _noop(*_a, **_k):
    return None


for _ev in ("refresh", "start_stream", "stop_stream", "get_exec_brief",
            "get_screener", "sync_positions", "login", "logout",
            "set_dry_run", "toggle_auto_execute_options"):
    socketio.on_event(_ev, _noop)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log.info(f"charts-only server → http://localhost:{PORT}/charts  "
             f"({len(UNIVERSE)} symbols, no login, yfinance data)")
    socketio.run(app, host="127.0.0.1", port=PORT)
