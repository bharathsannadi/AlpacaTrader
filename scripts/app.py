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

from flask import Flask, render_template, request, jsonify, session
from flask_socketio import SocketIO, disconnect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv

import spy_auto_trader as trader
import news_filter
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

load_dotenv()
ET = ZoneInfo("America/New_York")

# ── Tunables (named constants over magic numbers) ─────────────────────────────
TICKER_INTERVAL_SEC      = 5         # price + state push cadence
ACCOUNT_REFRESH_TICKS    = 3         # refresh account/buying power every N ticks (~15s)
VIX_CACHE_TTL_SEC        = 120       # VIX rarely changes
PRIOR_LEVELS_CACHE_SEC   = 3600      # prior-day OHLC: refresh hourly
CHART_CACHE_TTL_SEC      = 8         # short-window bar cache (matches 10s JS refresh)
APPROVAL_TIMEOUT_SEC     = 60
POSITION_MONITOR_SEC     = 10        # position monitor poll interval (10s for tighter stop execution)
LOGIN_RATE_LIMIT         = "10 per minute"
API_STATUS_RATE_LIMIT    = "30 per minute"
MAX_SIGNAL_HISTORY       = 50
VALID_SYMBOLS            = frozenset({"SPY", "AMZN", "GOOG", "MSFT", "NVDA", "META"})
_SYMBOLS_ORDERED         = ["SPY", "AMZN", "GOOG", "MSFT", "NVDA", "META"]
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

def add_signal_marker(direction: str, price: float, reason: str, symbol: str = "SPY") -> None:
    """Record a signal for chart display (thread-safe). Tagged with symbol so
    the frontend only renders markers on the matching symbol's chart."""
    marker = {
        "time":      int(datetime.now(ET).timestamp()),
        "price":     float(price),
        "direction": direction,
        "reason":    reason,
        "symbol":    symbol.upper(),
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
    "dry_run":         True,
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
    "auto_schedule":        True,   # auto-start sessions at 9:30 ET on weekdays
    "news_filter_enabled":  True,   # veto session if bad headlines detected
    "trade_memory_enabled": True,   # ChromaDB similarity recall before signals
    "debate_enabled":       False,  # Bull/Bear LLM debate gate (needs ANTHROPIC_API_KEY)
    "auto_trade":           False,  # skip approval modal — orders placed automatically
}

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
def _state_snapshot() -> dict:
    """Single source of truth for the state payload sent to the UI."""
    with _state_lock:
        return {
            "logged_in":       state["logged_in"],
            "sessions":        dict(state["sessions"]),   # per-symbol {SPY: bool, ...}
            "streaming":       state["streaming"],
            "dry_run":         state["dry_run"],
            "paper_mode":      state["paper_mode"],
            "active_symbol":   state["active_symbol"],
            "session_end":     state["session_end"],
            "account_value":   state["account_value"],
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
            "open_positions":       trader.open_positions_snapshot(),
            "deployed_risk_pct":    round(trader.deployed_risk_pct(state["account_value"]) * 100, 2),
            "data_freshness":       trader.get_freshness_snapshot(),
            "timestamp":            datetime.now(ET).strftime("%H:%M:%S ET"),
        }


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


def price_ticker() -> None:
    """Background thread: refresh prices on TICKER_INTERVAL_SEC.
    Gated on streaming + at least one authenticated client connected.
    Also refreshes account/buying power every ACCOUNT_REFRESH_TICKS iterations
    so the header stays current without waiting for a fill."""
    tick = 0
    while True:
        try:
            with _state_lock:
                should_run = (state["logged_in"]
                              and state["streaming"]
                              and len(authenticated_sids) > 0)
            if should_run:
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
    Closes at stop-loss, profit target 1 (partial), profit target 2, or hard-close time."""
    while True:
        socketio.sleep(POSITION_MONITOR_SEC)
        try:
            with _state_lock:
                should_run = state["logged_in"] and bool(authenticated_sids)
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
                    "symbol":     ev["symbol"],
                    "direction":  ev["direction"],
                    "pnl_pct":    ev["pnl_pct"],
                    "reason":     ev["reason"],
                    "time":       datetime.now(ET).strftime("%H:%M"),
                    "is_partial": ev.get("is_partial", False),
                }
                with _state_lock:
                    state["trades_today"].append(close_entry)
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
        log.info("EOD Review: complete")
    except Exception as e:
        log.warning(f"EOD Review failed: {e}")


# ── Routes ────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    session.permanent = True
    return render_template("index.html")


@app.route("/api/status")
@limiter.limit(API_STATUS_RATE_LIMIT)
def api_status():
    if not session.get("authenticated"):
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify({k: v for k, v in state.items() if k != "trades_today"})


@app.route("/health")
def health():
    return jsonify({"status": "ok"}), 200


# ── WebSocket events ──────────────────────────────────────────────────────────
@socketio.on("connect")
def on_connect():
    ip = request.remote_addr
    security_log.info(f"WebSocket connect from {ip}")
    # Per-client state with `logged_in` reflecting this specific socket's auth.
    snapshot = _state_snapshot()
    snapshot["logged_in"] = request.sid in authenticated_sids
    socketio.emit("state", snapshot, to=request.sid)


@socketio.on("disconnect")
def on_disconnect():
    with _state_lock:
        authenticated_sids.discard(request.sid)
        no_auth_left = not authenticated_sids
    # If no authenticated sessions remain, clear the global logged_in flag
    # so a fresh page reload sees the login modal.
    if no_auth_left:
        with _state_lock:
            if state["logged_in"]:
                state["logged_in"] = False
                log.info("No authenticated sessions remain — logged_in cleared.")
    security_log.info(f"WebSocket disconnect from {request.remote_addr}")


@socketio.on("login")
@limiter.limit(LOGIN_RATE_LIMIT, key_func=get_remote_address)
def on_login(data):
    ip = request.remote_addr

    locked, remaining = login_tracker.is_locked(ip)
    if locked:
        mins = remaining // 60 + 1
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

    # Connect to Alpaca
    account, ok, err = trader.init_clients(api_key, api_secret, paper=paper)
    if not ok:
        login_tracker.record_failure(ip)
        # Include the paper-mode flag + key prefix so we can diagnose
        # "credentials work in curl but not in app" mismatches.
        key_prefix = api_key[:6] if api_key else "?"
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
    session["api_key_prefix"] = api_key[:6] + "…"
    session["login_time"]     = datetime.now(timezone.utc).isoformat()
    login_tracker.record_success(ip)
    security_log.info(f"Successful Alpaca login from {ip} (paper={paper})")
    trader.init_memory(enabled=state.get("trade_memory_enabled", True))
    trader.init_debate(enabled=state.get("debate_enabled", False))
    trader.init_news_filter(enabled=state.get("news_filter_enabled", True))
    refresh_account()
    refresh_prices()
    socketio.emit("login_result", {"success": True})
    emit_state()
    log.info(f"Connected to Alpaca {'PAPER' if paper else 'LIVE'} — equity ${float(account.equity):,.2f}")


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
    log.info(f"Risk per trade updated to {pct}%")


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

    # Portfolio risk cap: refuse to open a new session if total deployed risk
    # across all open positions already meets or exceeds MAX_PORTFOLIO_RISK (3%).
    acct = trader.account_value()
    deployed = trader.deployed_risk_pct(acct)
    if deployed >= trader.MAX_PORTFOLIO_RISK:
        msg = (
            f"{sym} session blocked — portfolio already at "
            f"{deployed*100:.1f}% risk "
            f"(cap={trader.MAX_PORTFOLIO_RISK*100:.0f}%)"
        )
        log.warning(msg)
        socketio.emit("log", {"message": f"⚠ {msg}", "level": "WARNING"})
        return

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
LOG_PATH = os.path.join(os.path.dirname(__file__), "spy_trader.log")


def scheduler():
    """Background task: auto-start all-day sessions at 9:30 ET on weekdays,
    and fire end-of-day learning review at 15:35 ET."""
    session_fired_on = None
    eod_fired_on     = None

    while True:
        socketio.sleep(30)
        now = datetime.now(ET)

        if now.weekday() > 4:   # skip weekends
            continue

        with _state_lock:
            if not state["logged_in"] or not state["auto_schedule"]:
                continue

        today = now.date()
        sh, sm = SESSION_AUTO_START
        if (now.hour, now.minute) == (sh, sm) and session_fired_on != today:
            session_fired_on = today
            log.info("Auto-scheduler: starting all-day sessions for all symbols")
            for sym in _SYMBOLS_ORDERED:
                _launch_session(sym)

        # EOD learning review — fires once at 15:35 ET after all sessions have ended
        if (now.hour, now.minute) == (EOD_REVIEW_HOUR, EOD_REVIEW_MINUTE) and eod_fired_on != today:
            eod_fired_on = today
            with _state_lock:
                trades_snapshot = list(state["trades_today"])
            socketio.start_background_task(_run_eod_review, trades_snapshot)


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


_VALID_INTERVALS  = frozenset({"1m", "5m", "15m", "30m", "1h", "1d"})
_VALID_RANGES     = frozenset({"1D", "5D", "1M", "3M", "1Y", "5Y"})

# Chart-bar cache: (symbol, timeframe) -> (bars_list, monotonic_ts)
_chart_cache: dict[tuple[str, str], tuple[list, float]] = {}
_chart_cache_lock = threading.Lock()


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
    return bars


@socketio.on("set_active_symbol")
@require_auth
def on_set_active_symbol(data):
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
@require_auth
def on_get_chart_data(data=None):
    """Return OHLCV bars + signal markers for the requested symbol, interval, and range."""
    data     = data or {}
    interval = data.get("interval", "15m")
    range_   = data.get("range",    "1D")
    force    = bool(data.get("force_refresh", False))
    seq      = data.get("_seq")

    if interval not in _VALID_INTERVALS: interval = "15m"
    if range_   not in _VALID_RANGES:    range_   = "1D"

    with _state_lock:
        active = state["active_symbol"]
    symbol = (data.get("symbol") or active).upper()
    if symbol not in VALID_SYMBOLS:
        symbol = "SPY"

    try:
        bars = _cached_chart_bars(interval, range_, symbol, force_refresh=force)
        with _state_lock:
            signals = [m for m in signal_history if m.get("symbol", "SPY") == symbol]

        # Indicators + ORB + prior levels for the chart overlay
        overlays = trader.chart_overlays(bars, symbol) if bars else {}

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
            "overlays":         overlays,
            "position_overlay": position_overlay,
            "blocked_windows":  blocked_windows,
        })
    except Exception as e:
        log.warning(f"Chart data error: {e}", exc_info=True)
        socketio.emit("chart_data", {
            "bars": [], "signals": [], "interval": interval, "range": range_,
            "symbol": symbol, "_seq": seq,
        })


@socketio.on("trade_response")
@require_auth
def on_trade_response(data):
    """User responded to a trade approval modal."""
    approved = bool(data.get("approved", False))
    trade_approval.respond(approved)
    log.info(f"Trade {'ALLOWED' if approved else 'SKIPPED'} by user via UI")


@socketio.on("start_stream")
@require_auth
def on_start_stream():
    state["streaming"] = True
    refresh_account()
    refresh_prices()
    log.info("Live stream resumed — price + log feed active")
    emit_state()


@socketio.on("stop_stream")
@require_auth
def on_stop_stream():
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

        positions = trader.open_positions_snapshot()
        n_open    = len([p for p in positions if p.get("remaining", 0) > 0])
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
        plain += f"Open positions: {n_open}\n"
        if positions:
            for p in positions[:4]:
                pnl = p.get("unrealized_pct", 0) or 0
                plain += f"  {p.get('occ_symbol','?')} {p.get('direction','?').upper()} entry=${p.get('entry_price',0):.2f} unrealized={pnl:+.1f}%\n"

        api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if api_key:
            try:
                import anthropic
                client = anthropic.Anthropic(api_key=api_key)
                prompt = (
                    "You are the co-pilot AI for an automated SPY options trading system. "
                    "Write ONE short paragraph (3-4 sentences max) summarising today's trading activity "
                    "for the dashboard. Include: what the bot did, current state, what it's watching. "
                    "Be direct and specific. No preamble, no bullet points — just a flowing sentence or two.\n\n"
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


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    socketio.start_background_task(price_ticker)
    socketio.start_background_task(scheduler)
    socketio.start_background_task(position_monitor)

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
