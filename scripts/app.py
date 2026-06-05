"""
Auto Trader — Secure Web Dashboard
Security: security headers, rate limiting, login lockout,
          session authentication, input validation.
"""

# ── eventlet monkey-patch MUST run before any std-lib that uses sockets/threads.
# Falls back to threading mode silently if eventlet isn't available.
# Eventlet 0.41+ emits a deprecation warning that we acknowledge — for our
# single-user paper-trading workload it remains the right choice today.
# Long-term migration target: gevent (similar greenlet model, still active) or
# switching the stack to ASGI (FastAPI + python-socketio async).
import warnings
try:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # eventlet's EventletDeprecationWarning at import
        import eventlet
        eventlet.monkey_patch()
    _ASYNC_MODE = "eventlet"
except ImportError:
    _ASYNC_MODE = "threading"

import os
import logging
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional
from functools import wraps
from zoneinfo import ZoneInfo

from flask import Flask, render_template, request, jsonify, session, make_response
from flask_socketio import SocketIO, disconnect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv

import spy_auto_trader as trader
import news_filter
import daily_trader as dtrad
import screener_engine as screener
import screener_executor
import kb_principles
import debate as debate_mod
import auto_engine
from universe import ETFS_TRADE, ETFS_HEDGE
from universe import ALL as _UNIVERSE_ALL
from security import (
    get_or_create_secret_key,
    LoginTracker,
    validate_api_key,
    validate_api_secret,
    validate_risk_pct,
    validate_bool,
    validate_time,
    validate_vix_max,
    validate_stop_loss,
    validate_profit_target,
    validate_dte,
    SECURITY_HEADERS,
)

load_dotenv(override=True)
ET = ZoneInfo("America/New_York")

# ── Tunables (named constants over magic numbers) ─────────────────────────────
TICKER_INTERVAL_SEC      = 5         # price + state push cadence
ACCOUNT_REFRESH_TICKS    = 3         # refresh account/buying power every N ticks (~15s)
VIX_CACHE_TTL_SEC        = 120       # VIX rarely changes
PRIOR_LEVELS_CACHE_SEC   = 3600      # prior-day OHLC: refresh hourly
CHART_CACHE_TTL_SEC      = 60        # bar cache: 60s (a 15m chart doesn't change
                                     # in 8s; the active chart's auto-refresh keeps
                                     # it fresh anyway). With background pre-warm
                                     # this makes tab switches instant cache hits
                                     # instead of a cold 1-3s yfinance fetch.
APPROVAL_TIMEOUT_SEC     = 60
POSITION_MONITOR_SEC     = 10        # position monitor poll interval (10s for tighter stop execution)
LOGIN_RATE_LIMIT         = "10 per minute"
API_STATUS_RATE_LIMIT    = "30 per minute"
MAX_SIGNAL_HISTORY       = 50
_SYMBOLS_ORDERED         = _UNIVERSE_ALL          # all 40 (39 universe + IWM)
VALID_SYMBOLS            = frozenset(_SYMBOLS_ORDERED)
SESSION_AUTO_START       = (9, 30)   # ET hour, minute to auto-fire all-day sessions

# ── Concurrency ───────────────────────────────────────────────────────────────
# Single RLock guards `state`, `signal_history`, `authenticated_sids`,
# and ad-hoc caches. RLock so the same thread can re-enter (e.g. emit_state
# from inside a handler that already holds the lock).
_state_lock = threading.RLock()

# ── App setup ─────────────────────────────────────────────────────────────────
app = Flask(__name__,
            template_folder=os.path.join(os.path.dirname(__file__), '..', 'templates'),
            static_folder=os.path.join(os.path.dirname(__file__), '..', 'static'))
app.config.update(
    SEND_FILE_MAX_AGE_DEFAULT = 0,        # disable static file caching in dev
    SECRET_KEY              = get_or_create_secret_key(),
    SESSION_COOKIE_SECURE   = False,      # HTTP localhost
    SESSION_COOKIE_HTTPONLY = True,       # No JS access
    SESSION_COOKIE_SAMESITE = "Strict",   # CSRF mitigation
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8),
    SESSION_COOKIE_NAME     = "spy_session",
)

socketio = SocketIO(
    app,
    cors_allowed_origins=[],          # No cross-origin WebSocket
    async_mode=_ASYNC_MODE,           # eventlet preferred, threading fallback
    cookie="__Host-spy_io",
    manage_session=False,
    # Tolerate brief eventlet-hub stalls (network blips, slow yfinance) without
    # dropping the socket — a drop forces a reconnect that logs the browser out.
    ping_timeout=60,
    ping_interval=25,
)

# ── Rate limiter (login endpoint) ─────────────────────────────────────────────
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)

# ── Login lockout tracker ─────────────────────────────────────────────────────
login_tracker = LoginTracker()

# ── Authenticated WebSocket session IDs ───────────────────────────────────────
# More reliable than Flask sessions for WebSocket auth (sessions don't
# always persist across polling→websocket transport upgrades).
authenticated_sids = set()


# ── Signal tracker (for chart markers) ────────────────────────────────────────
signal_history = []   # list of {time, price, direction, reason} dicts

# Real 3yr Polygon backtest verdict per symbol (commit 3a0253d) + measured
# underlying directional hit-rate @30m (signal_diagnostic). The honest
# "why not to buy" that travels with every advisory marker.
_SYMBOL_VERDICT = {
    # sym:  (PF, exp%/trade, underlying-hit% @30m, tier)
    "SPY":  (1.18, +0.75, 59.7, "warn"),   # only positive, but 1/6 = likely fluke, <1.5 bar
    "NVDA": (0.74, -1.46, 57.8, "bad"),
    "MSFT": (0.71, -1.53, 55.6, "bad"),
    "AMZN": (0.66, -1.75, 60.1, "bad"),
    "GOOG": (0.65, -1.82, 56.3, "bad"),
    "META": (0.63, -1.94, 55.9, "bad"),
}

def _signal_verdict(symbol: str, direction: str) -> tuple[str, str]:
    """Returns (badge, tip) — compact on-chart tag + plain why-not-to-buy."""
    v = _SYMBOL_VERDICT.get(symbol.upper())
    side = "call" if direction == "bull" else "put"
    if not v:
        return ("⚠?", f"{symbol}: no real-data verdict — treat as unproven, do not auto-buy.")
    pf, exp, hit, tier = v
    if tier == "warn":
        badge = f"⚠ {symbol} PF{pf:.2f}"
        tip = (f"{symbol}: signal ~{hit:.0f}% directionally right @30min — the ONLY "
               f"symbol that backtested positive (PF {pf:.2f}) over 3yr, BUT that's "
               f"1-of-6 = likely a fluke, and still below the 1.5 go-live bar. "
               f"NOT cleared for real money. The {side} is a discretionary read, "
               f"not a system buy.")
    else:
        badge = f"❌ {symbol} PF{pf:.2f}"
        tip = (f"{symbol}: signal ~{hit:.0f}% directionally right @30min (real edge) "
               f"— BUT buying the {side} backtested a PROVEN LOSER: PF {pf:.2f}, "
               f"{exp:+.2f}%/trade over real 3yr. Do NOT buy the {side}; option "
               f"spread+theta eats the edge. If you act on the bull/bear read, "
               f"use SHARES, not options.")
    return (badge, tip)


def add_signal_marker(direction: str, price: float, reason: str, symbol: str = "SPY") -> None:
    """Record a signal for chart display (thread-safe). Tagged with symbol so
    the frontend only renders markers on the matching symbol's chart.
    Carries the real-data verdict (badge + plain why-not-to-buy tip) so the
    warning travels with every marker — meets the override impulse with
    evidence, every time."""
    _badge, _tip = _signal_verdict(symbol, direction)
    side = "CALL" if direction == "bull" else "PUT"
    log.info("SIGNAL %s %s @ $%.2f  trigger=%s  verdict=%s  |  %s",
             symbol.upper(), side, price, reason, _badge, _tip)
    marker = {
        "time":      int(datetime.now(ET).timestamp()),
        "price":     float(price),
        "direction": direction,
        "reason":    reason,
        "symbol":    symbol.upper(),
        "badge":     _badge,
        "tip":       _tip,
    }
    with _state_lock:
        signal_history.append(marker)
        if len(signal_history) > MAX_SIGNAL_HISTORY:
            signal_history.pop(0)
    # Emit outside the lock (Socket.IO emit is thread-safe and may block briefly)
    socketio.emit("chart_signal", marker)


# ── Trade approval ────────────────────────────────────────────────────────────
class TradeApproval:
    """Coordinates signal → UI alert → user response.
    Lock guards against late `respond()` from a previous trade overwriting
    the current trade's outcome.
    When auto_trade=True, approves immediately without waiting for the user."""

    def __init__(self) -> None:
        self._event      = threading.Event()
        self._approved   = False
        self._pending    = False
        self._lock       = threading.Lock()
        self.auto_trade  = False   # set by toggle_auto_trade handler

    def request(self, details: dict) -> bool:
        with self._lock:
            self._approved = False
            self._pending  = True
            self._event.clear()
            payload = dict(details)
            payload["timeout"]    = APPROVAL_TIMEOUT_SEC
            payload["auto_trade"] = self.auto_trade
            socketio.emit("trade_signal", payload)
            add_signal_marker(
                direction = details.get("direction", "bull"),
                price     = details.get("mid_price", 0),
                reason    = details.get("reason", ""),
                symbol    = details.get("symbol", "SPY"),
            )

        if self.auto_trade:
            with self._lock:
                self._pending = False
            log.info("Auto-trade: signal AUTO-APPROVED — placing order without user prompt.")
            return True

        if self._event.wait(timeout=APPROVAL_TIMEOUT_SEC):
            return self._approved
        with self._lock:
            self._pending = False
        log.warning(f"Trade approval timed out after {APPROVAL_TIMEOUT_SEC}s — auto-skipped.")
        return False

    def respond(self, approved: bool) -> None:
        """Late-arriving responses (after timeout) are ignored."""
        with self._lock:
            if not self._pending:
                log.warning("Late trade response ignored (no pending approval).")
                return
            self._approved = bool(approved)
            self._pending  = False
            self._event.set()

trade_approval = TradeApproval()
trader.TRADE_CONFIRM_CALLBACK = trade_approval.request


# ── Advisory signal markers (decision-support, NOT auto-trade) ────────────────
# Measured directional track-record per signal class, from the REAL 3yr
# signal_diagnostic.py run (underlying-direction, decoupled from option P&L).
# This is what makes a marker *informative*: the chart shows not just "signal
# here" but "this setup is historically right X% over the next hour".
_SIGNAL_TRACK_RECORD = {
    "vwap_momentum": "✅ edge: 58% right @30m, 60% @60m, +0.34→0.62 ATR (real 3yr, all 6 symbols)",
    "orb_breakout":  "⚠ unproven on real data",
    "gap_fade":      "⛔ NOISE — ~48% (disabled)",
    "trend_cont":    "⛔ the bleed — PF 0.49 (disabled)",
    "mean_rev":      "⛔ negative, tiny sample (disabled)",
}

def _advisory_signal(symbol: str, direction: str, reason: str,
                     price: float, signal_class: str) -> None:
    """Fired the instant a signal is detected (pre-gate). Plots a call/put
    marker on the symbol's chart for the user to decide on. NOT an order.

    Honest framing baked into the tooltip: the measured track record + the
    standing reality that monetizing this via retail options is unproven."""
    tr = _SIGNAL_TRACK_RECORD.get(signal_class, "track record unknown")
    side = "CALL" if direction == "bull" else "PUT"
    enriched = (f"[ADVISORY · {signal_class} → {side}] {reason}  "
                f"│ {tr}  │ directional aid only — option monetization unproven, "
                f"you decide instrument/size/skip")
    add_signal_marker(direction=direction, price=price,
                      reason=enriched, symbol=symbol)

trader.ADVISORY_SIGNAL_CALLBACK = _advisory_signal

# ── Logging ───────────────────────────────────────────────────────────────────
# Root logging is already configured by spy_auto_trader.py at import time
# (rotating spy_trader.log + errors.log with dedup + stream). Don't reconfigure
# here — just grab the logger.
from logging.handlers import RotatingFileHandler

log = logging.getLogger(__name__)

security_log = logging.getLogger("security")
sec_handler  = RotatingFileHandler("security.log", maxBytes=5_000_000, backupCount=3)
sec_handler.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s"))
security_log.addHandler(sec_handler)
security_log.setLevel(logging.INFO)
security_log.propagate = False  # security events don't need to go to main log

# ── Dedicated LOGIN log ──────────────────────────────────────────────────────
# A focused, isolated trail of the full login lifecycle (browser + silent re-auth)
# so login problems can be diagnosed at a glance: `tail -f logs/login.log`.
# Own handler + propagate=False so it survives root-handler reconfiguration and
# stays uncluttered by the rest of the app's logging.
login_log = logging.getLogger("login")
try:
    _login_log_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs", "login.log")
    os.makedirs(os.path.dirname(_login_log_path), exist_ok=True)
    _login_handler = RotatingFileHandler(_login_log_path, maxBytes=2_000_000, backupCount=3)
    _login_handler.setFormatter(logging.Formatter(
        "%(asctime)s  %(levelname)-7s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    login_log.addHandler(_login_handler)
    login_log.setLevel(logging.INFO)
    login_log.propagate = False
except Exception as _e:
    log.warning(f"could not set up login log: {_e}")


# ── Custom SocketIO log handler ───────────────────────────────────────────────
class SocketIOHandler(logging.Handler):
    def emit(self, record):
        # Skip log streaming when paused
        if not state.get("streaming", True):
            return
        try:
            msg = self.format(record)
            socketio.emit("log", {"message": msg, "level": record.levelname})
        except Exception:
            pass

sio_handler = SocketIOHandler()
sio_handler.setFormatter(logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S"))
logging.getLogger().addHandler(sio_handler)


# ── File logging (defensive) ─────────────────────────────────────────────────
# The comment above claims spy_auto_trader.py installs file handlers at import
# time. Field check 2026-05-29: those files are 0 bytes / stale. Errors from
# screener_executor (incl. failed order placements) were vanishing because the
# only sink was the browser SocketIOHandler.
#
# Add a defensive RotatingFileHandler so every log record lands on disk
# regardless of whether spy_auto_trader's setup ran.
_repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_main_log_path  = os.path.join(_repo_root, "spy_trader.log")
_error_log_path = os.path.join(_repo_root, "errors.log")

_file_fmt = logging.Formatter(
    "%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

_main_handler = RotatingFileHandler(_main_log_path, maxBytes=10_000_000, backupCount=5)
_main_handler.setFormatter(_file_fmt)
_main_handler.setLevel(logging.INFO)

_err_handler = RotatingFileHandler(_error_log_path, maxBytes=5_000_000, backupCount=3)
_err_handler.setFormatter(_file_fmt)
_err_handler.setLevel(logging.WARNING)   # warnings + errors only

_root_log = logging.getLogger()
_root_log.setLevel(logging.INFO)
# Mark our handlers so we can detect double-imports without falsely matching
# whatever stale/broken handler spy_auto_trader installed.
_main_handler._is_app_main_file_handler = True   # type: ignore[attr-defined]
_err_handler._is_app_error_file_handler = True   # type: ignore[attr-defined]
_already_added_main = any(getattr(h, "_is_app_main_file_handler", False)
                          for h in _root_log.handlers)
_already_added_err  = any(getattr(h, "_is_app_error_file_handler", False)
                          for h in _root_log.handlers)
if not _already_added_main:
    _root_log.addHandler(_main_handler)
if not _already_added_err:
    _root_log.addHandler(_err_handler)


# ── Security headers ──────────────────────────────────────────────────────────
@app.after_request
def add_security_headers(response):
    for header, value in SECURITY_HEADERS.items():
        response.headers[header] = value
    # Remove fingerprinting headers
    response.headers.pop("Server", None)
    response.headers.pop("X-Powered-By", None)
    return response


# ── State ─────────────────────────────────────────────────────────────────────
state = {
    "logged_in":       False,
    # Per-symbol running state (tabs are chart-only; any symbol can trade anytime)
    "sessions":        {s: False for s in _SYMBOLS_ORDERED},
    "streaming":       True,         # Live price + log streaming
    "dry_run":         False,  # DEFAULT OFF (operator directive 2026-06-03): TRADE by
                               # default — the screener auto-exec, stock auto-buy, and
                               # manual clicks place REAL PAPER orders. Can ONLY ever be
                               # paper (PAPER_MODE + non-paper hard guards + go-live gate).
                               # Flip to simulation anytime via the UI Dry Run toggle.
    "paper_mode":      True,         # Alpaca paper vs live
    "active_symbol":   "SPY",        # currently selected chart tab
    "session_end":     "15:45",      # all-day session end time (HH:MM ET)
    "account_value":   0.0,
    "buying_power":    0.0,
    "trades_today":    [],
    "spy_price":       None,
    "spy_change_pct":  None,
    "market_session":  "closed",
    "vix":             None,
    # Trade-rule parameters (mirror trader module constants)
    "vix_max":         30,
    "stop_loss":       50,    # % of premium paid
    "profit_target":   75,    # % of premium paid
    "dte_min":         7,
    "dte_max":         14,
    "auto_schedule":        False,  # auto-start ORB/VWAP sessions for ALL 25 symbols at 9:30 ET — heavy; default off because the strategy has no validated edge per README
    "news_filter_enabled":  True,   # veto session if bad headlines detected
    "trade_memory_enabled": True,   # ChromaDB similarity recall before signals
    "debate_enabled":       True,   # Bull/Bear LLM debate gate (needs ANTHROPIC_API_KEY)
    "auto_trade":           True,   # skip approval modal — auto-execute on paper account
    "auto_execute_options": True,   # DEFAULT ARMED (operator directive 2026-05-31).
                                    # Now places REAL PAPER orders (dry_run OFF). Safety
                                    # rests on: paper-only hard guards + KB-match & debate
                                    # gates + KB §9 liquidity + MAX_AUTO_EXEC_PER_DAY cap.
}

# ── Auto-execute options dedup (prevents re-firing same symbol same day) ─────
# Persisted to disk so a server restart mid-day cannot re-execute symbols
# that already fired. File format: {"date":"YYYY-MM-DD","executed":["SYM",...]}
import json as _json_dedup
_AUTO_EXEC_STATE_FILE = os.path.join(
    os.path.dirname(__file__), "..", "data", "auto_exec_state.json"
)
_auto_exec_lock = threading.Lock()   # guards file + in-memory set
_auto_exec_today:  set = set()   # dedup — symbols ATTEMPTED today (prevents re-attempt)
_auto_exec_filled: set = set()   # symbols that actually FILLED today — the N/3 cap counter
_auto_exec_date:   str = ""
# Stock auto-exec lane (mirrors the options lane) — its own dedup/fill/cap so
# stocks and options don't share the daily budget. Gated by the same Armed toggle.
_auto_exec_stock_today:  set = set()
_auto_exec_stock_filled: set = set()
STOCK_MAX_AUTO_EXEC_PER_DAY = 3
# AH-2/CR-6: equal-dollar stock sizing target lives in config.py (single source).
from config import STOCK_TARGET_USD, size_position as _size_position


def _stock_qty_for(price) -> int:
    """Shares to deploy ~STOCK_TARGET_USD at `price` (min 1). 0 if price unusable.
    Delegates to the shared config.size_position so every path sizes identically (CR-6)."""
    return _size_position("stocks", price)
# Per-symbol daily attempt cap (#36): a symbol that fails to fill (e.g. COHR
# tripping the $600 hard ceiling, an illiquid name, a rejected order) is retried
# at most this many times per day, then skipped — stops the retry storm where
# the same name was re-fetched + re-failed 20-30× a session, hammering yfinance
# and the eventlet hub for nothing. Keyed sym → attempts; persisted with state.
_auto_exec_attempts: dict = {}
MAX_SYMBOL_ATTEMPTS_PER_DAY = 2

# ── Daily P&L circuit breaker ────────────────────────────────────────────────
# Snapshot equity at start-of-day; halt auto-execute if drawdown exceeds limit.
DAILY_LOSS_LIMIT_PCT = 2.0   # halt auto-exec if today's equity drops > 2%
LOSS_BREACH_CONFIRM  = 2     # consecutive breaching reads required to halt (debounce)
_session_start_equity: float = 0.0
_session_start_date:   str   = ""
_loss_breach_count:    int   = 0     # consecutive readings under the loss limit


def _load_auto_exec_state() -> None:
    """Restore today's dedup set from disk on startup. Discards yesterday's data."""
    global _auto_exec_today, _auto_exec_filled, _auto_exec_date
    global _auto_exec_stock_today, _auto_exec_stock_filled, _auto_exec_attempts
    today = datetime.now(ET).strftime("%Y-%m-%d")
    try:
        with open(_AUTO_EXEC_STATE_FILE) as fh:
            data = _json_dedup.load(fh)
        if data.get("date") == today:
            _auto_exec_today  = set(data.get("executed", []))
            _auto_exec_filled = set(data.get("filled", []))
            _auto_exec_stock_today  = set(data.get("stock_executed", []))
            _auto_exec_stock_filled = set(data.get("stock_filled", []))
            _auto_exec_attempts = dict(data.get("attempts", {}))
            _auto_exec_date   = today
            if _auto_exec_today:
                log.info(f"[auto-exec] Restored {today}: attempted="
                         f"{sorted(_auto_exec_today)} filled={sorted(_auto_exec_filled)}")
    except (FileNotFoundError, _json_dedup.JSONDecodeError, OSError):
        pass


def _save_auto_exec_state() -> None:
    """Write the current dedup set to disk. Atomic via temp-file rename."""
    os.makedirs(os.path.dirname(_AUTO_EXEC_STATE_FILE), exist_ok=True)
    tmp = _AUTO_EXEC_STATE_FILE + ".tmp"
    try:
        with open(tmp, "w") as fh:
            _json_dedup.dump(
                {"date": _auto_exec_date, "executed": sorted(_auto_exec_today),
                 "filled": sorted(_auto_exec_filled),
                 "stock_executed": sorted(_auto_exec_stock_today),
                 "stock_filled": sorted(_auto_exec_stock_filled),
                 "attempts": _auto_exec_attempts},
                fh,
            )
        os.replace(tmp, _AUTO_EXEC_STATE_FILE)
    except OSError as e:
        log.warning(f"[auto-exec] Could not persist dedup state: {e}")


# ── trades_today persistence (#17) ────────────────────────────────────────────
# Survives server restart so the UI shows continuity and the 15:35 ET EOD
# review sees the full day's closes even if the process was bounced.
_TRADES_TODAY_FILE = os.path.join(
    os.path.dirname(__file__), "..", "data", "trades_today.json"
)


def _load_trades_today() -> None:
    """Restore today's closed trades from disk on startup. Discards stale
    (yesterday's) files so the UI never shows trades from a previous session."""
    today = datetime.now(ET).strftime("%Y-%m-%d")
    try:
        with open(_TRADES_TODAY_FILE) as fh:
            data = _json_dedup.load(fh)
        if data.get("date") == today:
            trades = list(data.get("trades", []))
            with _state_lock:
                state["trades_today"] = trades
            if trades:
                log.info(f"[trades] Restored {len(trades)} closed trades for {today}")
    except (FileNotFoundError, _json_dedup.JSONDecodeError, OSError):
        pass


def _save_trades_today() -> None:
    """Persist trades_today atomically. Called after every position close."""
    today = datetime.now(ET).strftime("%Y-%m-%d")
    with _state_lock:
        trades = list(state["trades_today"])
    os.makedirs(os.path.dirname(_TRADES_TODAY_FILE), exist_ok=True)
    tmp = _TRADES_TODAY_FILE + ".tmp"
    try:
        with open(tmp, "w") as fh:
            # default=str so any datetime/Decimal in the trade dict serialises
            _json_dedup.dump({"date": today, "trades": trades}, fh, default=str)
        os.replace(tmp, _TRADES_TODAY_FILE)
    except OSError as e:
        log.warning(f"[trades] Could not persist trades_today: {e}")

# Per-symbol session threads and stop events
_session_threads:     dict[str, threading.Thread] = {}
_session_stop_events: dict[str, threading.Event]  = {
    sym: threading.Event() for sym in _SYMBOLS_ORDERED
}

# ── Sleep prevention (macOS caffeinate) ──────────────────────────────────────
_caffeinate_proc: Optional[subprocess.Popen] = None
_caffeinate_lock = threading.Lock()


def _ensure_awake() -> None:
    """Start caffeinate so the Mac won't sleep during an active session."""
    global _caffeinate_proc
    with _caffeinate_lock:
        if _caffeinate_proc and _caffeinate_proc.poll() is None:
            return
        try:
            _caffeinate_proc = subprocess.Popen(["caffeinate", "-i"])
            log.info("Sleep prevention ON (caffeinate -i started)")
        except FileNotFoundError:
            log.warning("caffeinate not found — system may sleep during session")


def _release_awake() -> None:
    """Stop caffeinate once no sessions are running."""
    global _caffeinate_proc
    with _state_lock:
        still_active = any(state["sessions"].values())
    if still_active:
        return
    with _caffeinate_lock:
        if _caffeinate_proc and _caffeinate_proc.poll() is None:
            _caffeinate_proc.terminate()
            _caffeinate_proc = None
            log.info("Sleep prevention OFF (caffeinate stopped)")


# ── Auth helpers ──────────────────────────────────────────────────────────────
def authenticated():
    """Check if the current WebSocket connection is authenticated."""
    try:
        return request.sid in authenticated_sids
    except Exception:
        return False

def require_auth(fn):
    """Decorator: ask client to re-authenticate, then disconnect."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not authenticated():
            security_log.warning(f"Unauthenticated socket event from {request.remote_addr}")
            socketio.emit("login_required", to=request.sid)
            disconnect()
            return None
        return fn(*args, **kwargs)
    return wrapper


# ── Helpers ───────────────────────────────────────────────────────────────────
_acct_pos_cache = {"equity": [], "options": [], "ts": 0.0}
_ACCT_POS_TTL   = 8.0   # cache Alpaca positions ~8s (state snapshot runs often)


_opt_peak: dict = {}   # per-underlying option {peak P&L, ts} for the stall time-stop
_opt_exit_state: dict = {}              # per-underlying ExitState for the REQ-608 dynamic option stop ladder
_OPT_EXIT_ENGINE = auto_engine.ExitEngine()   # breakeven+trail ladder (pure logic; never places orders)
_exit_mgmt_state = {"last": 0.0}   # throttle the heavy exit-management block (~30s)


def _read_jsonl_today(path: str, today: str) -> list:
    out = []
    try:
        import json as _j
        with open(os.path.expanduser(path)) as fh:
            for ln in fh:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    o = _j.loads(ln)
                except Exception:
                    continue
                if str(o.get("ts", ""))[:10] == today:
                    out.append(o)
    except FileNotFoundError:
        pass
    return out


def _run_eod_analysis(emit: bool = True) -> dict:
    """EOD analysis + learning: compile today's closes, missed buys, relaxations and
    P&L, then ask Claude for insights + recommendations (REQ-610 self-learn). Saves a
    report to ~/.spy_trader/eod_<date>.json and emits it to the UI."""
    import datetime as _dt, json as _j
    today = _dt.date.today().isoformat()
    closed   = _read_jsonl_today(auto_engine._JOURNAL_FILE, today)
    relaxed  = _read_jsonl_today("~/.spy_trader/kb_relaxed.jsonl", today)
    screened = _read_jsonl_today(f"~/.spy_trader/screened_{today}.jsonl", today)
    eq, op = _account_equity_positions(), _account_option_positions()
    held_syms   = {p["sym"] for p in eq} | {o["sym"] for o in op}
    closed_syms = {c.get("sym") for c in closed}
    # "missed" = screened-as-BUY, never entered (not held, not closed today)
    missed = sorted({s.get("sym") for s in screened
                     if s.get("sym") not in held_syms and s.get("sym") not in closed_syms})
    wins   = [c for c in closed if (c.get("pnl_pct") or 0) > 0]
    losses = [c for c in closed if (c.get("pnl_pct") or 0) < 0]
    realized = sum(float(c.get("pnl_usd") or 0) for c in closed)
    unreal   = sum(float(p.get("pnl_usd") or 0) for p in eq) + sum(float(o.get("pnl_usd") or 0) for o in op)
    # exit-reason breakdown
    reasons: dict = {}
    for c in closed:
        r = (c.get("reason") or "?").split(" ")[0]
        reasons[r] = reasons.get(r, 0) + 1
    stats = {
        "date": today, "closed": len(closed), "wins": len(wins), "losses": len(losses),
        "win_rate": round(len(wins) / len(closed) * 100, 1) if closed else 0,
        "realized_pnl": round(realized, 2), "unrealized_pnl": round(unreal, 2),
        "open": len(eq) + len(op), "screened_buy": len(screened),
        "missed_count": len(missed), "missed_names": missed[:25],
        "relaxations": len(relaxed),
        "exit_reasons": reasons,
    }
    narrative = _eod_llm(stats, closed, relaxed)
    report = {"ts": _dt.datetime.now().isoformat(), "stats": stats, "narrative": narrative}
    try:
        with open(os.path.expanduser(f"~/.spy_trader/eod_{today}.json"), "w") as fh:
            _j.dump(report, fh, indent=2)
    except Exception as e:
        log.warning(f"save eod report: {e}")
    if emit:
        socketio.emit("eod_report", report)   # carries ts for the card's "last run" stamp
        # Full report → the Log. Build ALL lines, then emit with a yield between each so every
        # line flushes to the socket. (Bug 2026-06-05: ~18 rapid emits with no yield → under
        # eventlet hub contention only the header reached the browser.)
        _lines = [f"━━━━━ EOD ANALYSIS {today} ━━━━━",
                  f"  Closed {len(closed)} ({len(wins)}W/{len(losses)}L · {stats['win_rate']}%) · "
                  f"realized ${realized:+.0f} · open {stats['open']} (${unreal:+.0f} unreal)"]
        if reasons:
            _lines.append("  Exits: " + " · ".join(f"{k} {v}" for k, v in reasons.items()))
        if missed:
            _lines.append(f"  Missed BUYs ({len(missed)}): " + ", ".join(missed[:15])
                          + ("…" if len(missed) > 15 else ""))
        if relaxed:
            _lines.append(f"  KB relaxations: {len(relaxed)} (paper-only fills)")
        _lines += ["  " + l.strip() for l in (narrative or "").splitlines() if l.strip()]
        _lines.append("━━━━━ end EOD analysis ━━━━━")
        for _ln in _lines:
            _emit_log(_ln, level="INFO")
            socketio.sleep(0)     # yield → let the hub flush this line before the next
    return report


def _eod_llm(stats: dict, closed: list, relaxed: list) -> str:
    """Ask Claude for an EOD review + 2-3 concrete recommendations. Deterministic
    fallback if no API key."""
    plain = (f"Date {stats['date']} · closed {stats['closed']} "
             f"({stats['wins']}W/{stats['losses']}L, win-rate {stats['win_rate']}%) · "
             f"realized ${stats['realized_pnl']:+.0f} · unrealized ${stats['unrealized_pnl']:+.0f} · "
             f"open {stats['open']} · screened-BUY {stats['screened_buy']} · "
             f"missed {stats['missed_count']} ({', '.join(stats['missed_names'][:12])}) · "
             f"KB-relaxed {stats['relaxations']} · exit-reasons {stats['exit_reasons']}")
    try:
        if os.environ.get("ANTHROPIC_API_KEY", "").strip():
            import debate as _d
            client = _d.get_anthropic_client()
            if client is not None:
                resp = client.messages.create(
                    model="claude-haiku-4-5-20251001", max_tokens=320,
                    messages=[{"role": "user", "content":
                        "You are the EOD coach for an automated PAPER trading system "
                        "(stocks/ETFs ±2% exits, options ±20%, KB-gated, some gates relaxed "
                        "to fill). Review today's data and give: (1) a 2-sentence summary, "
                        "(2) 2-3 SPECIFIC, actionable recommendations to improve tomorrow "
                        "(e.g. tighten/loosen a threshold, stop relaxing a gate, missed names "
                        "worth pre-staging). Be concrete and brief.\n\n" + plain}],
                )
                return resp.content[0].text.strip()
    except Exception as e:
        log.warning(f"eod llm: {e}")
    # fallback
    rec = []
    if stats["relaxations"] > 3:
        rec.append(f"Relaxed KB gates {stats['relaxations']}× — review whether those fills helped.")
    if stats["missed_count"] > 0:
        rec.append(f"{stats['missed_count']} buyable names not taken: {', '.join(stats['missed_names'][:8])}.")
    if stats["losses"] > stats["wins"]:
        rec.append("More losses than wins — consider tightening entries or the stop.")
    return (f"Closed {stats['closed']} ({stats['wins']}W/{stats['losses']}L), realized "
            f"${stats['realized_pnl']:+.0f}, {stats['open']} still open (${stats['unrealized_pnl']:+.0f}). "
            + " ".join(rec or ["Steady day."]))


def _journal_recent(n: int = 25) -> list:
    """Last n closed-trade events from the shared journal (#34)."""
    try:
        import json as _j
        with open(auto_engine._JOURNAL_FILE) as fh:
            lines = fh.readlines()[-n:]
        out = []
        for ln in lines:
            try:
                out.append(_j.loads(ln))
            except Exception:
                continue
        return list(reversed(out))   # newest first
    except Exception:
        return []


def _manage_option_positions() -> None:
    """±20% exit on option positions (operator 2026-06-02): close an underlying's
    option legs when the net position is +20% (take profit) or −20% (stop) on the
    net debit. Groups legs by underlying so spreads exit as a unit."""
    import re
    c = getattr(trader, "TRADING_CLIENT", None)
    if c is None:
        return
    try:
        opts = [p for p in c.get_all_positions()
                if getattr(getattr(p, "asset_class", None), "value", "") == "us_option"]
    except Exception as e:
        log.debug(f"option-exit fetch: {e}")
        return
    groups: dict[str, list] = {}
    for p in opts:
        m = re.match(r"^([A-Z]+)\d", p.symbol)
        groups.setdefault(m.group(1) if m else p.symbol, []).append(p)
    tp, sl = screener_executor.OPT_TAKE_PROFIT_PCT, screener_executor.OPT_STOP_LOSS_PCT
    import datetime as _dt
    now = _dt.datetime.now()
    for u, legs in groups.items():
        try:
            net_pl   = sum(float(l.unrealized_pl) for l in legs)
            net_cost = abs(sum(float(l.cost_basis) for l in legs))   # net debit paid
            if net_cost <= 0:
                continue
            pct = net_pl / net_cost
            # stall tracking (#33): peak gain + when it was last set, per underlying
            pk = _opt_peak.get(u)
            if pk is None or pct > pk["peak"]:
                _opt_peak[u] = {"peak": pct, "ts": now}
            stall_min = (now - _opt_peak.get(u, {"ts": now})["ts"]).total_seconds() / 60
            stalled = (pct >= auto_engine.STALL_MIN_PROFIT_PCT
                       and stall_min >= screener_executor.OPT_STALL_MINUTES)
            reason = None
            if pct >= tp:
                reason = f"take-profit +{tp*100:.0f}%"
            elif screener_executor.OPT_DYNAMIC_EXIT_ENABLED:
                # REQ-608: dynamic breakeven+trail ladder on the stop side. The init
                # stop is -OPT_STOP_LOSS_PCT (same -50% floor as before); it then
                # ratchets UP as the net debit gains, so a winner can't give it all
                # back to the flat stop (KB §XM-4). Stall still applies as a fallback.
                val = net_cost + net_pl                       # current value of the net debit
                st  = _opt_exit_state.get(u) or _OPT_EXIT_ENGINE.init_position(
                    net_cost, init_stop=net_cost * (1 - sl))
                act, why, st = _OPT_EXIT_ENGINE.update(st, val, val, val)
                _opt_exit_state[u] = st
                if act == "exit":
                    reason = f"dynamic stop: {why}"
                elif stalled:
                    reason = f"time-stop {int(stall_min)}min stalled +{pct*100:.1f}%"
            elif pct <= -sl:
                reason = f"stop -{sl*100:.0f}%"
            elif stalled:
                reason = f"time-stop {int(stall_min)}min stalled +{pct*100:.1f}%"
            if reason:
                for l in legs:
                    try:
                        c.close_position(l.symbol)
                    except Exception as e:
                        log.warning(f"  option close {l.symbol}: {e}")
                auto_engine._journal_add(u, "option", reason, pct * 100, net_pl)
                _opt_peak.pop(u, None)
                _opt_exit_state.pop(u, None)
                _emit_log(f"OPTION EXIT {u}: {reason} (net {pct*100:+.0f}% on ${net_cost:.0f})",
                          level="INFO")
        except Exception as e:
            log.debug(f"option-exit {u}: {e}")


def _protect_untracked_stocks() -> None:
    """Any account equity position not yet in the engine's managed store gets brought
    under dynamic exit management — so stock auto-buys + manual buys get a trailing
    stop / profit floor / time cap, not just the engine's own ETF entries."""
    try:
        acct = _account_equity_positions()
        if not acct:
            return
        tracked = {p.get("sym") for p in auto_engine._load_positions()}
        for p in acct:
            if p["sym"] not in tracked:
                auto_engine.record_stock_position(
                    p["sym"], p["qty"], p["entry"], strategy="screener/manual")
    except Exception as e:
        log.debug(f"protect untracked stocks: {e}")


def _refresh_account_positions() -> None:
    """Fetch all Alpaca positions once, split into equity + options, cache ~8s — the
    source of truth for the Positions tab + P&L (engine ETFs, stock auto-buys, manual,
    and option positions)."""
    now = time.monotonic()
    if now - _acct_pos_cache["ts"] < _ACCT_POS_TTL:
        return
    c = getattr(trader, "TRADING_CLIENT", None)
    if c is None:
        return
    import re as _re
    eq, op = [], []
    try:
        for p in c.get_all_positions():
            ac = getattr(getattr(p, "asset_class", None), "value", "")
            try:
                base = {
                    "qty": int(float(p.qty)),
                    "entry": float(p.avg_entry_price), "last": float(p.current_price),
                    "mkt_value": float(p.market_value),
                    "pnl_usd": float(p.unrealized_pl),
                    "pnl_pct": float(p.unrealized_plpc) * 100,
                    "day_pnl_usd": float(getattr(p, "unrealized_intraday_pl", 0) or 0),
                    "day_pnl_pct": float(getattr(p, "unrealized_intraday_plpc", 0) or 0) * 100,
                }
            except Exception:
                continue
            if ac == "us_equity":
                eq.append({"sym": p.symbol, **base})
            elif ac == "us_option":
                m = _re.match(r"^([A-Z]+)\d", p.symbol)
                op.append({"occ": p.symbol, "sym": (m.group(1) if m else p.symbol), **base})
    except Exception as e:
        log.debug(f"account positions fetch: {e}")
        return   # keep last good on a transient error
    _acct_pos_cache.update(equity=eq, options=op, ts=now)


def _account_equity_positions() -> list:
    _refresh_account_positions()
    return _acct_pos_cache.get("equity", [])


def _account_option_positions() -> list:
    _refresh_account_positions()
    return _acct_pos_cache.get("options", [])


def _state_snapshot() -> dict:
    """Single source of truth for the state payload sent to the UI.

    The lock guards only the in-memory `state` dict reads. Trader function
    calls that may do I/O (open_positions_snapshot, equity_curve_snapshot, etc.)
    run OUTSIDE the lock to avoid blocking other threads that need to update
    state (e.g. price_ticker, position_monitor)."""
    with _state_lock:
        acct_val = state["account_value"]
        snap = {
            "logged_in":       state["logged_in"],
            "sessions":        dict(state["sessions"]),
            "streaming":       state["streaming"],
            "dry_run":         state["dry_run"],
            "paper_mode":      state["paper_mode"],
            "risk_mode":       getattr(trader, "RISK_MODE", "paper_aggressive"),
            "active_symbol":   state["active_symbol"],
            "session_end":     state["session_end"],
            "account_value":   acct_val,
            "buying_power":    state["buying_power"],
            "spy_price":       state["spy_price"],
            "spy_change_pct":  state["spy_change_pct"],
            "market_session":  state["market_session"],
            "vix":             state["vix"],
            "trades_today":    list(state["trades_today"]),
            "vix_max":         state["vix_max"],
            "stop_loss":       state["stop_loss"],
            "profit_target":   state["profit_target"],
            "dte_min":         state["dte_min"],
            "dte_max":         state["dte_max"],
            "auto_schedule":        state["auto_schedule"],
            "news_filter_enabled":  state["news_filter_enabled"],
            "trade_memory_enabled": state["trade_memory_enabled"],
            "debate_enabled":       state["debate_enabled"],
            "auto_trade":           state["auto_trade"],
            "auto_execute_options": state["auto_execute_options"],
            "auto_exec_today":      list(_auto_exec_filled),   # the N/3 cap counts FILLED trades
            "timestamp":            datetime.now(ET).strftime("%H:%M:%S ET"),
        }
    # Trader calls outside the lock — these may do file I/O or iterate lists
    # under their own internal locks. Holding _state_lock here would create
    # unnecessary contention with price_ticker and position_monitor threads.
    snap["open_positions"]         = trader.open_positions_snapshot()
    try:
        snap["auto_positions"]     = auto_engine.positions_snapshot()
    except Exception:
        snap["auto_positions"]     = []
    # ALL Alpaca positions (truth) so the Positions tab shows everything — engine
    # ETFs + stock auto-buys + manual buys + OPTION positions — not just the stores.
    snap["account_positions"]      = _account_equity_positions()
    snap["account_options"]        = _account_option_positions()
    # Closed trades are surfaced in the Log (auto-engine "CLOSED" / "OPTION EXIT"
    # lines), so the separate Notes panel was retired (operator 2026-06-04). The
    # journal.jsonl store stays — EOD summary, trades-today count and restore use it.
    snap["exit_config"] = {                                  # operator-editable exits
        "stock_tp_pct":  round(auto_engine.STOCK_TAKE_PROFIT_PCT * 100, 2),
        "stock_sl_pct":  round(auto_engine.STOCK_STOP_PCT * 100, 2),
        "opt_tp_pct":    round(screener_executor.OPT_TAKE_PROFIT_PCT * 100, 2),
        "opt_sl_pct":    round(screener_executor.OPT_STOP_LOSS_PCT * 100, 2),
        "stock_stall_days": round(auto_engine.STALL_MINUTES / 1440, 1),   # stocks: days
        "opt_stall_min":    screener_executor.OPT_STALL_MINUTES,          # options: minutes
        "opt_dynamic_exit": screener_executor.OPT_DYNAMIC_EXIT_ENABLED,   # REQ-608 breakeven+trail ladder
        "time_cap_days": auto_engine.TIME_CAP_DAYS,
    }
    snap["deployed_risk_pct"]      = round(trader.deployed_risk_pct(acct_val) * 100, 2)
    snap["max_portfolio_risk_pct"] = round(trader.eff_max_portfolio_risk() * 100, 2)
    snap["pdt_remaining"]          = trader.pdt_day_trades_remaining()
    snap["equity_curve"]           = trader.equity_curve_snapshot(acct_val)
    snap["slippage"]               = trader.slippage_snapshot()
    snap["data_freshness"]         = trader.get_freshness_snapshot()
    # Daily Connors positions + incubation stats (PA-UI)
    try:
        all_pos = dtrad._load_positions()
        snap["daily_positions"] = [
            p for p in all_pos
            if p.get("status") in ("open", "pending", "signal")
        ]
        closed_pos = [p for p in all_pos if p.get("status") == "closed"]
        from datetime import date as _date
        incub_start = _date(2026, 5, 20)
        incub_days  = (_date.today() - incub_start).days
        wins  = sum(1 for p in closed_pos if (p.get("pnl_usd") or 0) > 0)
        losses = sum(1 for p in closed_pos if (p.get("pnl_usd") or 0) < 0)
        snap["incubation"] = {
            "start_date":   str(incub_start),
            "days_running": incub_days,
            "trade_count":  len(closed_pos),
            "wins":         wins,
            "losses":       losses,
            "target_days":  28,
        }
    except Exception:
        snap["daily_positions"] = []
        snap["incubation"] = {}
    return snap


def emit_state() -> None:
    socketio.emit("state", _state_snapshot())


def emit_state_to(sid: str) -> None:
    """Send state to a single client (e.g. on connect)."""
    socketio.emit("state", _state_snapshot(), to=sid)


def refresh_account() -> None:
    try:
        with _state_lock:
            state["account_value"] = round(trader.account_value(), 2)
            state["buying_power"]  = round(trader.buying_power(),  2)
    except Exception as e:
        log.warning(f"refresh_account failed: {e}")


def _on_trader_fill() -> None:
    """Trader-side hook: refresh account stats and broadcast updated state.

    Wired into trader.ON_FILL_CALLBACK below — the trader calls this from session
    threads after a successful entry fill or a successful position close, so the
    header (Account / Buying Power / Max Risk) ticks in real time instead of only
    on session start/end.
    """
    refresh_account()
    emit_state()


# Register the callback once (at import time — session threads pick it up).
trader.ON_FILL_CALLBACK = _on_trader_fill


# ── Cached lookups ────────────────────────────────────────────────────────────
_vix_cache:    dict = {"value": None, "ts": 0.0}
# Per-symbol prior-levels cache: symbol -> {"value": dict, "ts": monotonic}
_levels_cache: dict[str, dict] = {}
_levels_lock = threading.Lock()


def _cached_vix() -> Optional[float]:
    """Return VIX with TTL-based caching to avoid hammering the API."""
    now = time.monotonic()
    if now - _vix_cache["ts"] < VIX_CACHE_TTL_SEC:
        return _vix_cache["value"]
    try:
        v = trader.fetch_vix()
        _vix_cache["value"] = v
        _vix_cache["ts"]    = now
        return v
    except Exception as e:
        log.warning(f"VIX fetch failed: {e}")
        return _vix_cache["value"]


def _cached_prior_levels(symbol: str = "SPY") -> dict:
    """Prior-day OHLC + pivots for `symbol` — cached for 1h."""
    symbol = symbol.upper()
    now = time.monotonic()
    with _levels_lock:
        entry = _levels_cache.get(symbol)
        if entry and entry["value"] is not None and now - entry["ts"] < PRIOR_LEVELS_CACHE_SEC:
            return entry["value"]
    try:
        levels = trader.fetch_prior_day_levels(symbol)
        with _levels_lock:
            _levels_cache[symbol] = {"value": levels, "ts": now}
        return levels
    except Exception as e:
        log.warning(f"Prior-day levels fetch failed for {symbol}: {e}")
        with _levels_lock:
            stale = _levels_cache.get(symbol)
        return (stale or {}).get("value") or {}


def refresh_prices() -> None:
    """Fast path — refresh ONLY the active symbol (sub-second). Called inline
    from login + UI refresh handlers. Other symbols' freshness is updated by
    refresh_all_prices() running on the price_ticker background thread.
    """
    try:
        price, chg_pct, session = trader.get_symbol_price(state["active_symbol"])
        with _state_lock:
            state["market_session"] = session
            if price is not None:
                state["spy_price"]      = price
                state["spy_change_pct"] = chg_pct
    except Exception as e:
        log.warning(f"refresh_prices (price) failed: {e}")
    try:
        vix = _cached_vix()
        if vix:
            with _state_lock:
                state["vix"] = round(vix, 2)
    except Exception as e:
        log.warning(f"refresh_prices (vix) failed: {e}")


def refresh_all_prices() -> None:
    """Background path — refresh ALL 6 symbols so Data Freshness panel stays
    green for every tab. Slow (1-3s total) so this is only called from the
    price_ticker thread, never from a request handler.
    """
    active_sym = state["active_symbol"]
    for sym in _SYMBOLS_ORDERED:
        try:
            price, chg_pct, session = trader.get_symbol_price(sym)
            if sym == active_sym:
                with _state_lock:
                    state["market_session"] = session
                    if price is not None:
                        state["spy_price"]      = price
                        state["spy_change_pct"] = chg_pct
        except Exception as e:
            log.warning(f"refresh_all_prices ({sym}) failed: {e}")
    try:
        vix = _cached_vix()
        if vix:
            with _state_lock:
                state["vix"] = round(vix, 2)
    except Exception as e:
        log.warning(f"refresh_all_prices (vix) failed: {e}")


# ── Background-thread heartbeats (for a meaningful /health) ───────────────────
# launchd KeepAlive restarts a DEAD process. It can't detect a HUNG one —
# Flask still answering HTTP while the position_monitor thread is wedged
# (deadlock, eventlet stall) = positions silently unmanaged, stops never
# fire. We stamp a heartbeat at the top of each critical loop; /health turns
# 503 if the position monitor goes stale so the watchdog can kill+restart.
_heartbeats = {"position_monitor": 0.0, "price_ticker": 0.0, "scheduler": 0.0}
_heartbeats_lock = threading.Lock()

def _beat(name: str) -> None:
    with _heartbeats_lock:
        _heartbeats[name] = time.time()

def heartbeat_age(name: str) -> float:
    with _heartbeats_lock:
        ts = _heartbeats.get(name, 0.0)
    return float("inf") if ts == 0.0 else (time.time() - ts)


def price_ticker() -> None:
    """Background thread: refresh prices on TICKER_INTERVAL_SEC.
    Gated on streaming + at least one authenticated client connected.
    Also refreshes account/buying power every ACCOUNT_REFRESH_TICKS iterations
    so the header stays current without waiting for a fill."""
    tick = 0
    while True:
        _beat("price_ticker")
        try:
            with _state_lock:
                # Run as long as we're logged in — headless auto-execute needs
                # fresh prices even when no browser is connected. Streaming
                # flag still gates UI broadcasts but data must stay current.
                should_run    = state["logged_in"] and state["streaming"]
                has_browsers  = len(authenticated_sids) > 0
            if should_run:
                # Only the active symbol — no more 40-symbol fan-out on every
                # 3rd tick (#14). refresh_all_prices and _prewarm_next_chart
                # were optimizations for a multi-tab chart grid that's being
                # removed; if a user switches to a different chart tab the
                # cache will be cold by ~120s, which is fine.
                refresh_prices()
                if tick % ACCOUNT_REFRESH_TICKS == 0:
                    refresh_account()
                emit_state()
                tick += 1
        except Exception as e:
            log.warning(f"price_ticker iteration failed: {e}")
        socketio.sleep(TICKER_INTERVAL_SEC)


def position_monitor() -> None:
    """Background thread: evaluate open positions every 10s.
    Closes at stop-loss, profit target 1 (partial), profit target 2, or hard-close time.

    NOTE: intentionally does NOT gate on authenticated_sids. Stop-loss/target
    execution must continue even when all browser tabs are closed or a network
    blip causes a temporary disconnect — halting it would leave open positions
    unmanaged until the user reconnects, which is dangerous."""
    while True:
        socketio.sleep(POSITION_MONITOR_SEC)
        _beat("position_monitor")   # loop is alive (even if idle below)
        try:
            with _state_lock:
                should_run = state["logged_in"]   # runs as long as Alpaca is connected
            if not should_run:
                continue

            events = trader.check_positions()
            for ev in events:
                arrow = "▲" if ev["pnl_pct"] > 0 else "▼"
                tag   = "PARTIAL" if ev.get("is_partial") else "CLOSED"
                msg   = (
                    f"{arrow} {tag} {ev['close_qty']}x {ev['occ_symbol']}  "
                    f"{ev['reason']}  P&L {ev['pnl_pct']:+.1f}%"
                )
                socketio.emit("log", {"message": msg, "level": "INFO"})
                close_entry = {
                    "symbol":       ev["symbol"],
                    "direction":    ev["direction"],
                    "pnl_pct":      ev["pnl_pct"],
                    "reason":       ev["reason"],
                    "time":         datetime.now(ET).strftime("%H:%M"),
                    "is_partial":   ev.get("is_partial", False),
                    "signal_class": ev.get("signal_class", "unknown"),
                }
                with _state_lock:
                    state["trades_today"].append(close_entry)
                _save_trades_today()   # persist for restart safety (#17)
                # Wire update_outcome into ChromaDB for full (non-partial) closes
                if not ev.get("is_partial") and ev.get("order_id"):
                    hold_min = 0.0
                    if ev.get("opened_at"):
                        try:
                            opened = datetime.fromisoformat(ev["opened_at"])
                            hold_min = (datetime.now(ET) - opened).total_seconds() / 60
                        except Exception:
                            pass
                    trader.TRADE_MEMORY.update_outcome(
                        ev["order_id"], ev["pnl_pct"], hold_min
                    )

            if events:
                refresh_account()
                emit_state()

            # Autonomous-engine exit management (REQ-608/609). This does several
            # Alpaca + yfinance calls (account fetch, option exits, per-symbol price,
            # closes) — heavy enough to stall the eventlet hub if run every 10s tick.
            # Throttle to ~every 30s; stops still fire well within tolerance.
            if (auto_engine.DUAL_ENGINE_ENABLED and auto_engine.DUAL_ENGINE_MODE == "execute"
                    and time.monotonic() - _exit_mgmt_state["last"] >= 30):
                _exit_mgmt_state["last"] = time.monotonic()
                try:
                    _protect_untracked_stocks()        # give stock buys a stop too
                    _manage_option_positions()         # ±20% exit on options
                    auto_engine.manage_exits(dry_run=False)
                except Exception as e:
                    log.warning(f"[auto-engine] manage_exits error: {e}")

        except Exception as e:
            log.warning(f"position_monitor error: {e}")


def _run_eod_review(trades_snapshot: list) -> None:
    """Run end-of-day learning review and broadcast results to the UI."""
    log.info("EOD Review: starting analysis…")
    socketio.emit("log", {"message": "── EOD Learning Review starting… ──", "level": "INFO"})
    try:
        # Persist today's closing equity for weekly-drawdown tracking
        try:
            acct_val = trader.account_value()
            if acct_val > 0:
                trader.record_eod_equity(acct_val)
                dd5 = trader.rolling_drawdown_pct(5) * 100
                dd20 = trader.rolling_drawdown_pct(20) * 100
                socketio.emit("log", {
                    "message": f"EOD equity: ${acct_val:,.2f}  |  5-day DD: {dd5:.2f}%  |  20-day DD: {dd20:.2f}%",
                    "level": "INFO",
                })
        except Exception as e:
            log.warning(f"EOD equity snapshot failed: {e}")

        review = trader.eod_review(LOG_PATH, trades_snapshot)
        for line in review.splitlines():
            if line.strip():
                socketio.emit("log", {"message": line, "level": "INFO"})
        # Autonomous-engine EOD summary (its own closed-trades review)
        try:
            for line in auto_engine.eod_summary().splitlines():
                if line.strip():
                    socketio.emit("log", {"message": line, "level": "INFO"})
        except Exception as e:
            log.warning(f"auto-engine EOD summary failed: {e}")
        log.info("EOD Review: complete")
    except Exception as e:
        log.warning(f"EOD Review failed: {e}")


# ── Routes ────────────────────────────────────────────────────────────────────
def _render_spa():
    session.permanent = True
    resp = make_response(render_template("index.html"))
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    resp.headers["Pragma"]        = "no-cache"
    resp.headers["Expires"]       = "0"
    return resp


@app.route("/")
def index():
    return _render_spa()


# Deep-link routes — same SPA, the frontend opens the matching view from the path.
@app.route("/screener")
@app.route("/log")
def spa_view():
    return _render_spa()


# Charts now live on the standalone charts server (operator request 2026-06-01):
# decoupled so charts are viewable with no Alpaca login, independent of this
# trading app. Keep the old deep-link working by redirecting to :5001.
CHARTS_SERVER_URL = os.environ.get("CHARTS_SERVER_URL", "http://localhost:5001/charts")


@app.route("/charts")
def charts_redirect():
    from flask import redirect as _redirect
    return _redirect(CHARTS_SERVER_URL, code=302)


@app.route("/api/status")
@limiter.limit(API_STATUS_RATE_LIMIT)
def api_status():
    if not session.get("authenticated"):
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify({k: v for k, v in state.items() if k != "trades_today"})


@app.route("/health")
def health():
    """Meaningful liveness — not just 'Flask answers'. The watchdog hits this;
    a 503 means a critical background loop is wedged so it should kill the
    process (launchd KeepAlive then restarts a clean one).

    position_monitor must tick every POSITION_MONITOR_SEC (10s). We allow
    6× slack (60s) before declaring it stale — covers a slow check_positions
    cycle without false-positiving. price_ticker/scheduler are reported but
    not fatal (a stale ticker is cosmetic; a stale monitor = unmanaged
    positions = dangerous)."""
    pm_age   = heartbeat_age("position_monitor")
    pt_age   = heartbeat_age("price_ticker")
    sc_age   = heartbeat_age("scheduler")
    pm_stale = pm_age > (POSITION_MONITOR_SEC * 6)
    # Scheduler ticks every 15s; if > 6× (90s) it's drifting badly. Counts
    # as degraded because the screener auto-refresh + auto-execute path live
    # inside the scheduler — silent failure here used to mean no signals fired.
    sc_stale = sc_age > (SCHEDULER_INTERVAL_SEC * 6)

    with _state_lock:
        logged_in     = state["logged_in"]
        paper         = state["paper_mode"]
        auto_exec     = state["auto_execute_options"]
        trades_count  = len(state["trades_today"])

    # Screener cache age (None if never refreshed)
    try:
        import time as _t
        _cached = screener.get_cached()
        cache_ts = _cached.get("ts", 0) if _cached else 0
        screener_age_s = round(_t.time() - cache_ts, 1) if cache_ts else None
        screener_options_count = len(_cached.get("options", [])) if _cached else 0
    except Exception:
        screener_age_s = None
        screener_options_count = 0

    with _auto_exec_lock:
        auto_exec_today_count = len(_auto_exec_filled)   # filled trades, not attempts

    degraded = pm_stale or sc_stale
    body = {
        "status": "degraded" if degraded else "ok",
        "logged_in":              logged_in,
        "paper_mode":             paper,
        # Heartbeats
        "position_monitor_age_s": None if pm_age == float("inf") else round(pm_age, 1),
        "price_ticker_age_s":     None if pt_age == float("inf") else round(pt_age, 1),
        "scheduler_age_s":        None if sc_age == float("inf") else round(sc_age, 1),
        # Auto-execute observability (#6 — see RUNBOOK.md "why isn't it trading?")
        "auto_execute_options":   auto_exec,
        "auto_exec_today_count":  auto_exec_today_count,
        "auto_exec_cap":          MAX_AUTO_EXEC_PER_DAY,
        # Screener cache freshness — if scheduler is healthy but this is high,
        # _refresh_screener_bg is stuck (e.g. _screener_refresh_lock held)
        "screener_cache_age_s":   screener_age_s,
        "screener_options_count": screener_options_count,
        # Position monitor activity
        "trades_today_count":     trades_count,
        "boots_24h":              _boots_last_24h(),   # OB-5: restart frequency (instability)
    }
    # inf age right after boot is normal (loop hasn't ticked yet) — don't 503
    # on a cold start; only 503 once it has ticked then went stale.
    fatal = pm_stale and pm_age != float("inf")
    return jsonify(body), (503 if fatal else 200)


# ── WebSocket events ──────────────────────────────────────────────────────────
@socketio.on("connect")
def on_connect():
    ip = request.remote_addr
    security_log.info(f"WebSocket connect from {ip}")
    # Restore auth across reconnects from the Flask session cookie (8h lifetime).
    # Auth is otherwise bound to the socket id, so a reconnect (after any hub stall
    # or network blip) would log the browser out and force an Alpaca re-login —
    # the "logging off often" symptom. If this browser already authenticated and
    # the shared Alpaca client is connected, silently re-grant the new sid.
    _reauthed = False
    if (request.sid not in authenticated_sids
            and session.get("authenticated")
            and getattr(trader, "TRADING_CLIENT", None) is not None):
        with _state_lock:
            authenticated_sids.add(request.sid)
        _reauthed = True
        security_log.info(f"Re-authenticated reconnecting browser from {ip} (session cookie)")
    # Per-client state with `logged_in` reflecting this specific socket's auth.
    snapshot = _state_snapshot()
    snapshot["logged_in"] = request.sid in authenticated_sids
    login_log.info(f"⊙ ws connect  ip={ip}  sid={request.sid}  "
                   f"authed={snapshot['logged_in']}  "
                   f"{'(cookie re-auth)' if _reauthed else ('(has session, no client)' if session.get('authenticated') else '(fresh)')}")
    socketio.emit("state", snapshot, to=request.sid)


_EXIT_CFG_FILE = os.path.expanduser("~/.spy_trader/exit_config.json")


def _apply_exit_config(cfg: dict) -> None:
    """Set the live exit thresholds from a config dict (% values → fractions)."""
    try:
        if "stock_tp_pct" in cfg: auto_engine.STOCK_TAKE_PROFIT_PCT = max(0.1, float(cfg["stock_tp_pct"])) / 100
        if "stock_sl_pct" in cfg: auto_engine.STOCK_STOP_PCT        = max(0.1, float(cfg["stock_sl_pct"])) / 100
        if "opt_tp_pct"   in cfg: screener_executor.OPT_TAKE_PROFIT_PCT = max(1.0, float(cfg["opt_tp_pct"])) / 100
        if "opt_sl_pct"   in cfg: screener_executor.OPT_STOP_LOSS_PCT   = max(1.0, float(cfg["opt_sl_pct"])) / 100
        if "stock_stall_days" in cfg: auto_engine.STALL_MINUTES = max(60, int(float(cfg["stock_stall_days"]) * 1440))
        if "opt_stall_min"    in cfg: screener_executor.OPT_STALL_MINUTES = max(5, int(cfg["opt_stall_min"]))
        if "opt_dynamic_exit" in cfg: screener_executor.OPT_DYNAMIC_EXIT_ENABLED = bool(cfg["opt_dynamic_exit"])
        if "time_cap_days" in cfg: auto_engine.TIME_CAP_DAYS = max(1, int(cfg["time_cap_days"]))
    except Exception as e:
        log.warning(f"apply exit config: {e}")


def _load_exit_config() -> None:
    try:
        import json as _j
        with open(_EXIT_CFG_FILE) as fh:
            _apply_exit_config(_j.load(fh))
        log.info("[exit-config] restored saved exit thresholds")
    except (FileNotFoundError, ValueError, OSError):
        pass


@socketio.on("set_exit_config")
@require_auth
def on_set_exit_config(data):
    """Operator-editable exit thresholds (±% stocks/options, stall, time cap)."""
    if not isinstance(data, dict):
        return
    _apply_exit_config(data)
    try:
        import json as _j
        os.makedirs(os.path.dirname(_EXIT_CFG_FILE), exist_ok=True)
        with open(_EXIT_CFG_FILE, "w") as fh:
            _j.dump(data, fh)
    except Exception as e:
        log.warning(f"persist exit config: {e}")
    _emit_log(f"Exit thresholds updated: stocks ±{auto_engine.STOCK_TAKE_PROFIT_PCT*100:.1f}% · "
              f"options ±{screener_executor.OPT_TAKE_PROFIT_PCT*100:.0f}% · "
              f"stall {auto_engine.STALL_MINUTES}min", level="INFO")
    emit_state()


@socketio.on("run_eod_analysis")
@require_auth
def on_run_eod_analysis():
    """Trigger EOD analysis + learning on demand."""
    socketio.start_background_task(_run_eod_analysis)


@socketio.on("refresh_positions")
def on_refresh_positions():
    """Force a FRESH pull of account positions and push state to the caller (used by
    the Positions tab refresh button). NOT auth-gated — only reads/emits positions
    the client already sees, and avoids the disconnect that the auth-gated 'refresh'
    would cause if the socket isn't authenticated."""
    try:
        _acct_pos_cache["ts"] = 0.0      # invalidate cache → next read re-fetches
        snap = _state_snapshot()
        snap["logged_in"] = request.sid in authenticated_sids
        socketio.emit("state", snap, to=request.sid)
    except Exception as e:
        log.debug(f"refresh_positions: {e}")


@socketio.on("disconnect")
def on_disconnect():
    """Disconnect a browser session.

    IMPORTANT: do NOT clear state["logged_in"] here. The server may be
    running headless (auto-login from .env) and managing open positions
    without any browser connected. Clearing the global flag would halt
    position_monitor and auto-execute the moment the last tab closes.

    Per-browser auth is enforced separately via authenticated_sids: when a
    new tab opens, on_connect checks its sid against the set and surfaces
    the login modal if it's not authenticated."""
    with _state_lock:
        authenticated_sids.discard(request.sid)
    security_log.info(f"WebSocket disconnect from {request.remote_addr}")


@socketio.on("login")
@limiter.limit(LOGIN_RATE_LIMIT, key_func=get_remote_address)
def on_login(data):
    ip = request.remote_addr
    _kp = str((data or {}).get("api_key", ""))[:6]
    login_log.info(f"◀ login attempt  ip={ip}  sid={getattr(request,'sid','?')}  "
                   f"key={_kp}…  paper={(data or {}).get('paper', True)}")

    locked, remaining = login_tracker.is_locked(ip)
    if locked:
        mins = remaining // 60 + 1
        login_log.warning(f"✗ blocked — IP locked, {remaining}s remaining")
        security_log.warning(f"Blocked login from locked IP {ip} ({remaining}s remaining)")
        socketio.emit("login_result", {
            "success": False,
            "error":   f"Too many failed attempts. Try again in {mins} minute(s)."
        })
        return

    try:
        api_key    = validate_api_key   (data.get("api_key", ""))
        api_secret = validate_api_secret(data.get("api_secret", ""))
        paper      = bool(data.get("paper", True))
    except ValueError as e:
        login_tracker.record_failure(ip)
        socketio.emit("login_result", {"success": False, "error": str(e)})
        return

    # 3R-A.3 — live login gate: refuse if paper risk overrides exceed the
    # live-disciplined ceiling, unless the user explicitly confirms.
    # This prevents paper-aggressive settings from silently carrying into live.
    if not paper and not data.get("live_risk_confirmed", False):
        violations = []
        risk_ov = getattr(trader, "_ui_risk_override", None)
        port_ov = getattr(trader, "_ui_portfolio_risk_override", None)
        if risk_ov is not None and risk_ov > trader.SUB10K_MAX_RISK_PCT:
            violations.append(
                f"per-trade risk {risk_ov*100:.1f}% > live ceiling {trader.SUB10K_MAX_RISK_PCT*100:.0f}%"
            )
        if port_ov is not None and port_ov > trader.SUB10K_MAX_PORTFOLIO_RISK:
            violations.append(
                f"portfolio risk {port_ov*100:.1f}% > live ceiling {trader.SUB10K_MAX_PORTFOLIO_RISK*100:.0f}%"
            )
        if violations:
            msg = (
                "Live mode refused — paper risk overrides exceed live-disciplined limits: "
                + "; ".join(violations)
                + ". Reset Settings to default or re-submit with live_risk_confirmed=true "
                  "(live mode will cap them to the disciplined profile)."
            )
            log.warning(f"🚫 {msg}")
            socketio.emit("login_result", {"success": False, "error": msg,
                                           "risk_override_conflict": True})
            return

    # Fast path: the server is often already authenticated via _auto_login
    # at boot using the same credentials from .env. Re-running init_clients
    # makes a fresh Alpaca handshake (1-3s) and an extra account-fetch network
    # call for no real benefit — eventlet hub stalls during it block other
    # greenlets including subsequent UI events. Skip when we can verify
    # the requested key matches the active one.
    import eventlet as _ev
    fast_path_taken = False
    try:
        with _state_lock:
            already_logged_in = state["logged_in"]
            same_paper_mode   = state["paper_mode"] == paper
        if (already_logged_in and same_paper_mode
                and getattr(trader, "TRADING_CLIENT", None) is not None
                and getattr(trader, "ACTIVE_KEY_PREFIX", "") == api_key[:6]):
            # Cheap call — already-cached client, no fresh handshake. Still
            # bounded: if the cached client has gone stale and hangs, fall back
            # fast rather than freezing the login.
            with _ev.Timeout(trader.LOGIN_VERIFY_TIMEOUT_SEC):
                account = trader.TRADING_CLIENT.get_account()
            ok, err = True, None
            fast_path_taken = True
            login_log.info("  fast-path OK (already authed, cached client)")
    except (Exception, _ev.Timeout) as e:
        login_log.info(f"  fast-path probe failed ({e}) → full init")
        log.info(f"Login fast-path probe failed ({e}); falling back to full init")
        fast_path_taken = False

    # Slow path: full Alpaca handshake + client init (first browser login, or
    # different credentials than auto-login's).
    if not fast_path_taken:
        login_log.info("  slow-path: init_clients (fresh Alpaca handshake, ≤8s)…")
        account, ok, err = trader.init_clients(api_key, api_secret, paper=paper)
        if ok:
            # Stash the active key prefix so subsequent logins can fast-path
            try:
                trader.ACTIVE_KEY_PREFIX = api_key[:6]
            except Exception:
                pass

    if not ok:
        login_tracker.record_failure(ip)
        # Include the paper-mode flag + key prefix so we can diagnose
        # "credentials work in curl but not in app" mismatches.
        key_prefix = api_key[:6] if api_key else "?"
        login_log.warning(f"✗ login FAILED  key={key_prefix}…  paper={paper}  err={err}")
        security_log.warning(
            f"Failed Alpaca login from {ip}: paper={paper} key={key_prefix}... "
            f"err={err}"
        )
        socketio.emit("login_result", {
            "success": False,
            "error":   f"Login failed: {err[:120] if err else 'invalid credentials'}"
        })
        return

    with _state_lock:
        state["logged_in"]   = True
        state["paper_mode"]  = paper
        authenticated_sids.add(request.sid)
    session.permanent         = True            # honor PERMANENT_SESSION_LIFETIME (8h)
    session["authenticated"]  = True            # allows /api/status + reconnect re-auth
    session["api_key_prefix"] = api_key[:6] + "…"
    session["login_time"]     = datetime.now(timezone.utc).isoformat()
    login_tracker.record_success(ip)
    login_log.info(f"✔ login SUCCESS  ({'fast-path' if fast_path_taken else 'full init'})  "
                   f"paper={paper}  sid={request.sid}  → login_result emitted")
    security_log.info(f"Successful Alpaca login from {ip} (paper={paper})")

    # Tell the client login succeeded IMMEDIATELY — before any slow data
    # fetch. refresh_account()/refresh_prices() hit yfinance+Alpaca and can
    # take 1-5s; if we block the emit behind them the UI spins, the user
    # assumes failure and retries (→ duplicate logins in the log).
    socketio.emit("login_result", {"success": True}, to=request.sid)

    trader.init_memory(enabled=state.get("trade_memory_enabled", True))
    trader.init_debate(enabled=state.get("debate_enabled", True))
    trader.init_news_filter(enabled=state.get("news_filter_enabled", True))
    trader.DRY_RUN = state.get("dry_run", False)
    trade_approval.auto_trade = state.get("auto_trade", True)
    mode_str = "PAPER" if paper else "LIVE"
    log.info(f"Connected to Alpaca {mode_str} — equity ${float(account.equity):,.2f}")

    # Surface system state to the log tab on every login
    def _login_status_lines():
        socketio.sleep(1)   # let the client finish login_result handling first
        debate_on  = trader.DEBATE_ENABLED
        dry_on     = trader.DRY_RUN
        auto_on    = trade_approval.auto_trade
        eq         = float(account.equity)
        socketio.emit("log", {"message": "─" * 52,          "level": "INFO"})
        socketio.emit("log", {"message": f"Connected  Alpaca {mode_str}  equity=${eq:,.2f}", "level": "INFO"})
        socketio.emit("log", {"message":
            f"  Debate gate : {'✓ ON' if debate_on else '✗ OFF'}"
            f"   |  Auto-trade: {'✓ ON' if auto_on else '✗ OFF'}"
            f"   |  Dry-run: {'ON' if dry_on else 'off'}",
            "level": "INFO"})
        # Daily positions snapshot
        try:
            positions = dtrad._load_positions()
            open_pos = [p for p in positions if p["status"] in ("open", "pending", "signal")]
            if open_pos:
                socketio.emit("log", {"message": f"  Daily positions ({len(open_pos)}):", "level": "INFO"})
                for p in open_pos:
                    instr = p.get("structure", p.get("instrument", "?"))
                    socketio.emit("log", {"message":
                        f"    {p['sym']:6}  {instr:6}  entry={p['entry_date']}"
                        f"  debit=${p.get('entry_debit') or p.get('est_debit','?')}"
                        f"  [{p['status']}]",
                        "level": "INFO"})
            else:
                socketio.emit("log", {"message": "  Daily positions: none", "level": "INFO"})
        except Exception:
            pass
        socketio.emit("log", {"message": "─" * 52, "level": "INFO"})
    socketio.start_background_task(_login_status_lines)

    # Slow path AFTER the client already knows it's in — populate header/state.
    def _post_login_refresh():
        try:
            refresh_account()
            refresh_prices()
            emit_state()
        except Exception as e:
            log.warning(f"post-login refresh failed: {e}")
    socketio.start_background_task(_post_login_refresh)


@socketio.on("logout")
@require_auth
def on_logout():
    # Stop all running sessions before clearing clients
    for sym in _SYMBOLS_ORDERED:
        _session_stop_events[sym].set()
    trader.TRADING_CLIENT = None
    trader.DATA_CLIENT    = None
    trader.OPTION_CLIENT  = None
    with _state_lock:
        authenticated_sids.discard(request.sid)
        state["logged_in"] = False
        for sym in _SYMBOLS_ORDERED:
            state["sessions"][sym] = False
    session.clear()
    security_log.info(f"Logout from {request.remote_addr}")
    emit_state()


@socketio.on("set_dry_run")
@require_auth
def on_set_dry_run(data):
    try:
        val = validate_bool(data.get("dry_run", True))
    except ValueError:
        return
    trader.DRY_RUN   = val
    state["dry_run"] = val
    log.info(f"Mode: {'DRY RUN' if val else 'LIVE TRADING'}")
    security_log.info(f"DRY_RUN set to {val} by {session.get('user_email')}")
    emit_state()


@socketio.on("set_risk")
@require_auth
def on_set_risk(data):
    try:
        pct = validate_risk_pct(data.get("risk_pct", 0.5))
    except ValueError as e:
        socketio.emit("log", {"message": f"Invalid risk: {e}", "level": "WARNING"})
        return
    trader.MAX_RISK_PCT = pct / 100.0
    trader._ui_risk_override = pct / 100.0   # UI choice wins over sub-10K profile
    log.info(f"Risk per trade updated to {pct}% (UI override — wins over account-size profile)")


@socketio.on("set_max_portfolio_risk")
@require_auth
def on_set_max_portfolio_risk(data):
    try:
        pct = float(data.get("pct", 3))
        if not (0.5 <= pct <= 50):
            raise ValueError("must be 0.5–50%")
    except (TypeError, ValueError) as e:
        socketio.emit("log", {"message": f"Invalid max portfolio risk: {e}", "level": "WARNING"})
        return
    trader.MAX_PORTFOLIO_RISK = pct / 100.0
    trader._ui_portfolio_risk_override = pct / 100.0  # UI wins over sub-10K profile
    log.info(f"Max portfolio risk updated to {pct}% (UI override — wins over account-size profile)")
    emit_state()


@socketio.on("set_param")
@require_auth
def on_set_param(data):
    """Update a numeric trader parameter via stepper."""
    field = data.get("field", "")
    value = data.get("value")
    try:
        if field == "vix_max":
            v = validate_vix_max(value)
            trader.VIX_MAX  = v
            state["vix_max"] = v
            log.info(f"VIX max set to {v}")
        elif field == "stop_loss":
            v = validate_stop_loss(value)
            trader.STOP_LOSS_PCT = v / 100.0
            state["stop_loss"]    = v
            log.info(f"Stop loss set to -{v}%")
        elif field == "profit_target":
            v = validate_profit_target(value)
            trader.PROFIT_TARGET = v / 100.0
            state["profit_target"] = v
            log.info(f"Profit target set to +{v}%")
        elif field == "dte_min":
            v = validate_dte(value)
            if v > state["dte_max"]:
                raise ValueError("DTE min cannot exceed DTE max.")
            trader.DTE_MIN  = v
            state["dte_min"] = v
            log.info(f"DTE min set to {v}")
        elif field == "dte_max":
            v = validate_dte(value)
            if v < state["dte_min"]:
                raise ValueError("DTE max cannot be less than DTE min.")
            trader.DTE_MAX  = v
            state["dte_max"] = v
            log.info(f"DTE max set to {v}")
        else:
            return
        emit_state()
    except ValueError as e:
        socketio.emit("log", {"message": f"Invalid value: {e}", "level": "WARNING"})


@socketio.on("set_session_end")
@require_auth
def on_set_session_end(data):
    """Update the all-day session end time. Format HH:MM (24h)."""
    try:
        end_time = (data or {}).get("session_end", "15:45")
        validate_time(end_time)
        with _state_lock:
            state["session_end"] = end_time
        log.info(f"Session end time set to {end_time} ET")
        emit_state()
    except ValueError as e:
        socketio.emit("log", {"message": f"Invalid time: {e}", "level": "WARNING"})


def _launch_session(sym: str) -> None:
    """Start all-day trading session for `sym`. Safe to call from any thread."""
    sym = sym.upper()
    if sym not in VALID_SYMBOLS:
        log.warning(f"_launch_session: invalid symbol {sym}")
        return

    with _state_lock:
        if state["sessions"].get(sym, False):
            log.info(f"Session for {sym} already running — ignoring duplicate start.")
            return
        filter_on = state["news_filter_enabled"]

    # Note: portfolio risk cap is enforced INSIDE the trade-entry logic
    # (spy_auto_trader.all_day_session checks deployed_risk before placing
    # new orders). We don't gate session startup itself, so sessions can
    # still monitor existing positions even when at the risk cap.

    if filter_on:
        vetoed, reason = news_filter.check_news_sentiment(sym)
        if vetoed:
            log.warning(f"{sym} session blocked by news filter: {reason}")
            socketio.emit("log", {
                "message": f"⚠ News filter blocked {sym} session: {reason}",
                "level": "WARNING",
            })
            return

    stop_ev = _session_stop_events[sym]
    stop_ev.clear()

    with _state_lock:
        state["sessions"][sym] = True
    _ensure_awake()
    emit_state()

    def run():
        try:
            with _state_lock:
                end_val = state.get("session_end", "15:45")
            eh, em = validate_time(end_val)
            prior = _cached_prior_levels(sym)
            vix   = _cached_vix()
            trader.all_day_session(
                symbol=sym, prior_levels=prior, vix=vix,
                stop_event=stop_ev, end_hour=eh, end_minute=em,
            )
        except Exception as e:
            log.error(f"Session error ({sym}): {e}")
        finally:
            with _state_lock:
                state["sessions"][sym] = False
            _release_awake()
            refresh_account()
            emit_state()

    t = threading.Thread(target=run, daemon=True, name=f"session-{sym}")
    _session_threads[sym] = t
    t.start()


EOD_REVIEW_HOUR   = 15
EOD_REVIEW_MINUTE = 35
# Daily strategy scheduler windows (Connors RSI-2 daily-bar, Path A)
DAILY_EOD_HOUR      = 16
DAILY_EOD_MINUTE    = 10   # ~4:10 PM ET — after close prints
DAILY_MORNING_HOUR  = 9
DAILY_MORNING_MINUTE = 35  # ~9:35 AM ET — fills confirmed by then
LOG_PATH = os.path.join(os.path.dirname(__file__), "spy_trader.log")


# ── Daily strategy background tasks (Connors RSI-2, Path A) ──────────────────
def _emit_log(msg: str, level: str = "INFO") -> None:
    """Emit a line to the dashboard log tab and the server log."""
    socketio.emit("log", {"message": msg, "level": level})
    if level == "ERROR":
        log.error(msg)
    elif level == "WARNING":
        log.warning(msg)
    else:
        log.info(msg)


def _alert(title: str, msg: str = "", level: str = "ERROR") -> None:
    """OB-2 — push a critical alert so failures aren't silent: always to the UI Log +
    server log, and to ALERT_WEBHOOK_URL (env, e.g. Slack/Discord) when configured.
    Use for breaker trips, naked-leg rollback failures, repeated fill failures. Never raises."""
    _emit_log(f"🚨 ALERT — {title}{(' · ' + msg) if msg else ''}", level=level)
    url = os.environ.get("ALERT_WEBHOOK_URL", "").strip()
    if not url:
        return
    try:
        import json as _j, urllib.request as _u
        body = _j.dumps({"text": f"[AlpacaTrader] {title}\n{msg}"}).encode()
        req = _u.Request(url, data=body, headers={"Content-Type": "application/json"})
        # short timeout; runs in a background greenlet — must not wedge the caller
        _u.urlopen(req, timeout=5).read()
    except Exception as e:
        log.debug(f"alert webhook failed: {e}")


# ── OB-5: health history — restart frequency is a wedge/instability proxy ─────
_HEALTH_HISTORY_PATH = os.path.expanduser("~/.spy_trader/health_history.jsonl")


def _record_boot() -> None:
    """Append a boot event so restart frequency is visible. The watchdog kills+relaunches a
    wedged process, so frequent boots = instability. Append-only; never raises."""
    try:
        import json as _j, datetime as _dt
        os.makedirs(os.path.dirname(_HEALTH_HISTORY_PATH), exist_ok=True)
        with open(_HEALTH_HISTORY_PATH, "a") as fh:
            fh.write(_j.dumps({"ts": _dt.datetime.now().isoformat(),
                               "event": "boot", "pid": os.getpid()}) + "\n")
    except Exception as e:
        log.debug(f"health history: {e}")


def _boots_last_24h() -> int:
    """Count boot events in the last 24h (restart-frequency / instability signal)."""
    try:
        import json as _j, datetime as _dt
        cutoff = _dt.datetime.now() - _dt.timedelta(hours=24)
        n = 0
        with open(_HEALTH_HISTORY_PATH) as fh:
            for line in fh:
                try:
                    r = _j.loads(line)
                    if r.get("event") == "boot" and _dt.datetime.fromisoformat(r["ts"]) >= cutoff:
                        n += 1
                except Exception:
                    pass
        return n
    except Exception:
        return 0


def _run_daily_eod() -> None:
    """EOD routine for the daily Connors RSI(2) strategy.
    Fires at DAILY_EOD_HOUR:DAILY_EOD_MINUTE ET. Respects app's dry_run state."""
    with _state_lock:
        dry = state["dry_run"]
    try:
        _emit_log("─" * 52)
        _emit_log(f"DAILY EOD  Connors RSI(2)  {'[DRY RUN]' if dry else '[PAPER]'}")
        summary = dtrad.run_eod(dry_run=dry)
        socketio.emit("daily_eod_result", summary)

        # Surface per-signal detail to the log tab
        positions = dtrad._load_positions()
        new_signals = [p for p in positions if p["status"] == "signal"]
        pending_exits = [p for p in positions if p["status"] == "exit_pending"]

        if not new_signals and not pending_exits:
            _emit_log("  No new signals today.")
        for p in new_signals:
            instr = p.get("structure", "?")
            occ   = p.get("long_occ", "?")
            deb   = p.get("est_debit", "?")
            exp   = p.get("expiry", "?")
            dte   = p.get("dte", "?")
            ivhv  = p.get("iv_hv", "?")
            ivr   = p.get("ivr", "?")
            _emit_log(
                f"  ▲ ENTRY  {p['sym']:6}  {instr:6}  "
                f"occ={occ}  debit=${deb}  exp={exp}  "
                f"DTE={dte}  IVR={ivr}%  IV/HV={ivhv}"
            )
        for p in pending_exits:
            _emit_log(
                f"  ✗ EXIT   {p['sym']:6}  reason={p.get('exit_reason','?')}  "
                f"→ order at morning open",
                level="WARNING"
            )
        _emit_log(
            f"  Summary: {summary['entries']} entr, {summary['exits']} exit, "
            f"{summary['open']} open"
        )
    except Exception as e:
        _emit_log(f"Daily EOD error: {e}", level="ERROR")


def _run_daily_morning() -> None:
    """Morning fill-confirm for the daily Connors RSI(2) strategy.
    Fires at DAILY_MORNING_HOUR:DAILY_MORNING_MINUTE ET."""
    with _state_lock:
        dry = state["dry_run"]
    try:
        _emit_log("─" * 52)
        _emit_log(f"DAILY MORNING  fill-confirm  {'[DRY RUN]' if dry else '[PAPER]'}")

        # Snapshot status before so we can report what changed
        before = {p["sym"]: p["status"] for p in dtrad._load_positions()}

        dtrad.run_morning(dry_run=dry)

        positions = dtrad._load_positions()
        for p in positions:
            was = before.get(p["sym"], "?")
            now_s = p["status"]
            sym   = p["sym"]
            instr = p.get("structure", p.get("instrument", "?"))
            if was == "signal" and now_s == "pending":
                _emit_log(
                    f"  ⏳ ORDER SUBMITTED  {sym:6}  {instr}  "
                    f"long={p.get('long_occ','?')}  "
                    f"est_debit=${p.get('est_debit','?')}"
                )
            elif was in ("signal", "pending") and now_s == "open":
                _emit_log(
                    f"  ✓ FILLED  {sym:6}  {instr}  "
                    f"debit=${p.get('entry_debit','?')}  "
                    f"stop_debit=${p.get('stop_debit','?')}"
                )
            elif was == "open" and now_s == "exit_pending":
                _emit_log(
                    f"  ⚠ STOP HIT  {sym:6}  reason={p.get('exit_reason','?')}",
                    level="WARNING"
                )
            elif was == "exit_pending" and now_s == "closed":
                pnl = ""
                if p.get("entry_debit") and p.get("exit_debit"):
                    raw = (float(p["exit_debit"]) - float(p["entry_debit"])) \
                          * p.get("contracts", 1) * 100
                    pnl = f"  P&L ${raw:+.0f}"
                _emit_log(
                    f"  ✓ CLOSED  {sym:6}  {p.get('exit_reason','?')}{pnl}"
                )
        _emit_log("  Morning routine complete.")
    except Exception as e:
        _emit_log(f"Daily morning error: {e}", level="ERROR")


SCHEDULER_INTERVAL_SEC      = 15   # nominal cadence
SCHEDULER_STALE_THRESHOLD_S = 120  # supervisor respawns if heartbeat older than this

# Generation counter so a respawn supersedes any zombie scheduler greenlet
# that wakes up later — the older greenlet sees a generation mismatch on
# its next iteration and self-retires instead of running in parallel.
_scheduler_generation      = 0
_scheduler_generation_lock = threading.Lock()


def _scheduler_supervisor():
    """Detect a dead/wedged scheduler greenlet and respawn it.

    eventlet has known greenlet-starvation edge cases — a tick body that
    triggers GreenletExit / SystemExit (which inherit from BaseException, NOT
    Exception) can kill the scheduler silently, even with a try/except
    around every reasonable error. This watchdog detects a stale heartbeat
    and starts a fresh scheduler greenlet.

    The scheduler is idempotent on a same-day restart: session firing
    checks `state["sessions"][sym]` first, EOD review uses
    `eod_fired_on != today`, etc. A respawn doesn't double-fire.
    """
    import time as _time
    last_respawn = 0.0
    while True:
        socketio.sleep(60)
        age = heartbeat_age("scheduler")
        if age == float("inf"):
            continue   # never started yet; let the initial spawn run
        if age > SCHEDULER_STALE_THRESHOLD_S and (_time.monotonic() - last_respawn) > 300:
            log.error(
                f"Scheduler heartbeat {age:.0f}s stale — respawning greenlet "
                f"(threshold={SCHEDULER_STALE_THRESHOLD_S}s)"
            )
            try:
                trader.log_failure("watchdog_restart",
                                   f"Scheduler stale {age:.0f}s — respawning",
                                   {"threshold_s": SCHEDULER_STALE_THRESHOLD_S})
            except Exception:
                pass
            socketio.start_background_task(scheduler)
            last_respawn = _time.monotonic()


_reconcile_state = {"last": 0.0}
RECONCILE_INTERVAL_SEC = 300     # OB-4: run reconciliation every 5 min
STALE_ORDER_MINUTES    = 10      # cancel an order left unfilled longer than this


def _reconcile_orders_positions() -> None:
    """OB-4 — state↔broker reconciliation (the gap that left a stale AMZN order open ~24h).
    (1) Cancel OPEN orders that have been unfilled > STALE_ORDER_MINUTES — restores the
        FILL_TIMEOUT intent that didn't fire. (2) ALERT (don't auto-delete) on phantom daily
        positions: marked open/pending but the underlying isn't in the live account.
    Conservative + idempotent; never raises into the scheduler."""
    c = getattr(trader, "TRADING_CLIENT", None)
    if c is None:
        return
    import datetime as _dt
    # 1) cancel stale unfilled orders
    try:
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus
        now = _dt.datetime.now(_dt.timezone.utc)
        for o in c.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN)):
            try:
                age_min = (now - o.created_at).total_seconds() / 60.0
                if float(o.filled_qty or 0) == 0 and age_min > STALE_ORDER_MINUTES:
                    c.cancel_order_by_id(o.id)
                    _emit_log(f"⚠ RECONCILE: cancelled stale unfilled order {o.symbol} "
                              f"({age_min:.0f}m old — fill timeout didn't fire)", level="WARNING")
            except Exception as e:
                log.debug(f"reconcile order {getattr(o,'id','?')}: {e}")
    except Exception as e:
        log.debug(f"reconcile orders: {e}")
    # 2) alert on phantom daily positions (state says held, broker doesn't)
    try:
        acct_syms = {p["sym"].upper() for p in _account_equity_positions()} \
                    | {o["sym"].upper() for o in _account_option_positions()}
        for p in dtrad._load_positions():
            if p.get("status") in ("open", "pending") and str(p.get("sym", "")).upper() not in acct_syms:
                _emit_log(f"⚠ RECONCILE: phantom — {p.get('sym')} is '{p.get('status')}' in state but "
                          f"NOT in the broker account (no fill); needs cleanup", level="WARNING")
    except Exception as e:
        log.debug(f"reconcile positions: {e}")


def scheduler():
    """Background task: auto-start all-day sessions at 9:30 ET on weekdays,
    fire end-of-day learning review at 15:35 ET, and run the Connors RSI(2)
    daily-bar strategy EOD/morning routines. Also refreshes the Screener tab
    every 90s during market hours.

    Reliability hardening:
      • Generation check: if a supervisor has respawned a newer instance,
        any zombie that wakes up later sees the mismatch and self-retires.
      • Outer try/except BaseException so even non-Exception exits (eventlet
        GreenletExit, SystemExit) get logged before the loop can die.
      • Catch-up deadline sleep: we sleep until `next_tick`, NOT for a fixed
        15s. If a tick body took 20s, the next sleep is 0s — cadence
        catches up automatically.
    """
    import time as _time

    global _scheduler_generation
    with _scheduler_generation_lock:
        _scheduler_generation += 1
        my_gen = _scheduler_generation
    log.info(f"Scheduler started (generation {my_gen})")

    session_fired_on       = None
    eod_fired_on           = None
    daily_eod_fired_on     = None
    daily_morning_fired_on = None
    _screener_last_refresh = 0.0

    next_tick = _time.monotonic() + SCHEDULER_INTERVAL_SEC

    while True:
        # Generation check — a zombie that wakes after the supervisor has
        # respawned us should self-retire so we don't double-fire EOD etc.
        with _scheduler_generation_lock:
            if my_gen != _scheduler_generation:
                log.info(f"Scheduler gen {my_gen} retiring (current gen {_scheduler_generation})")
                return

        # Catch-up sleep — never drift permanently behind real time
        sleep_for = max(0.1, next_tick - _time.monotonic())
        socketio.sleep(sleep_for)
        next_tick = _time.monotonic() + SCHEDULER_INTERVAL_SEC
        _beat("scheduler")

        try:
            now = datetime.now(ET)

            if now.weekday() > 4:   # skip weekends
                continue

            with _state_lock:
                if not state["logged_in"]:
                    continue
                auto_sched_on = state["auto_schedule"]

            today = now.date()
            sh, sm = SESSION_AUTO_START  # 9:30 ET
            end_h, end_m = 15, 45        # sessions end at 15:45 ET
            market_open = (now.hour, now.minute) >= (sh, sm)
            market_open = market_open and (now.hour, now.minute) < (end_h, end_m)

            # Per-symbol intraday session launching is the heaviest work the
            # scheduler does (25 symbols × yfinance + Alpaca + indicator calcs).
            # It runs ONLY when auto_schedule is on. The screener auto-refresh
            # + auto-execute path below runs regardless of auto_schedule so
            # the headless options trading path still works when the (unproven)
            # ORB/VWAP per-symbol sessions are disabled.
            if auto_sched_on and market_open:
                with _state_lock:
                    missing = [s for s in _SYMBOLS_ORDERED if not state["sessions"].get(s, False)]
                if missing:
                    if session_fired_on != today:
                        session_fired_on = today
                        log.info(f"Auto-scheduler: starting all-day sessions for {missing}")
                    else:
                        log.info(f"Auto-scheduler: retrying missing sessions: {missing}")
                    for sym in missing:
                        _launch_session(sym)

            # EOD learning review — fires once at 15:35 ET after all sessions have ended
            if (now.hour, now.minute) == (EOD_REVIEW_HOUR, EOD_REVIEW_MINUTE) and eod_fired_on != today:
                eod_fired_on = today
                with _state_lock:
                    trades_snapshot = list(state["trades_today"])
                socketio.start_background_task(_run_eod_review, trades_snapshot)

            # Daily strategy: morning fill-confirm at 9:35 ET
            if (now.hour * 60 + now.minute) >= (DAILY_MORNING_HOUR * 60 + DAILY_MORNING_MINUTE) \
                    and daily_morning_fired_on != today:
                daily_morning_fired_on = today
                socketio.start_background_task(_run_daily_morning)

            # Daily strategy: EOD routine at 4:10 PM ET
            if (now.hour * 60 + now.minute) >= (DAILY_EOD_HOUR * 60 + DAILY_EOD_MINUTE) \
                    and daily_eod_fired_on != today:
                daily_eod_fired_on = today
                socketio.start_background_task(_run_daily_eod)

            # OB-4 reconciliation: cancel stale unfilled orders + alert on phantom positions
            if _time.monotonic() - _reconcile_state["last"] >= RECONCILE_INTERVAL_SEC:
                _reconcile_state["last"] = _time.monotonic()
                socketio.start_background_task(_reconcile_orders_positions)
                socketio.start_background_task(_run_eod_analysis)   # EOD analysis + learning

            # Screener auto-refresh — every 90s during market hours
            _screener_age = _time.time() - _screener_last_refresh
            if market_open and _screener_age >= screener.CACHE_TTL_MARKET:
                _screener_last_refresh = _time.time()
                socketio.start_background_task(_refresh_screener_bg)

            # Autonomous dual-engine — SHADOW (Phase 5b). Default OFF
            # (auto_engine.DUAL_ENGINE_ENABLED). When on, logs what it WOULD
            # trade every ~5 min during market hours; places no orders.
            if market_open and auto_engine.DUAL_ENGINE_ENABLED:
                global _shadow_last_run
                if _time.time() - _shadow_last_run >= 300:
                    _shadow_last_run = _time.time()
                    socketio.start_background_task(_run_shadow_engine)

        except SystemExit:
            # SystemExit is intentional shutdown — re-raise so eventlet hub
            # can clean up properly. Don't swallow this.
            raise
        except BaseException as e:
            # Catch BaseException (not just Exception) so eventlet's
            # GreenletExit and other non-Exception escapes get logged
            # instead of silently killing the loop. KeyboardInterrupt is
            # mostly irrelevant under launchd but caught for safety.
            log.error(
                f"Scheduler tick {type(e).__name__}: {e} — continuing",
                exc_info=True,
            )
            try:
                trader.log_failure("scheduler_crash",
                                   f"{type(e).__name__}: {e}",
                                   {"generation": my_gen})
            except Exception:
                pass


@socketio.on("daily_status")
@require_auth
def on_daily_status():
    """Emit current Connors RSI(2) daily strategy position list to caller."""
    try:
        positions = dtrad._load_positions()
        socketio.emit("daily_positions", {"positions": positions}, to=request.sid)
    except Exception as e:
        log.warning(f"daily_status failed: {e}")


# ── Screener tab ──────────────────────────────────────────────────────────────
_screener_refresh_lock = threading.Lock()

from config import MAX_AUTO_EXEC_PER_DAY   # AH-2: hard cap on auto orders/day (single source)

# Merged-picks feature flag. When ON, the screener becomes ONE KB-ranked pick list
# (data["picks"]) that drives the display AND both auto-exec lanes — so "what's shown
# == what's traded". When OFF (default), the legacy dt/options two-list flow is
# byte-for-byte preserved. Gated per CLAUDE.md trading safety rails; flip on only
# after the Phase-5 backtest A/B shows no regression.
MERGED_PICKS_ENABLED = True   # enabled 2026-06-04 (operator). Invariant: merged trades a
# SUBSET of legacy (one order per symbol via its route) under the same KB gates/caps, so
# it can't trade MORE or riskier than the legacy two-list flow. Full OOS backtest A/B is
# still pending (blocked on the Polygon pull). Revert to False to fall back instantly.
_PICK_ETF_SYMS = set(ETFS_TRADE) | set(ETFS_HEDGE)   # for the instrument-priority tiebreak


def _annotate_kb(data: dict, options_only: bool = False) -> None:
    """Attach a KB-principles match score to every screener row (in place).

    Adds row['kb_match'] (0-100%) + row['kb_principles'] {matched,failed} so the
    UI can show a Confidence % column and the executor can gate on KB alignment.

    options_only=True (CR-4): the post-liquidity re-score only needs to revisit OPTION
    rows (liquidity affects only option scores); skipping the unchanged stock rows
    avoids re-scoring them twice every refresh.
    """
    try:
        with _state_lock:
            vix = state.get("vix")
    except Exception:
        vix = None
    for o in data.get("options", []):
        try:
            sc = kb_principles.score_option_candidate(o, vix=vix)
            o["kb_match"] = sc["pct"]
            o["kb_principles"] = {"matched": sc["matched"], "failed": sc["failed"]}
            # operator 2026-06-02: a perfect 100% KB-match is a BUY regardless of
            # is_top/⭐ ranking. (§9 liquidity is relaxed separately, so this fills.)
            if sc["pct"] >= 100 and o.get("action") != "✅ BUY":
                o["action"] = "✅ BUY"
                o["kb100_upgrade"] = True
        except Exception:
            o["kb_match"] = None
    if options_only:
        return
    for r in data.get("dt", []):
        try:
            sc = kb_principles.score_stock_candidate(r, vix=vix)
            r["kb_match"] = sc["pct"]
            r["kb_principles"] = {"matched": sc["matched"], "failed": sc["failed"]}
            if sc["pct"] >= 100 and r.get("action") != "✅ BUY":
                r["action"] = "✅ BUY"
                r["kb100_upgrade"] = True
        except Exception:
            r["kb_match"] = None


# §9 liquidity pre-check cache for the screener ranking (#22). OI/spread don't move
# fast — cache 10 min and only check ✅ BUY option rows to limit option-chain fetches.
_liquidity_cache: dict = {}
_LIQUIDITY_TTL_SEC = 600


def _annotate_liquidity(data: dict) -> None:
    """Demote option rows whose ATM contract fails the KB §9 liquidity gate, so a
    'Top Pick / ✅ BUY' is never something the executor will later reject for OI or
    bid-ask (#22 — the HOOD/CVNA class). Fail-open: only demote on a CONFIRMED
    illiquid result; an unknown (fetch failed) leaves the row unchanged."""
    now = time.monotonic()
    for o in data.get("options", []):
        if o.get("action") != "✅ BUY":
            continue
        sym, expiry = (o.get("sym") or "").upper(), (o.get("expiry") or "")
        if not sym or not expiry:
            continue
        key = (sym, expiry, o.get("opt_type", "Call"))
        cached = _liquidity_cache.get(key)
        if cached and now - cached[1] < _LIQUIDITY_TTL_SEC:
            res = cached[0]
        else:
            res = screener_executor.liquidity_check(sym, expiry, o.get("opt_type", "Call"))
            _liquidity_cache[key] = (res, now)
        o["liquidity"] = res
        if res.get("ok") is False:               # confirmed illiquid → not tradable
            o["action"] = "⚠ Illiquid"
            if str(o.get("badge", "")).startswith("⭐"):
                o["badge"] = "📈 Valid"
            o["confidence"] = (f"⚠ illiquid — {res.get('reason', '§9')} (won't fill) · "
                               + o.get("confidence", ""))[:200]


_SCREENED_TODAY: set = set()   # (date, sym, kind) dedup so each name logs once/day


def _log_screened(data: dict) -> None:
    """Track every ✅ BUY-rated screener item to a daily file for EOD analysis —
    so we can review what we screened-as-buyable but DIDN'T buy (operator). One row
    per (symbol, kind) per day, with KB%, action, and whether we held it."""
    import datetime as _dt, json as _j
    today = _dt.date.today().isoformat()
    path = os.path.expanduser(f"~/.spy_trader/screened_{today}.jsonl")
    rows = ([("option", o) for o in data.get("options", [])]
            + [("stock", r) for r in data.get("dt", [])])
    new = []
    for kind, r in rows:
        if r.get("action") != "✅ BUY":
            continue
        sym = (r.get("sym") or "").upper()
        keyd = (today, sym, kind)
        if not sym or keyd in _SCREENED_TODAY:
            continue
        _SCREENED_TODAY.add(keyd)
        new.append({"ts": _dt.datetime.now().isoformat(), "sym": sym, "kind": kind,
                    "kb_match": r.get("kb_match"), "held": bool(r.get("held")),
                    "structure": r.get("structure"), "dir_pct": r.get("dir_pct"),
                    "pf": r.get("pf"), "kb100": bool(r.get("kb100_upgrade"))})
    if new:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "a") as fh:
                for n in new:
                    fh.write(_j.dumps(n) + "\n")
        except Exception as e:
            log.debug(f"log_screened: {e}")


def _sort_screener_by_kb(data: dict) -> None:
    """Sort screener rows by KB-match desc (operator). BUY rows first, then by KB%,
    then held rows after (already owned). In place."""
    def key(r):
        # PRIMARY: KB match desc (operator 2026-06-04); held-last + BUY-first break ties.
        return (-(r.get("kb_match") or 0),
                1 if r.get("held") else 0,
                0 if r.get("action") == "✅ BUY" else 1)
    for k in ("options", "dt"):
        if isinstance(data.get(k), list):
            data[k] = sorted(data[k], key=key)


def _build_picks(data: dict, positions: list, vix: float | None = None) -> list:
    """Merge the screener's stock (dt) + option rows into ONE KB-ranked pick list —
    the single source of truth for the display AND both auto-exec lanes, so "what's
    shown == what's traded" (operator: "the screener and picks should be the same").

    Each unique underlying collapses to ONE pick that is ROUTED to stock or option
    (router.route_for_pick, KB §5/§2). The canonical `kb_match` is the score of the
    ROUTED instrument, so the displayed % equals the % the executor gates on. Picks
    are lean (display + routing); the auto-exec lanes map a pick back to its original
    dt/option row by symbol. Pure aside from a single equity read (kept OUTSIDE
    _state_lock per the lock-contention gotcha)."""
    import router as _router
    from risk_brain import RiskBrain

    opt_by, stk_by = {}, {}
    for o in data.get("options", []):
        s = (o.get("sym") or "").upper()
        if s and s not in opt_by:
            opt_by[s] = o
    for r in data.get("dt", []):
        s = (r.get("sym") or "").upper()
        if s and s not in stk_by:
            stk_by[s] = r

    # Equity for routing/sizing. Read the CHEAP state snapshot FIRST (CR-4 — avoids a
    # blocking account_value() network call on the refresh greenlet that can wedge the
    # eventlet hub); fall back to a live read only if the snapshot is empty; route
    # display-only (rb=None) only when BOTH are 0 so a transient read can't silently
    # halt all auto-exec (CR-2).
    equity = 0.0
    try:
        with _state_lock:
            equity = float(state.get("account_value") or 0.0)
    except Exception:
        equity = 0.0
    if equity <= 0:
        try:
            equity = float(trader.account_value() or 0.0)
        except Exception:
            equity = 0.0
    rb = RiskBrain(total_equity=equity) if equity > 0 else None

    picks = []
    for sym in (set(opt_by) | set(stk_by)):
        srow, orow = stk_by.get(sym), opt_by.get(sym)
        route, structure, route_reason = "skip", None, "no equity read — display only"
        if rb is not None:
            try:
                dec = _router.route_for_pick(srow, orow, rb, vix=vix)
                route, structure, route_reason = dec.route, dec.structure, dec.reason
            except Exception as e:
                route, route_reason = "skip", f"route error: {e}"

        # canonical fields from the ROUTED instrument (fall back to whatever row exists)
        if route == "options" and orow is not None:
            base, action = orow, orow.get("action")
        elif route == "stocks" and srow is not None:
            base = srow
            action = (srow.get("action")
                      or ("✅ BUY" if (srow.get("valid") and srow.get("is_top")) else "⚠ WATCH"))
        else:
            base, action = (orow or srow or {}), "⚠ WATCH"

        picks.append({
            "sym": sym,
            "route": route,                       # "stocks" | "options" | "skip"
            "structure": structure,
            "route_reason": route_reason,
            "kb_match": base.get("kb_match"),
            "kb_principles": base.get("kb_principles", {}),
            "action": action,
            "source": (orow or {}).get("source") or (srow or {}).get("strategy") or (srow or {}).get("setup"),
            "dir_pct": (orow or {}).get("dir_pct") if orow else (srow or {}).get("bt_dir"),
            "pf": (orow or {}).get("pf") if orow else (srow or {}).get("bt_pf"),
            "expiry": (orow or {}).get("expiry"),
            "opt_type": (orow or {}).get("opt_type"),
            "max_risk": (orow or {}).get("max_risk"),
            "price": (srow or {}).get("price"),
            "held": bool(base.get("held")),
            "exit_plan": base.get("exit_plan"),
            "reason": base.get("reason"),
            "strategy": base.get("strategy") or base.get("setup"),
            # confidence-calibration: ONE kb_match-driven label on every pick (both routes)
            "confidence": (f"KB {base.get('kb_match')}% · {route}"
                           if base.get("kb_match") is not None else route),
        })

    def _src_priority(p):   # Connors "⭐ Proven" wins ties
        s = str(p.get("source") or "")
        return 0 if ("Connors" in s or "Proven" in s) else 1

    def _instr_pref(p):     # instrument-priority: options favor ETFs; shares favor stocks
        is_etf = p["sym"] in _PICK_ETF_SYMS
        if p["route"] == "options":
            return 0 if is_etf else 1
        if p["route"] == "stocks":
            return 0 if not is_etf else 1
        return 2

    picks.sort(key=lambda p: (
        -(p.get("kb_match") or 0),                 # PRIMARY: KB match desc (operator 2026-06-04)
        1 if p.get("held") else 0,                 # held after non-held on ties
        0 if p.get("action") == "✅ BUY" else 1,   # BUY before WATCH on ties
        _src_priority(p),
        _instr_pref(p),
        -(float(p.get("dir_pct") or 0)),
    ))
    return picks


def _position_exit_plan(pos: dict) -> dict:
    """Compute the exit plan for a held daily position, for UI display.
    Returns {stop, target, trigger, instrument, entry, status}."""
    instr = pos.get("instrument", "shares")
    entry = pos.get("entry_price")
    trigger = "RSI(2) > 70 → sell next open (§19)"
    if instr == "options":
        debit = pos.get("entry_debit") or pos.get("est_debit")
        width = pos.get("width")
        structure = pos.get("structure", "")
        stop = pos.get("stop_debit")
        if stop is None and debit:
            stop = round(debit * 0.50, 2)   # OPT_STOP_PCT = 50% of premium (§9)
        # target: 80% of max profit on a spread (§24), else +80% of premium
        if width and debit and "spread" in structure:
            target = round(debit + 0.80 * (width - debit), 2)   # 80% of max
        elif debit:
            target = round(debit * 1.80, 2)
        else:
            target = None
        return {"instrument": "options", "entry": debit,
                "stop": stop, "target": target,
                "trigger": "RSI(2)>70 · +80% profit · D-2 earnings (§23/§24)",
                "unit": "$ debit", "status": pos.get("status")}
    # shares
    return {"instrument": "shares", "entry": entry,
            "stop": pos.get("stop_price"),
            "target": None,   # shares exit on the signal, no fixed target
            "trigger": trigger, "unit": "$ price", "status": pos.get("status")}


def _annotate_held_exits(data: dict, positions: list) -> None:
    """Mark screener rows for symbols we HOLD and attach their exit plan (in place).
    So the screener shows OUR EXITS for the stocks/options we bought (operator req)."""
    # Held by instrument-appropriate source:
    #  • option rows  → only an actual OPTION/daily position (holding HOOD *shares*
    #    must NOT mark the HOOD *option* row held — that would hide its Execute btn).
    #  • stock rows   → daily-strategy positions OR any equity holding in the account.
    held_opt:    dict[str, dict] = {}
    held_shares: dict[str, dict] = {}
    for p in positions or []:
        if p.get("status") in ("open", "pending", "signal"):
            sym = str(p.get("sym", "")).upper()
            plan = _position_exit_plan(p)
            (held_opt if p.get("instrument") == "options" else held_shares)[sym] = plan
    try:
        eng_by = {p["sym"]: p for p in auto_engine.positions_snapshot()}
        for ap in _account_equity_positions():           # account equity → shares only
            sym = ap["sym"]
            if sym in held_shares:
                continue
            e = eng_by.get(sym) or {}
            held_shares[sym] = {
                "instrument": "shares", "qty": ap.get("qty"), "entry": ap.get("entry"),
                "stop": e.get("stop"), "target": None,
                "trigger": "dynamic trail · 21d cap" if e else "held",
                "unit": "$ price", "status": "open",
            }
    except Exception as _e:
        log.debug(f"held-from-account: {_e}")

    # account OPTION positions → mark the option screener row for that underlying as
    # held (we already own the option), so it shows 🔵 HELD instead of a BUY button.
    try:
        for op in _account_option_positions():
            u = (op.get("sym") or "").upper()
            if u and u not in held_opt:
                held_opt[u] = {
                    "instrument": "options", "qty": op.get("qty"),
                    "entry": op.get("entry"), "stop": None, "target": None,
                    "trigger": "±20% take-profit / stop", "unit": "$ debit", "status": "open",
                }
    except Exception as _e:
        log.debug(f"held-from-account-options: {_e}")

    for row in data.get("options", []):
        plan = held_opt.get(str(row.get("sym", "")).upper())
        row["held"] = plan is not None
        if plan:
            row["exit_plan"] = plan
    for row in data.get("dt", []):
        sym = str(row.get("sym", "")).upper()
        plan = held_shares.get(sym) or held_opt.get(sym)
        row["held"] = plan is not None
        if plan:
            row["exit_plan"] = plan


def _kb_and_debate_gate(row: dict) -> tuple[bool, str]:
    """Pre-trade gate: a trade is only taken if it (1) clears the KB-principles
    floor AND (2) passes the bull/bear debate gate (when enabled).

    Returns (allowed, reason). Implements the operator directive: "always take
    trades using the knowledge base / maximum principles."
    """
    sym = str(row.get("sym", "")).upper()
    # 1) KB-principles floor
    try:
        with _state_lock:
            vix = state.get("vix")
        sc = kb_principles.score_option_candidate(row, vix=vix)
    except Exception as e:
        return False, f"KB scoring error: {e}"
    if sc["pct"] < kb_principles.KB_MATCH_MIN:
        miss = "; ".join(sc["failed"][:3])
        return False, (f"KB match {sc['pct']}% < {kb_principles.KB_MATCH_MIN}% floor "
                       f"— failed: {miss}")
    # 2) Bull/bear debate gate — ONLY when the full intraday technical indicator
    #    set is present. Screener picks carry backtested-edge metrics (dir%/pf/
    #    ivr), NOT price/RSI/VWAP/EMA/ATR, so the debate can't evaluate them and
    #    would reject everything for "missing data". The KB-principles gate above
    #    is the data-matched filter for screener picks; the debate applies to the
    #    intraday signal path (which carries full indicators).
    has_tech = bool(row.get("price")) and any(
        row.get(k) is not None for k in ("rsi14", "rsi", "vwap_diff", "atr"))
    if trader.DEBATE_ENABLED and has_tech:
        direction = "bull" if "Call" in str(row.get("opt_type", "")) \
            or "▲" in str(row.get("direction", "")) else "bear"
        indicators = {
            "price": row.get("price"), "rsi": row.get("rsi14") or row.get("rsi"),
            "vwap_diff": row.get("vwap_diff"), "atr": row.get("atr"),
            "dir_pct": row.get("dir_pct"), "pf": row.get("pf"),
            "ivr": row.get("ivr"), "structure": row.get("structure"),
            "signal": row.get("signal"), "kb_match": sc["pct"],
        }
        try:
            proceed, conf, summary = debate_mod.run_debate(sym, direction, indicators)
            if not proceed:
                return False, f"Debate gate suppressed (conf {conf:.2f}): {summary}"
        except Exception as e:
            return False, f"Debate gate error (failing closed): {e}"
        return True, f"KB match {sc['pct']}% ✓ + debate ✓"
    return True, f"KB match {sc['pct']}% ✓ (debate n/a — no intraday indicators)"


def _auto_exec_options(data: dict) -> None:
    """After each screener refresh, auto-place BUY-rated options rows if armed.

    Safety rules:
      · Only fires if auto_execute_options is True AND market is open
      · At most MAX_AUTO_EXEC_PER_DAY orders per calendar day (hard cap)
      · Dedup set (_auto_exec_today) — persisted to disk; survives restart
      · DAILY_LOSS_LIMIT_PCT circuit breaker — halts auto-exec on drawdown
      · Each order respects the existing KB §4 $400 max-risk budget
      · dry_run flag is honoured — if True, no real order is placed
    """
    global _auto_exec_today, _auto_exec_filled, _auto_exec_date
    global _auto_exec_stock_today, _auto_exec_stock_filled, _auto_exec_attempts
    global _session_start_equity, _session_start_date

    with _state_lock:
        armed  = state.get("auto_execute_options", False)
        logged = state["logged_in"]
        dry    = state["dry_run"]
    if not armed or not logged:
        return
    if not screener._is_market_open():
        return

    today = datetime.now(ET).strftime("%Y-%m-%d")

    # ── Daily-rollover housekeeping (dedup + circuit-breaker baseline) ──
    with _auto_exec_lock:
        if _auto_exec_date != today:
            _auto_exec_today  = set()
            _auto_exec_filled = set()
            _auto_exec_stock_today  = set()   # stock lane shares the date key
            _auto_exec_stock_filled = set()
            _auto_exec_attempts = {}          # reset per-symbol attempt counters
            _auto_exec_date   = today
            _save_auto_exec_state()

    if _session_start_date != today:
        try:
            _session_start_equity = float(trader.account_value() or 0.0)
            _session_start_date   = today
            log.info(f"[auto-exec] Day baseline equity: ${_session_start_equity:,.2f}")
        except Exception as e:
            log.warning(f"[auto-exec] Could not snapshot start equity: {e}")
            _session_start_equity = 0.0

    # ── Circuit breaker: halt if today's drawdown exceeds DAILY_LOSS_LIMIT_PCT ──
    if _session_start_equity > 0:
        try:
            cur_eq = float(trader.account_value() or 0.0)
            # Guard against a failed/garbage equity fetch. account_value() returns
            # 0 / None on a transient API or DNS hiccup; a real account holding cash
            # + long positions cannot read $0, and given the risk caps a true
            # single-day drop past -50% is impossible. Treat such readings as bad
            # DATA, not a real loss — skip the check rather than false-halting.
            global _loss_breach_count
            dd_pct = (cur_eq - _session_start_equity) / _session_start_equity * 100
            if cur_eq <= 0 or dd_pct <= -50.0:
                # Implausible reading (failed fetch): don't count it either way.
                log.warning(f"[auto-exec] ignoring implausible equity reading "
                            f"${cur_eq:,.2f} (dd {dd_pct:+.1f}%) — likely a failed "
                            f"fetch, not a real loss; circuit breaker not tripped")
            elif dd_pct <= -DAILY_LOSS_LIMIT_PCT:
                # Debounce: require LOSS_BREACH_CONFIRM consecutive breaching reads
                # so a single flaky equity fetch can't disarm a healthy account.
                _loss_breach_count += 1
                if _loss_breach_count >= LOSS_BREACH_CONFIRM:
                    _alert("AUTO-EXEC HALTED — daily loss limit breached",
                           f"P&L {dd_pct:+.2f}% < -{DAILY_LOSS_LIMIT_PCT:.1f}% "
                           f"(equity ${cur_eq:,.2f} vs start ${_session_start_equity:,.2f})",
                           level="WARNING")   # OB-2: push so the operator is told, not just logged
                    with _state_lock:
                        state["auto_execute_options"] = False
                    emit_state()
                    return
                log.warning(f"[auto-exec] loss-limit breach {_loss_breach_count}/"
                            f"{LOSS_BREACH_CONFIRM} (dd {dd_pct:+.1f}%, equity "
                            f"${cur_eq:,.2f}) — not halting until confirmed")
            else:
                _loss_breach_count = 0          # healthy reading resets the streak
        except Exception as e:
            log.warning(f"[auto-exec] equity check failed: {e}")

    # Boundaries (operator 2026-06-02): max 3 concurrent option positions, and only
    # ONE option per underlying (no doubling up). Counted from the live account.
    import re as _re
    held_opt_underlyings = set()
    try:
        _c = getattr(trader, "TRADING_CLIENT", None)
        if _c is not None:
            for _p in _c.get_all_positions():
                if getattr(getattr(_p, "asset_class", None), "value", "") == "us_option":
                    _m = _re.match(r"^([A-Z]+)\d", _p.symbol)
                    held_opt_underlyings.add(_m.group(1) if _m else _p.symbol)
    except Exception as _e:
        log.debug(f"option-cap fetch: {_e}")

    # Merged-picks: trade only option-ROUTED picks, in pick-rank order, mapped back
    # to their option rows. Flag off → legacy full options list. Either way the
    # per-row gates/caps below are unchanged.
    if MERGED_PICKS_ENABLED and isinstance(data.get("picks"), list):
        _opt_by = {(x.get("sym") or "").upper(): x for x in data.get("options", [])}
        rows = [_opt_by[p["sym"]] for p in data["picks"]
                if p.get("route") == "options" and p.get("sym") in _opt_by]
    else:
        rows = data.get("options", [])
    for o in rows:
        with _auto_exec_lock:
            count_today = len(_auto_exec_filled)   # cap counts FILLED trades, not attempts
        if count_today >= MAX_AUTO_EXEC_PER_DAY:
            log.info(f"[auto-exec] Daily cap ({MAX_AUTO_EXEC_PER_DAY} filled) reached "
                     f"— skipping remaining signals")
            break
        if len(held_opt_underlyings) >= screener_executor.OPT_MAX_OPEN:
            log.info(f"[auto-exec] max {screener_executor.OPT_MAX_OPEN} option positions "
                     f"open — skipping remaining")
            break
        if o.get("action") != "✅ BUY":
            continue
        sym = o.get("sym", "").upper()
        if not sym:
            continue
        if sym in held_opt_underlyings:        # one option per underlying max
            continue
        # #36: stop retrying a symbol that already failed to fill twice today
        with _auto_exec_lock:
            if _auto_exec_attempts.get(sym, 0) >= MAX_SYMBOL_ATTEMPTS_PER_DAY:
                continue

        # ── KB-principles + debate gate (operator directive) ──────────────────
        allowed, reason = _kb_and_debate_gate(o)
        if not allowed:
            _emit_log(f"AUTO-EXEC ⛔ {sym} blocked by gate — {reason}", level="INFO")
            continue
        # log-kb-principle TODO: print the FULL KB principles satisfied, not just §#
        _matched = (o.get("kb_principles") or {}).get("matched") or []
        if _matched:
            _emit_log(f"AUTO-EXEC ✓ {sym} KB: " + " · ".join(_matched[:4]), level="INFO")

        with _auto_exec_lock:
            if sym in _auto_exec_today:
                continue
            # Mark + persist BEFORE the API call so a slow/crashing request
            # cannot leave the dedup set inconsistent with what was sent.
            _auto_exec_today.add(sym)
            _save_auto_exec_state()

        payload = {
            "sym":       sym,
            "structure": o.get("structure", "ATM Call"),
            "expiry":    o.get("expiry", ""),
            "opt_type":  o.get("opt_type", "Call"),
            # EOD fix 2026-06-04: align the enforced max-risk to the $600 ceiling (was the
            # stale $400, which is what produced the §4 "relaxation" noise). Equal-dollar
            # sizing keeps total risk ≤ $600, so enforce-max-risk passes cleanly — no relax.
            "max_risk":  screener_executor.OPT_HARD_MAX_USD,
        }
        log.info(f"[auto-exec] {sym}  {payload['structure']}  "
                 f"{payload['expiry']}  dry={dry}")
        try:
            result = screener_executor.execute_screener_option(payload, dry_run=dry)
            socketio.emit("screener_order_result", result)
            level = "INFO" if result.get("success") else "WARNING"
            _emit_log(
                f"AUTO-EXEC {'✅' if result.get('success') else '⚠️'}  "
                f"{sym}  {payload['structure']}  {result.get('message', '')}",
                level=level
            )
            # ── Count toward the N/3 daily cap ONLY on an actual fill ──────────
            # (operator: "until it is filled we don't want this to change"). A
            # placed-but-canceled/rejected/unfilled order leaves the cap counter
            # untouched. Dedup (_auto_exec_today) still prevents re-attempting the
            # symbol today; this only governs what the N/3 counter reflects.
            _filled = (result.get("long_fill_status") in ("filled", "partial")
                       or int(result.get("long_filled_qty", 0) or 0) > 0)
            if _filled:
                with _auto_exec_lock:
                    _auto_exec_filled.add(sym)
                    _auto_exec_attempts.pop(sym, None)   # success clears the counter
                    _save_auto_exec_state()
                log.info(f"[auto-exec] {sym} FILLED — counts toward daily cap "
                         f"({len(_auto_exec_filled)}/{MAX_AUTO_EXEC_PER_DAY})")
            else:
                # #36: record the failed attempt so we stop retrying after the cap
                with _auto_exec_lock:
                    _auto_exec_attempts[sym] = _auto_exec_attempts.get(sym, 0) + 1
                    _n = _auto_exec_attempts[sym]
                    _save_auto_exec_state()
                if _n >= MAX_SYMBOL_ATTEMPTS_PER_DAY:
                    _emit_log(f"AUTO-EXEC ⏭ {sym} skipped for today "
                              f"({_n} failed attempts)", level="INFO")
            # ── Dedup-on-reject release ──────────────────────────────────────
            # If the executor returned failure AND no order was actually
            # submitted (no long_order_id), the trade took zero capital and
            # zero risk. Releasing the symbol from the dedup set is safe and
            # frees the daily-cap slot for other candidates. We only KEEP the
            # dedup mark when at least one order id exists — that means real
            # Alpaca exposure (possibly partial fill, rollback in progress,
            # or full success).
            no_order_placed = (
                not result.get("success")
                and not result.get("long_order_id")
                and not result.get("short_order_id")
            )
            if no_order_placed:
                with _auto_exec_lock:
                    _auto_exec_today.discard(sym)
                    _save_auto_exec_state()
                log.info(f"[auto-exec] {sym} released from dedup "
                         f"(safety-gate rejection — no order placed)")
        except Exception as e:
            log.warning(f"[auto-exec] {sym} failed: {e}")
            # Defensive: same release on raised exception (no order took risk),
            # but count the attempt so a hard-failing name (e.g. ceiling) stops
            # being retried every cycle (#36).
            with _auto_exec_lock:
                _auto_exec_today.discard(sym)
                _auto_exec_attempts[sym] = _auto_exec_attempts.get(sym, 0) + 1
                _save_auto_exec_state()


def _auto_exec_stocks(data: dict) -> None:
    """Auto-buy 10 shares of strong screener STOCK rows — the shares analogue of
    _auto_exec_options (operator request). Same rails: armed toggle, market-open,
    KB-match gate, dedup (no re-attempt), and an N/3 cap that counts FILLED orders.
    Stocks are liquid, so there's no §9 option-liquidity gate here."""
    global _auto_exec_stock_today, _auto_exec_stock_filled, _auto_exec_date
    global _auto_exec_attempts

    with _state_lock:
        armed  = state.get("auto_execute_options", False)   # same Armed toggle
        logged = state["logged_in"]
        dry    = state["dry_run"]
        vix    = state.get("vix")
    if not armed or not logged:
        return
    if not screener._is_market_open():
        return

    today = datetime.now(ET).strftime("%Y-%m-%d")
    with _auto_exec_lock:
        if _auto_exec_date != today:
            # daily rollover is owned by _auto_exec_options; mirror for stocks
            _auto_exec_stock_today  = set()
            _auto_exec_stock_filled = set()

    import shares_executor
    # NOTE: the 3/day cap is OPTIONS-ONLY (operator). Stocks are not capped by a
    # daily count — the per-symbol dedup is the only limiter, so each strong name
    # is bought at most once/day, bounded by how many strong rows the screener has.
    # Merged-picks: trade only stock-ROUTED picks (a symbol routed to options is not
    # also bought as shares), in pick-rank order. Flag off → legacy full dt list.
    if MERGED_PICKS_ENABLED and isinstance(data.get("picks"), list):
        _stk_by = {(x.get("sym") or "").upper(): x for x in data.get("dt", [])}
        stock_rows = [_stk_by[p["sym"]] for p in data["picks"]
                      if p.get("route") == "stocks" and p.get("sym") in _stk_by]
    else:
        stock_rows = data.get("dt", [])
    for r in stock_rows:
        # Only strong, validated, top-ranked rows (the ⭐ + ✅ BUY ones).
        strong = (r.get("action") == "✅ BUY") or (r.get("valid") and r.get("is_top"))
        if not strong:
            continue
        sym = str(r.get("sym", "")).upper().strip()
        if not sym or not sym.replace(".", "").isalpha():
            continue
        with _auto_exec_lock:
            if sym in _auto_exec_stock_today:
                continue
            if _auto_exec_attempts.get(sym, 0) >= MAX_SYMBOL_ATTEMPTS_PER_DAY:
                continue   # #36: stop retrying a name that keeps failing to fill
        # KB-principles gate (REQ-004) — same floor the manual click enforces
        try:
            sc = kb_principles.score_stock_candidate(r, vix=vix)
        except Exception:
            continue
        if sc["pct"] < kb_principles.KB_MATCH_MIN:
            _emit_log(f"AUTO-BUY ⛔ {sym} blocked — KB match {sc['pct']}% "
                      f"< {kb_principles.KB_MATCH_MIN}%", level="INFO")
            continue
        # log-kb-principle TODO: print the FULL KB principles satisfied, not just §#
        if sc.get("matched"):
            _emit_log(f"AUTO-BUY ✓ {sym} KB: " + " · ".join(sc["matched"][:4]), level="INFO")
        # Equal-dollar sizing: ~$5000 per stock position (operator 2026-06-04)
        qty = _stock_qty_for(r.get("price"))
        if qty <= 0:
            _emit_log(f"AUTO-BUY ⛔ {sym} skipped — no usable price for $5000 sizing", level="INFO")
            with _auto_exec_lock:
                _auto_exec_stock_today.discard(sym)
            continue
        with _auto_exec_lock:
            _auto_exec_stock_today.add(sym)      # mark before the call (dedup)
            _save_auto_exec_state()
        try:
            res = shares_executor.buy(sym, qty, dry_run=dry)
            res["sym"] = sym
            res["message"] = (f"AUTO-BUY {qty} {sym} (~${qty*float(r.get('price') or 0):.0f})"
                              if res.get("success")
                              else res.get("message", "stock order failed")) + (" [dry]" if dry else "")
            socketio.emit("screener_order_result", res)
            _emit_log(f"AUTO-BUY {'✅' if res.get('success') else '⚠️'}  {res['message']}",
                      level="INFO" if res.get("success") else "WARNING")
            # Count toward the cap on a successful placement. A stock MARKET order
            # on paper fills reliably (the fill_price may just confirm a beat later),
            # so unlike a cancelable option spread, "accepted" == effectively filled.
            if res.get("success") and not res.get("dry_run"):
                with _auto_exec_lock:
                    _auto_exec_stock_filled.add(sym)
                    _save_auto_exec_state()
                log.info(f"[auto-buy] {sym} bought (10 sh) — "
                         f"{len(_auto_exec_stock_filled)} stock(s) today (uncapped)")
            elif not res.get("success"):
                with _auto_exec_lock:
                    _auto_exec_stock_today.discard(sym)   # no order — allow retry
                    _auto_exec_attempts[sym] = _auto_exec_attempts.get(sym, 0) + 1
                    _save_auto_exec_state()
        except Exception as e:
            log.warning(f"[auto-buy] {sym} failed: {e}")
            with _auto_exec_lock:
                _auto_exec_stock_today.discard(sym)
                _auto_exec_attempts[sym] = _auto_exec_attempts.get(sym, 0) + 1
                _save_auto_exec_state()


# Autonomous shadow-engine throttle (module-level; scheduler uses `global`)
_shadow_last_run = 0.0
_SHADOW_ETF_SET = set(ETFS_TRADE) | set(ETFS_HEDGE)


def _run_shadow_engine():
    """Run one autonomous cycle. In "execute" mode it places PAPER orders through
    all rails (regime-skip, sleeves/caps, dedup, concurrent cap); in "shadow" mode
    it only logs. PAPER-only by hard guard in shares_executor. Gated by
    DUAL_ENGINE_ENABLED + market open."""
    try:
        from universe import ALL as _UNI
        with _state_lock:
            equity = state.get("account_value") or 0.0
            logged = state["logged_in"]
        if not logged:
            return
        if equity <= 0:
            try:
                equity = float(trader.account_value() or 0.0)
            except Exception:
                equity = 0.0
        if equity <= 0:
            log.info("[auto-engine] no equity yet — cycle skipped")
            return
        # execute mode places real PAPER orders (dry_run=False); shadow logs only
        _dry = (auto_engine.DUAL_ENGINE_MODE != "execute")
        with _state_lock:
            _vix = state.get("vix")
        plan = auto_engine.run_cycle(equity, list(_UNI), _SHADOW_ETF_SET,
                                     enabled=True, dry_run=_dry, vix=_vix)
        if plan:
            socketio.emit("shadow_plan", {
                "mode": plan.get("mode"), "risk_on": plan.get("risk_on"),
                "planned": [
                    {"symbol": pt.signal.symbol, "strategy": pt.signal.strategy,
                     "route": pt.decision.route, "structure": pt.decision.structure,
                     "qty": pt.decision.qty, "cost": pt.decision.est_cost_usd,
                     "risk": pt.decision.est_risk_usd, "reason": pt.decision.reason}
                    for pt in plan["planned"]
                ],
                "n_signals": plan["n_signals"],
                "n_skipped": len(plan["skipped"]),
            })
    except Exception as e:
        log.warning(f"[auto-engine] shadow cycle error: {e}")


def _refresh_screener_bg():
    """Background task: refresh screener data and broadcast to all clients.

    Reverted from eventlet.tpool to inline compute — tpool.execute() inside
    a socketio.start_background_task() greenlet trips eventlet's "Cannot
    switch to a different thread" semaphore error, which silently kills the
    refresh greenlet without ever populating the cache. Field-caught 2026-05-29.

    Trade-off: pandas/yfinance work blocks the eventlet hub for 5-15s per
    90s cycle. UI logins during that window queue up. The login fast-path
    in on_login mitigates most of the user-visible impact; full fix
    requires either gevent/asgi migration or moving the screener compute
    to a subprocess.
    """
    if not _screener_refresh_lock.acquire(blocking=False):
        return  # already refreshing
    try:
        positions = []
        try:
            positions = dtrad._load_positions()
        except Exception:
            pass
        data = screener.refresh_screener(positions)
        _annotate_kb(data)
        _annotate_liquidity(data)
        _annotate_kb(data, options_only=True)   # re-score options for §9 liquidity (rank-liquidity-gate; CR-4)
        _annotate_held_exits(data, positions)
        _sort_screener_by_kb(data)
        if MERGED_PICKS_ENABLED:
            try:
                with _state_lock:
                    _vix = state.get("vix")
            except Exception:
                _vix = None
            data["picks"] = _build_picks(data, positions, _vix)
        _log_screened(data)          # EOD analysis: what we screened-as-buyable
        socketio.emit("screener_data", data)
        log.info(f"Screener refreshed: {len(data.get('dt',[]))} stocks, "
                 f"{len(data.get('options',[]))} options"
                 + (f", {len(data.get('picks',[]))} picks" if MERGED_PICKS_ENABLED else ""))
        _auto_exec_options(data)   # auto-place options if armed
        _auto_exec_stocks(data)    # auto-buy strong stock rows if armed
    except Exception as e:
        log.warning(f"Screener refresh failed: {e}")
    finally:
        _screener_refresh_lock.release()


@socketio.on("get_screener")
def on_get_screener(data=None):
    # #8 — screener cache is built from yfinance data; viewer is research-only.
    # The executor (execute_screener_option / toggle_auto_execute_options) is
    # still @require_auth so no trades can be placed without Alpaca login.
    """Client requests screener data. Return cache immediately, then refresh."""
    force = bool((data or {}).get("force", False))
    cached = screener.get_cached()
    if cached.get("dt"):
        _annotate_kb(cached)
        _annotate_liquidity(cached)
        _annotate_kb(cached, options_only=True)   # re-score options for §9 liquidity (CR-4)
        _cpos = []
        try:
            _cpos = dtrad._load_positions()
            _annotate_held_exits(cached, _cpos)
        except Exception:
            pass
        _sort_screener_by_kb(cached)
        if MERGED_PICKS_ENABLED:
            try:
                with _state_lock:
                    _vix = state.get("vix")
            except Exception:
                _vix = None
            cached["picks"] = _build_picks(cached, _cpos, _vix)
        socketio.emit("screener_data", cached, to=request.sid)
    if force or not cached.get("dt"):
        socketio.start_background_task(_refresh_screener_bg)
    else:
        # Serve cache; schedule background refresh if stale
        import time as _time
        age = _time.time() - cached.get("ts", 0)
        ttl = screener.CACHE_TTL_MARKET if screener._is_market_open() else screener.CACHE_TTL_CLOSED
        if age > ttl:
            socketio.start_background_task(_refresh_screener_bg)


@socketio.on("execute_screener_option")
@require_auth
def on_execute_screener_option(data=None):
    """Execute an options order from a screener recommendation row.

    Payload (from UI):
      sym       — underlying ticker (e.g. "NVDA")
      structure — "ATM Call" | "Debit Call Spread"
      expiry    — "2026-06-20"
      opt_type  — "Call" | "Put"
      max_risk  — max $ risk (default 400)

    Runs screener_executor in a background task so the WebSocket handler
    returns immediately. Result is emitted back to all clients as
    'screener_order_result'.
    """
    if not data:
        return

    # Basic validation
    sym = str(data.get("sym", "")).upper().strip()
    if not sym or not sym.isalpha():
        socketio.emit("screener_order_result", {
            "success": False, "sym": sym,
            "message": "Invalid symbol in execute request."
        }, to=request.sid)
        return

    with _state_lock:
        dry = state["dry_run"]

    # KB-principles + debate gate. Manual clicks can OVERRIDE (second click) —
    # the gate is advisory for a conscious manual trade, hard for the auto engine.
    if not data.get("kb_override"):
        allowed, gate_reason = _kb_and_debate_gate(data)
        if not allowed:
            socketio.emit("screener_order_result", {
                "success": False, "sym": sym, "gate_blocked": True,
                "message": f"{gate_reason}. Click again to override."
            }, to=request.sid)
            _emit_log(f"EXEC ⛔ {sym} blocked by gate — {gate_reason}", level="WARNING")
            return
    else:
        _emit_log(f"EXEC ⚠️ {sym} KB gate OVERRIDDEN (manual)", level="WARNING")

    sid = request.sid
    log.info(f"execute_screener_option: {sym}  structure={data.get('structure')}  "
             f"expiry={data.get('expiry')}  dry_run={dry}  gate={gate_reason}")

    def _run():
        result = screener_executor.execute_screener_option(data, dry_run=dry)
        socketio.emit("screener_order_result", result)   # broadcast to all clients
        level = "INFO" if result.get("success") else "WARNING"
        _emit_log(f"SCREENER EXEC  {result.get('message', '')}", level=level)

    socketio.start_background_task(_run)


@socketio.on("execute_screener_stock")
@require_auth
def on_execute_screener_stock(data=None):
    """Buy 10 shares of a screener stock pick (REQ-606), KB-gated (override-able)."""
    if not data:
        return
    sym = str(data.get("sym", "")).upper().strip()
    if not sym or not sym.replace(".", "").isalpha():
        socketio.emit("screener_order_result", {"success": False, "sym": sym,
                      "message": "Invalid symbol."}, to=request.sid)
        return
    with _state_lock:
        dry = state["dry_run"]
        vix = state.get("vix")
    # KB-principles gate (score the stock row) — manual clicks can override
    if not data.get("kb_override"):
        try:
            sc = kb_principles.score_stock_candidate(data, vix=vix)
            if sc["pct"] < kb_principles.KB_MATCH_MIN:
                socketio.emit("screener_order_result", {
                    "success": False, "sym": sym, "gate_blocked": True,
                    "kb_score": sc["pct"],
                    "message": (f"KB match {sc['pct']}% < {kb_principles.KB_MATCH_MIN}% "
                                f"— {'; '.join(sc['failed'][:2])}. Click again to override."),
                }, to=request.sid)
                return
        except Exception as e:
            log.warning(f"stock gate scoring error: {e}")
    sid = request.sid

    qty = _stock_qty_for(data.get("price"))
    if qty <= 0:
        socketio.emit("screener_order_result", {"success": False, "sym": sym,
                      "message": "No usable price for $5000 sizing."}, to=request.sid)
        return

    def _run():
        import shares_executor
        res = shares_executor.buy(sym, qty, dry_run=dry)   # ~$5000 equal-dollar sizing
        res["sym"] = sym
        res["message"] = (f"Bought {qty} {sym} (~${qty*float(data.get('price') or 0):.0f})"
                          if res.get("success") else
                          res.get("message", "stock order failed")) + (" [dry]" if dry else "")
        socketio.emit("screener_order_result", res)
        _emit_log(f"SCREENER STOCK EXEC  {res['message']}",
                  level="INFO" if res.get("success") else "WARNING")
    socketio.start_background_task(_run)


@socketio.on("toggle_auto_execute_options")
@require_auth
def on_toggle_auto_execute_options():
    """Arm or disarm headless options auto-execution."""
    with _state_lock:
        state["auto_execute_options"] = not state["auto_execute_options"]
        val = state["auto_execute_options"]
    log.info(f"Auto-execute options {'🟢 ARMED' if val else '⬛ disarmed'} "
             f"(executed today: {sorted(_auto_exec_today)})")
    emit_state()


@socketio.on("daily_eod_now")
@require_auth
def on_daily_eod_now():
    """Manually trigger the daily EOD routine (useful outside market hours for testing)."""
    with _state_lock:
        dry = state["dry_run"]
    socketio.start_background_task(_run_daily_eod)
    log.info(f"Daily EOD manually triggered (dry_run={dry})")


@socketio.on("start_session")
@require_auth
def on_start_session(data=None):
    """Start all-day session for the requested symbol (defaults to active_symbol)."""
    sym = ((data or {}).get("symbol") or state["active_symbol"]).upper()
    _launch_session(sym)


@socketio.on("stop_session")
@require_auth
def on_stop_session(data=None):
    """Stop the all-day session for the requested symbol."""
    sym = ((data or {}).get("symbol") or state["active_symbol"]).upper()
    if sym not in VALID_SYMBOLS:
        return
    _session_stop_events[sym].set()
    with _state_lock:
        state["sessions"][sym] = False
    log.info(f"{sym} session stopped by user.")
    emit_state()


@socketio.on("start_all_sessions")
@require_auth
def on_start_all_sessions():
    """Start all-day sessions for every configured symbol simultaneously."""
    for sym in _SYMBOLS_ORDERED:
        _launch_session(sym)


@socketio.on("stop_all_sessions")
@require_auth
def on_stop_all_sessions():
    """Stop all running sessions."""
    for sym in _SYMBOLS_ORDERED:
        _session_stop_events[sym].set()
    with _state_lock:
        for sym in _SYMBOLS_ORDERED:
            state["sessions"][sym] = False
    log.info("All sessions stopped by user.")
    emit_state()


@socketio.on("flatten_all")
@require_auth
def on_flatten_all(data=None):
    """EMERGENCY: close every open position immediately + halt new entries.

    Expects a confirmation token in the payload — the UI modal sets it after
    the user types FLATTEN to confirm. Idempotent: safe to call repeatedly.
    """
    if not data or data.get("confirm") != "FLATTEN":
        log.warning("flatten_all rejected: confirmation token missing")
        socketio.emit("log", {"message": "Flatten-all needs confirmation — type FLATTEN.", "level": "WARNING"})
        return
    log.warning(f"🛑 FLATTEN-ALL requested from {request.remote_addr}")
    summary = trader.flatten_all_positions(reason=f"user @ {request.remote_addr}")
    refresh_account()
    emit_state()
    socketio.emit("log", {
        "message": (
            f"🛑 FLATTEN: {summary['succeeded']}/{summary['attempted']} closed "
            f"({summary['dry_run']} dry-run, {summary['failed']} failed). Halt active."
        ),
        "level": "WARNING",
    })


@socketio.on("clear_emergency_halt")
@require_auth
def on_clear_emergency_halt():
    """Re-enable entries after a flatten-all kill switch."""
    trader.clear_emergency_halt()
    socketio.emit("log", {"message": "Emergency halt cleared — entries re-enabled.", "level": "INFO"})


@socketio.on("toggle_auto_schedule")
@require_auth
def on_toggle_auto_schedule():
    with _state_lock:
        state["auto_schedule"] = not state["auto_schedule"]
    log.info(f"Auto-schedule {'enabled' if state['auto_schedule'] else 'disabled'}")
    emit_state()


@socketio.on("toggle_news_filter")
@require_auth
def on_toggle_news_filter():
    with _state_lock:
        state["news_filter_enabled"] = not state["news_filter_enabled"]
        new_val = state["news_filter_enabled"]
    trader.init_news_filter(enabled=new_val)   # mirror to per-signal re-check gate
    log.info(f"News filter {'enabled' if new_val else 'disabled'}")
    emit_state()


@socketio.on("toggle_trade_memory")
@require_auth
def on_toggle_trade_memory():
    with _state_lock:
        state["trade_memory_enabled"] = not state["trade_memory_enabled"]
    trader.init_memory(enabled=state["trade_memory_enabled"])
    log.info(f"Trade memory {'enabled' if state['trade_memory_enabled'] else 'disabled'} ({trader.TRADE_MEMORY.count} trades stored)")
    emit_state()


@socketio.on("toggle_debate")
@require_auth
def on_toggle_debate():
    with _state_lock:
        state["debate_enabled"] = not state["debate_enabled"]
    trader.init_debate(enabled=state["debate_enabled"])
    status = "enabled" if trader.DEBATE_ENABLED else "disabled (ANTHROPIC_API_KEY missing?)"
    log.info(f"Bull/Bear debate {status}")
    emit_state()


@socketio.on("toggle_auto_trade")
@require_auth
def on_toggle_auto_trade():
    with _state_lock:
        state["auto_trade"] = not state["auto_trade"]
    trade_approval.auto_trade = state["auto_trade"]
    if state["auto_trade"]:
        log.warning("AUTO-TRADE ENABLED — orders will be placed without user approval!")
    else:
        log.info("Auto-trade disabled — manual approval required.")
    emit_state()


@socketio.on("refresh")
@require_auth
def on_refresh():
    refresh_account()
    refresh_prices()
    emit_state()


@socketio.on("sync_positions")
@require_auth
def on_sync_positions():
    """Force a two-way reconcile with Alpaca — picks up positions opened outside
    this session and drops stale local entries. No restart needed."""
    # Debug: log raw Alpaca positions so we can see exactly what comes back
    if trader.TRADING_CLIENT:
        try:
            raw = trader.TRADING_CLIENT.get_all_positions()
            log.info(f"sync_positions DEBUG: Alpaca returned {len(raw)} position(s):")
            for p in raw:
                log.info(f"  symbol={p.symbol}  asset_class={p.asset_class}  qty={p.qty}  avg_entry={p.avg_entry_price}")
        except Exception as e:
            log.warning(f"sync_positions DEBUG: get_all_positions failed: {e}")
    added = trader.reconcile_positions()
    refresh_account()
    emit_state()
    socketio.emit("sync_positions_done", {"added": added}, to=request.sid)


_VALID_INTERVALS  = frozenset({"1m", "5m", "15m", "30m", "1h", "1d"})
_VALID_RANGES     = frozenset({"1D", "5D", "1M", "3M", "1Y", "5Y"})

# Chart-bar cache: (symbol, interval, range) -> (bars_list, monotonic_ts)
_chart_cache: dict[tuple[str, str, str], tuple[list, float]] = {}
_chart_cache_lock = threading.Lock()

# Overlay cache: same key/TTL as bar cache.
# chart_overlays() calls fetch_daily_ema200 + fetch_prior_day_levels (both
# now cached 1 h in spy_auto_trader), but even the pandas math (VWAP/EMAs)
# adds ~5-20 ms per request — skip entirely when bars haven't changed.
_overlay_cache: dict[tuple[str, str, str], tuple[dict, float]] = {}
_overlay_cache_lock = threading.Lock()


# Tracks the interval/range the user is actually viewing so the background
# pre-warmer keeps exactly the right (symbol,interval,range) combos hot.
# A tab switch only changes the SYMBOL — interval/range stay — so warming all
# watchlist symbols at the last-used view makes every switch an instant hit.
_last_chart_view = {"interval": "15m", "range": "1D"}
_prewarm_idx = 0


def _prewarm_next_chart() -> None:
    """Round-robin: warm ONE watchlist symbol's chart cache per call (one
    yfinance fetch max, so the ticker thread never blocks on a 6× burst).
    6 symbols × every-other-tick (10s) ≈ each refreshed ~60s = the TTL."""
    global _prewarm_idx
    syms = _SYMBOLS_ORDERED
    sym = syms[_prewarm_idx % len(syms)]
    _prewarm_idx += 1
    iv, rng = _last_chart_view["interval"], _last_chart_view["range"]
    try:
        _cached_chart_bars(iv, rng, sym)   # populates _chart_cache if stale
    except Exception as e:
        log.debug(f"prewarm {sym} {iv}/{rng} failed: {e}")


def _cached_chart_bars(interval: str, range_: str, symbol: str, force_refresh: bool = False) -> list:
    """Cache chart bars per (symbol, interval, range) for CHART_CACHE_TTL_SEC."""
    key = (symbol, interval, range_)
    now = time.monotonic()
    if not force_refresh:
        with _chart_cache_lock:
            cached = _chart_cache.get(key)
            if cached and now - cached[1] < CHART_CACHE_TTL_SEC:
                return cached[0]
    bars = trader.fetch_chart_bars(interval, range_, symbol)
    with _chart_cache_lock:
        _chart_cache[key] = (bars, now)
    # Invalidate overlay cache when bars refresh so they stay in sync.
    with _overlay_cache_lock:
        _overlay_cache.pop(key, None)
    return bars


def _cached_chart_overlays(interval: str, range_: str, symbol: str, bars: list) -> dict:
    """Cache chart overlays alongside bars — same TTL.

    chart_overlays() runs pandas VWAP/EMA math + two API calls (ema200, prior
    levels). The API calls are individually cached in spy_auto_trader, but even
    the pandas pass adds latency on every 15-second auto-refresh. Cache the
    finished overlay dict so repeated fetches within the TTL window are instant.
    """
    if not bars:
        return {}
    key = (symbol, interval, range_)
    now = time.monotonic()
    with _overlay_cache_lock:
        cached = _overlay_cache.get(key)
        if cached and now - cached[1] < CHART_CACHE_TTL_SEC:
            return cached[0]
    overlays = trader.chart_overlays(bars, symbol)
    with _overlay_cache_lock:
        _overlay_cache[key] = (overlays, now)
    return overlays


@socketio.on("set_active_symbol")
def on_set_active_symbol(data):
    # #8 — UI state only. refresh_prices uses yfinance; safe pre-login.
    sym = (data or {}).get("symbol", "SPY").upper()
    if sym not in VALID_SYMBOLS:
        return
    with _state_lock:
        state["active_symbol"] = sym
    log.info(f"Active symbol switched to {sym}")
    refresh_prices()
    emit_state()


def _build_blocked_windows(bars: list) -> list:
    """Compute time-of-day shaded regions for the chart: lunch hour and the
    post-LAST_ENTRY_HOUR no-entry block. Returned as Unix-timestamp tuples
    that the frontend can render as background rectangles.

    Only emits windows that fall within the visible bar range so the frontend
    doesn't have to clip.
    """
    if not bars:
        return []
    try:
        from datetime import datetime as _dt, time as _t
        from zoneinfo import ZoneInfo
        ET = ZoneInfo("America/New_York")
        first_ts, last_ts = bars[0]["time"], bars[-1]["time"]
        # Anchor windows on the most-recent visible trading day (matches the
        # 1D view; longer ranges show only the most recent day's blocked zones).
        day_dt = _dt.fromtimestamp(last_ts, tz=ET).replace(
            hour=0, minute=0, second=0, microsecond=0,
        )
        out = []
        for label, start, end in [
            ("lunch",       day_dt.replace(hour=11, minute=30),
                            day_dt.replace(hour=13, minute=30)),
            ("post-cutoff", day_dt.replace(hour=14, minute=0),
                            day_dt.replace(hour=16, minute=0)),
        ]:
            if end.timestamp() < first_ts or start.timestamp() > last_ts:
                continue
            out.append({
                "label": label,
                "start": int(max(start.timestamp(), first_ts)),
                "end":   int(min(end.timestamp(), last_ts)),
            })
        return out
    except Exception as e:
        log.warning(f"_build_blocked_windows: {e}")
        return []


@socketio.on("get_chart_data")
def on_get_chart_data(data=None):
    # #8 — chart data is yfinance-cached, no Alpaca TradingClient required.
    """Return OHLCV bars + signal markers for the requested symbol, interval, and range."""
    data     = data or {}
    interval = data.get("interval", "15m")
    range_   = data.get("range",    "1D")
    force    = bool(data.get("force_refresh", False))
    seq      = data.get("_seq")
    pane_id  = data.get("pane_id")

    if interval not in _VALID_INTERVALS: interval = "15m"
    if range_   not in _VALID_RANGES:    range_   = "1D"
    # Track what the user is viewing so the pre-warmer hot-caches the right
    # combo for all watchlist symbols → next tab switch is an instant hit.
    _last_chart_view["interval"] = interval
    _last_chart_view["range"]    = range_

    with _state_lock:
        active = state["active_symbol"]
    symbol = (data.get("symbol") or active).upper()
    if symbol not in VALID_SYMBOLS:
        symbol = "SPY"

    try:
        bars = _cached_chart_bars(interval, range_, symbol, force_refresh=force)
        with _state_lock:
            signals = [m for m in signal_history if m.get("symbol", "SPY") == symbol]

        # Indicators + ORB + prior levels for the chart overlay (cached)
        overlays = _cached_chart_overlays(interval, range_, symbol, bars)

        # Position overlay: every open position on this symbol, with stop/T1/T2/peak
        positions_for_symbol = [
            p for p in trader.open_positions_snapshot()
            if p.get("symbol") == symbol and p.get("remaining", 0) > 0
        ]
        position_overlay = [
            {
                "occ_symbol":  p["occ_symbol"],
                "direction":   p["direction"],
                "entry_price": p["entry_price"],
                "stop_price":  p["stop_price"],
                "target_50":   p["target_50"],
                "target_75":   p["target_75"],
                "remaining":   p["remaining"],
                "opened_at":   p.get("opened_at"),
                "is_dry_run":  p.get("is_dry_run", False),
                "partial_done":p.get("partial_done", False),
                "peak_mid":    p.get("peak_mid_after_t1", 0.0),
            }
            for p in positions_for_symbol
        ]

        # Blocked windows: lunch + post-LAST_ENTRY_HOUR shading for the active day
        blocked_windows = _build_blocked_windows(bars)

        socketio.emit("chart_data", {
            "bars":     bars,
            "signals":  signals,
            "interval": interval,
            "range":    range_,
            "symbol":   symbol,
            "_seq":     seq,
            "pane_id":  pane_id,
            "overlays":         overlays,
            "position_overlay": position_overlay,
            "blocked_windows":  blocked_windows,
        })
    except Exception as e:
        log.warning(f"Chart data error: {e}", exc_info=True)
        socketio.emit("chart_data", {
            "bars": [], "signals": [], "interval": interval, "range": range_,
            "symbol": symbol, "_seq": seq, "pane_id": pane_id,
        })


@socketio.on("trade_response")
@require_auth
def on_trade_response(data):
    """User responded to a trade approval modal."""
    approved = bool(data.get("approved", False))
    trade_approval.respond(approved)
    log.info(f"Trade {'ALLOWED' if approved else 'SKIPPED'} by user via UI")


@socketio.on("start_stream")
def on_start_stream():
    # #8 — log/price stream toggle. Alpaca-touching refresh_account is
    # guarded so a public user can still resume the price feed.
    state["streaming"] = True
    with _state_lock:
        is_logged_in = state["logged_in"]
    if is_logged_in:
        refresh_account()
    refresh_prices()
    log.info("Live stream resumed — price + log feed active")
    emit_state()


@socketio.on("stop_stream")
def on_stop_stream():
    # #8 — pure UI flag, safe pre-login.
    state["streaming"] = False
    emit_state()
    log.info("Live stream paused — UI feed stopped (sessions still run)")


# ── Exec Brief ────────────────────────────────────────────────────────────────
@socketio.on("get_exec_brief")
@require_auth
def on_get_exec_brief():
    """Generate and emit a one-paragraph narrative of today's activity."""
    socketio.start_background_task(_build_exec_brief)


def _build_exec_brief() -> None:
    """Build a narrative summary and emit it as 'exec_brief'."""
    try:
        with _state_lock:
            trades   = list(state["trades_today"])
            sessions = dict(state["sessions"])
            acct     = state["account_value"]
            spy_px   = state["spy_price"]
            vix      = state["vix"]
            dry_run  = state["dry_run"]

        positions = trader.open_positions_snapshot()                  # options
        account_pos = _account_equity_positions()                     # stocks + ETFs (truth)
        n_opt     = len([p for p in positions if p.get("remaining", 0) > 0])
        n_open    = n_opt + len(account_pos)
        equity_pnl = sum(float(p.get("pnl_usd", 0) or 0) for p in account_pos)
        closed    = [t for t in trades if not t.get("is_partial")]
        wins      = [t for t in closed if t.get("pnl_pct", 0) > 0]
        losses    = [t for t in closed if t.get("pnl_pct", 0) < 0]
        active    = [s for s, on in sessions.items() if on]
        watching  = ", ".join(active) if active else "none"
        mode      = "paper dry-run" if dry_run else "paper live"

        # Build plain stats for the LLM
        plain = (
            f"Mode: {mode}\n"
            f"Account: ${acct:,.0f}  |  SPY: ${spy_px:.2f}  |  VIX: {vix:.1f}\n"
            f"Sessions running: {watching or 'none'}\n"
            f"Closed trades today: {len(closed)} total — {len(wins)} wins, {len(losses)} losses\n"
        )
        if closed:
            for t in closed:
                plain += f"  {t.get('symbol','?')} {t.get('direction','?').upper()} {t.get('pnl_pct',0):+.1f}% ({t.get('reason','')})\n"
        plain += (f"Open positions: {n_open} total "
                  f"({len(account_pos)} stocks/ETFs, {n_opt} options) — "
                  f"unrealized P&L ${equity_pnl:+,.0f}\n")
        if account_pos:
            for p in sorted(account_pos, key=lambda x: -abs(x.get("pnl_usd", 0)))[:8]:
                plain += (f"  {p['sym']} {p['qty']}sh entry=${p['entry']:.2f} "
                          f"P&L ${p.get('pnl_usd',0):+.0f} ({p.get('pnl_pct',0):+.1f}%)\n")
        for p in positions[:3]:
            pnl = p.get("unrealized_pct", 0) or 0
            plain += f"  {p.get('occ_symbol','?')} {p.get('direction','?').upper()} unrealized={pnl:+.1f}%\n"

        api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if api_key:
            try:
                import anthropic
                import debate as _d; client = _d.get_anthropic_client()
                if client is None:
                    raise RuntimeError('no anthropic client')
                prompt = (
                    "You are the co-pilot AI for an automated multi-strategy PAPER trading "
                    "system that trades stocks, ETFs and options across several lanes "
                    "(an autonomous ETF/stock engine, options auto-exec, and stock auto-buy). "
                    "Write ONE short paragraph (3-4 sentences max) summarising the current state "
                    "for the dashboard. GROUND IT IN THE DATA: state the number of OPEN POSITIONS "
                    "and total unrealized P&L accurately — do NOT say 'no positions' or 'full cash' "
                    "if positions are listed below. Be direct and specific; no preamble, no bullet "
                    "points.\n\n"
                    f"Today's data:\n{plain}"
                )
                resp = client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=150,
                    messages=[{"role": "user", "content": prompt}],
                )
                narrative = resp.content[0].text.strip()
            except Exception as e:
                log.warning(f"exec_brief LLM failed: {e}")
                narrative = _plain_narrative(closed, wins, losses, n_open, watching, mode, spy_px, vix)
        else:
            narrative = _plain_narrative(closed, wins, losses, n_open, watching, mode, spy_px, vix)

        socketio.emit("exec_brief", {
            "narrative": narrative,
            "stats": {
                "closed": len(closed),
                "wins":   len(wins),
                "losses": len(losses),
                "open":   n_open,
                "watching": watching,
            }
        })
    except Exception as e:
        log.warning(f"_build_exec_brief failed: {e}")
        socketio.emit("exec_brief", {"narrative": "Initialising…", "stats": {}})


def _plain_narrative(closed, wins, losses, n_open, watching, mode, spy_px, vix) -> str:
    if not closed and n_open == 0:
        return (f"Running in {mode} mode — no trades taken yet today. "
                f"SPY at ${spy_px:.2f}, VIX {vix:.1f}. "
                f"Watching: {watching or 'sessions not started'}.")
    parts = []
    if closed:
        parts.append(f"Closed {len(closed)} trade(s) today — {len(wins)} win(s), {len(losses)} loss(es).")
    if n_open:
        parts.append(f"{n_open} position(s) currently open.")
    if watching:
        parts.append(f"Monitoring: {watching}.")
    parts.append(f"SPY ${spy_px:.2f} | VIX {vix:.1f} | {mode}.")
    return " ".join(parts)


# ── Backtest UI ───────────────────────────────────────────────────────────────
@socketio.on("run_backtest")
def on_run_backtest(data=None):
    # #8 — pure historical compute. No Alpaca TradingClient needed.
    """Run backtest in background and stream results to the UI."""
    data       = data or {}
    symbols    = [s.strip().upper() for s in (data.get("symbols") or ["SPY"]) if s.strip()][:30]
    years      = max(0.5, min(float(data.get("years", 1.0)), 5.0))
    source     = data.get("source", "yfinance")
    bar_size   = data.get("bar_size", "daily")
    strategies = data.get("strategies") or ["breakout", "bull_flag", "rsi_dip", "gap_vol"]
    stop_pct   = max(0.05, min(float(data.get("stop_pct",  0.30)), 0.60))
    target_pct = max(0.20, min(float(data.get("target_pct", 1.00)), 2.00))
    vol_min    = max(0.8,  min(float(data.get("vol_min",    1.2)),  3.0))
    socketio.start_background_task(
        _run_backtest_task,
        symbols, years, source, bar_size, strategies,
        stop_pct, target_pct, vol_min, request.sid
    )


def _run_backtest_task(symbols: list, years: float, source: str, bar_size: str,
                       strategies: list, stop_pct: float, target_pct: float,
                       vol_min: float, sid: str) -> None:
    import sys, importlib
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def _emit(msg: str, level: str = "INFO"):
        socketio.emit("backtest_log", {"message": msg, "level": level}, to=sid)

    _INTRADAY_KEYS = {"orb", "vwap", "ema", "rsi_gate"}
    _DAILY_KEYS    = {
        # Core validated (KB §DT1–DT5)
        "breakout", "bull_flag", "rsi_dip", "gap_vol",
        # Extended KB-derived strategies
        "rsi_dip_red", "nr7", "bb_squeeze", "pocket_pivot", "pbs", "turtle_soup",
    }
    intraday_strats = [s for s in strategies if s in _INTRADAY_KEYS]
    daily_strats    = [s for s in strategies if s in _DAILY_KEYS]
    days_intraday   = min(59, int(years * 365))   # yfinance 5-min cap

    _emit(f"── Backtest ─ {len(symbols)} symbols · {years}yr · {source} · {bar_size} bars ──")
    if intraday_strats:
        _emit(f"  Intraday ({', '.join(intraday_strats)}) · {days_intraday}d window")
    if daily_strats:
        _emit(f"  Daily setups ({', '.join(daily_strats)}) · {years}yr window")

    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    import backtest as bt_mod
    importlib.reload(bt_mod)

    results = []
    for sym in symbols:
        # ── Daily setups ──────────────────────────────────────────────────────
        if daily_strats and (bar_size == "daily" or bar_size == "both"):
            try:
                _emit(f"→ {sym} — daily setups ({', '.join(daily_strats)})…")
                rs = bt_mod.run_daily_backtest(
                    sym, years, source, daily_strats,
                    stop_pct=stop_pct, target_pct=target_pct, vol_min=vol_min
                )
                for r in rs:
                    if r and r.get("trades", 0) > 0:
                        results.append(r)
                        m = r["metrics"]
                        pf = m.get("profit_factor", "n/a")
                        _emit(f"  ✓ {sym}/{r['setup']}: {r['trades']} trades | "
                              f"WR {m.get('win_rate',0):.1f}% | PF {pf} | "
                              f"Sharpe {m.get('sharpe',0):.2f}")
                    else:
                        _emit(f"  — {sym}/{r.get('setup','?')}: 0 signals in period")
            except Exception as e:
                _emit(f"✗ {sym} daily failed: {e}", "ERROR")

        # ── Intraday signals ──────────────────────────────────────────────────
        if intraday_strats and (bar_size == "5min" or bar_size == "both"):
            try:
                _emit(f"→ {sym} — intraday signals ({', '.join(intraday_strats)}) · {days_intraday}d…")
                r = bt_mod.run_backtest(
                    sym, days_intraday, source, intraday_strats,
                    stop_pct=stop_pct, target_pct=target_pct, vol_min=vol_min,
                    bar_size="5min"
                )
                if r and r.get("trades", 0) > 0:
                    results.append(r)
                    m = r["metrics"]
                    pf = m.get("profit_factor", "n/a")
                    _emit(f"  ✓ {sym}/Intraday: {r['trades']} trades | "
                          f"WR {m.get('win_rate',0):.1f}% | PF {pf} | "
                          f"Sharpe {m.get('sharpe',0):.2f}")
                else:
                    _emit(f"  — {sym}/Intraday: 0 signals in {days_intraday}d window")
            except Exception as e:
                _emit(f"✗ {sym} intraday failed: {e}", "ERROR")

    socketio.emit("backtest_results", {
        "results": results, "years": years,
        "source": source, "bar_size": bar_size
    }, to=sid)
    _emit(f"✅ Backtest complete — {len(results)} result rows")


# ── Auto-login at startup ─────────────────────────────────────────────────────
def _auto_login():
    """
    If Alpaca credentials are present in .env (or environment), connect to
    Alpaca automatically at startup — no browser login required. The server
    begins monitoring positions and executing scheduled trades immediately.
    Any browser that connects later will still see the login overlay (for UI
    auth) but the backend is already live.

    Credentials are resolved via the shared `credentials.load_alpaca_creds()`
    loader, which supports the canonical ALPACA_API_KEY/SECRET/PAPER names
    plus the legacy ALPACA_AUTO_* fallback chain. See scripts/credentials.py.
    """
    socketio.sleep(3)   # let the server fully bind before hitting Alpaca

    from credentials import load_alpaca_creds
    creds = load_alpaca_creds()

    if not creds.is_complete:
        log.info("[auto-login] No credentials in .env — waiting for browser login.")
        return

    try:
        api_key    = validate_api_key(creds.key)
        api_secret = validate_api_secret(creds.secret)
    except ValueError as e:
        log.error(f"[auto-login] Invalid credentials in .env: {e}")
        return

    account, ok, err = trader.init_clients(api_key, api_secret, paper=creds.paper)
    if not ok:
        log.error(f"[auto-login] Alpaca connection failed: {err}")
        return

    # Stash key prefix so a subsequent browser login can fast-path the
    # redundant Alpaca handshake (see on_login fast_path_taken branch).
    try:
        trader.ACTIVE_KEY_PREFIX = api_key[:6]
    except Exception:
        pass

    with _state_lock:
        state["logged_in"]  = True
        state["paper_mode"] = creds.paper

    trader.init_memory(enabled=state.get("trade_memory_enabled", True))
    trader.init_debate(enabled=state.get("debate_enabled", True))
    trader.init_news_filter(enabled=state.get("news_filter_enabled", True))
    trader.DRY_RUN            = state.get("dry_run", False)
    trade_approval.auto_trade = state.get("auto_trade", True)

    mode_str = "PAPER" if creds.paper else "LIVE"
    log.info(
        f"[auto-login] ✅ Connected to Alpaca {mode_str} — "
        f"key={creds.key_prefix}… equity=${float(account.equity):,.2f}"
    )


def _single_instance_guard(port: int = 5000) -> None:
    """Refuse to start if something is already serving on `port`.

    The recurring 'app unresponsive' outages were two processes colliding on
    :5000 (a stale instance + a fresh one). If the port already accepts a
    connection, an instance is up — exit cleanly rather than fighting over the
    socket. Plain socket check only (urllib gets trampolined by eventlet).
    """
    import sys as _sys
    import socket as _socket
    try:
        with _socket.create_connection(("127.0.0.1", port), timeout=2):
            pass
    except OSError:
        return  # nothing listening — safe to start
    log.error(f"Another process is already serving on :{port}. Refusing to start a "
              f"second instance (this avoids the port-collision hang). Exiting.")
    _sys.exit(0)


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    _single_instance_guard(5000)   # never run two instances on the same port
    _record_boot()            # OB-5: track restart frequency (instability signal)
    _load_auto_exec_state()   # restore today's dedup set if mid-day restart
    _load_trades_today()      # restore today's closed trades (#17)
    _load_exit_config()       # restore operator-edited exit thresholds
    socketio.start_background_task(price_ticker)
    socketio.start_background_task(scheduler)
    socketio.start_background_task(_scheduler_supervisor)   # respawn scheduler if it dies
    socketio.start_background_task(position_monitor)
    socketio.start_background_task(_auto_login)  # connect to Alpaca on boot if .env has creds

    print("\n" + "=" * 55)
    print("  SPY Auto Trader — Dashboard")
    print("  URL  : http://localhost:5000")
    print("  Logs : spy_trader.log  |  security.log")
    print("=" * 55 + "\n")

    _run_kwargs = dict(
        host="127.0.0.1",     # Localhost only — not reachable from outside
        port=5000,
        debug=False,
        log_output=False,
    )
    # allow_unsafe_werkzeug is only relevant when async_mode falls back to
    # threading. Eventlet runs its own WSGI server and rejects this kwarg.
    if _ASYNC_MODE == "threading":
        _run_kwargs["allow_unsafe_werkzeug"] = True
    socketio.run(
        app,
        **_run_kwargs,
    )
