"""
Auto Trader — Secure Web Dashboard
Security: security headers, rate limiting, login lockout,
          session authentication, input validation.
"""

import os
import logging
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone
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
TICKER_INTERVAL_SEC      = 15        # price + state push cadence
VIX_CACHE_TTL_SEC        = 120       # VIX rarely changes
PRIOR_LEVELS_CACHE_SEC   = 3600      # prior-day OHLC: refresh hourly
CHART_CACHE_TTL_SEC      = 30        # short-window bar cache
APPROVAL_TIMEOUT_SEC     = 60
LOGIN_RATE_LIMIT         = "10 per minute"
API_STATUS_RATE_LIMIT    = "30 per minute"
MAX_SIGNAL_HISTORY       = 50
VALID_SYMBOLS            = frozenset({"SPY", "AMZN", "GOOG", "MSFT", "NVDA", "META"})
MORNING_AUTO_START       = (9,  30)  # ET hour, minute to auto-fire morning session
EVENING_AUTO_START       = (15,  0)  # ET hour, minute to auto-fire evening session

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
    async_mode="threading",
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
    the current trade's outcome."""

    def __init__(self) -> None:
        self._event    = threading.Event()
        self._approved = False
        self._pending  = False
        self._lock     = threading.Lock()

    def request(self, details: dict) -> bool:
        with self._lock:
            self._approved = False
            self._pending  = True
            self._event.clear()
            payload = dict(details)
            payload["timeout"] = APPROVAL_TIMEOUT_SEC
            socketio.emit("trade_signal", payload)
            add_signal_marker(
                direction = details.get("direction", "bull"),
                price     = details.get("mid_price", 0),
                reason    = details.get("reason", ""),
                symbol    = details.get("symbol", "SPY"),
            )

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
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler("spy_trader.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

security_log = logging.getLogger("security")
sec_handler   = logging.FileHandler("security.log")
sec_handler.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s"))
security_log.addHandler(sec_handler)
security_log.setLevel(logging.INFO)


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
    "morning_running": False,
    "evening_running": False,
    "streaming":       True,         # Live price + log streaming
    "dry_run":         True,
    "paper_mode":      True,         # Alpaca paper vs live
    "active_symbol":   "SPY",        # currently selected tab
    "morning_symbol":  None,         # symbol the running morning session is trading
    "evening_symbol":  None,         # symbol the running evening session is trading
    # Configurable session end times (24h HH:MM)
    "morning_end":     "10:00",
    "evening_end":     "15:30",
    "account_value":   0.0,
    "buying_power":    0.0,
    "trades_today":    [],
    "spy_price":       None,
    "spy_change_pct":  None,
    "vix":             None,
    # Trade-rule parameters (mirror trader module constants)
    "vix_max":         30,
    "stop_loss":       50,    # % of premium paid
    "profit_target":   75,    # % of premium paid
    "dte_min":         7,
    "dte_max":         14,
    "auto_schedule":     True,   # auto-start sessions at market open/close
    "news_filter_enabled": True,  # veto session if bad headlines detected
}

morning_thread = None
evening_thread = None

# ── Sleep prevention (macOS caffeinate) ──────────────────────────────────────
_caffeinate_proc: "subprocess.Popen | None" = None
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
        still_active = state["morning_running"] or state["evening_running"]
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
            "morning_running": state["morning_running"],
            "evening_running": state["evening_running"],
            "morning_symbol":  state["morning_symbol"],
            "evening_symbol":  state["evening_symbol"],
            "streaming":       state["streaming"],
            "dry_run":         state["dry_run"],
            "paper_mode":      state["paper_mode"],
            "active_symbol":   state["active_symbol"],
            "account_value":   state["account_value"],
            "buying_power":    state["buying_power"],
            "spy_price":       state["spy_price"],
            "spy_change_pct":  state["spy_change_pct"],
            "vix":             state["vix"],
            "trades_today":    list(state["trades_today"]),
            "morning_end":     state["morning_end"],
            "evening_end":     state["evening_end"],
            "vix_max":         state["vix_max"],
            "stop_loss":       state["stop_loss"],
            "profit_target":   state["profit_target"],
            "dte_min":         state["dte_min"],
            "dte_max":         state["dte_max"],
            "auto_schedule":       state["auto_schedule"],
            "news_filter_enabled": state["news_filter_enabled"],
            "timestamp":           datetime.now(ET).strftime("%H:%M:%S ET"),
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


# ── Cached lookups ────────────────────────────────────────────────────────────
_vix_cache:    dict = {"value": None, "ts": 0.0}
# Per-symbol prior-levels cache: symbol -> {"value": dict, "ts": monotonic}
_levels_cache: dict[str, dict] = {}
_levels_lock = threading.Lock()


def _cached_vix() -> float | None:
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
        price, chg_pct = trader.get_symbol_price(state["active_symbol"])
        if price is not None:
            with _state_lock:
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
    Gated on streaming + at least one authenticated client connected."""
    while True:
        try:
            with _state_lock:
                should_run = (state["logged_in"]
                              and state["streaming"]
                              and len(authenticated_sids) > 0)
            if should_run:
                refresh_prices()
                emit_state()
        except Exception as e:
            log.warning(f"price_ticker iteration failed: {e}")
        socketio.sleep(TICKER_INTERVAL_SEC)


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
        security_log.warning(f"Failed Alpaca login from {ip}: {err}")
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
    refresh_account()
    refresh_prices()
    socketio.emit("login_result", {"success": True})
    emit_state()
    log.info(f"Connected to Alpaca {'PAPER' if paper else 'LIVE'} — equity ${float(account.equity):,.2f}")


@socketio.on("logout")
@require_auth
def on_logout():
    # No real "logout" with Alpaca — just clear local clients/state
    trader.TRADING_CLIENT = None
    trader.DATA_CLIENT    = None
    trader.OPTION_CLIENT  = None
    with _state_lock:
        authenticated_sids.discard(request.sid)
        state["logged_in"]       = False
        state["morning_running"] = False
        state["evening_running"] = False
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


@socketio.on("set_session_times")
@require_auth
def on_set_session_times(data):
    """Update morning_end and/or evening_end times. Format HH:MM (24h)."""
    try:
        m_end = data.get("morning_end")
        e_end = data.get("evening_end")
        if m_end:
            validate_time(m_end)            # raises if invalid
            state["morning_end"] = m_end
            log.info(f"Morning session end time set to {m_end} ET")
        if e_end:
            validate_time(e_end)
            state["evening_end"] = e_end
            log.info(f"Evening session end time set to {e_end} ET")
        emit_state()
    except ValueError as e:
        socketio.emit("log", {"message": f"Invalid time: {e}", "level": "WARNING"})


def _launch_morning(sym: str = None) -> None:
    """Start the morning session thread. Safe to call from any thread."""
    global morning_thread
    with _state_lock:
        if state["morning_running"]:
            return
        if sym is None:
            sym = state["active_symbol"]
        filter_on = state["news_filter_enabled"]

    if filter_on:
        vetoed, reason = news_filter.check_news_sentiment(sym)
        if vetoed:
            log.warning(f"Morning session blocked by news filter: {reason}")
            socketio.emit("log", {"msg": f"⚠ News filter blocked morning session: {reason}", "level": "warning"})
            return

    with _state_lock:
        state["morning_running"] = True
        state["morning_symbol"]  = sym
    trader.STOP_MORNING.clear()
    _ensure_awake()
    emit_state()

    def run():
        try:
            eh, em = validate_time(state["morning_end"])
            log.info("=" * 50)
            log.info(f"MORNING SESSION STARTED ({sym}) — runs until {eh:02d}:{em:02d} ET")
            log.info("=" * 50)
            prior = _cached_prior_levels(sym)
            vix   = _cached_vix()
            trader.morning_session(prior, vix, stop_event=trader.STOP_MORNING,
                                   end_hour=eh, end_minute=em, symbol=sym)
        except Exception as e:
            log.error(f"Morning session error: {e}")
        finally:
            with _state_lock:
                state["morning_running"] = False
                state["morning_symbol"]  = None
            _release_awake()
            refresh_account()
            emit_state()

    morning_thread = threading.Thread(target=run, daemon=True)
    morning_thread.start()


def _launch_evening(sym: str = None) -> None:
    """Start the evening session thread. Safe to call from any thread."""
    global evening_thread
    with _state_lock:
        if state["evening_running"]:
            return
        if sym is None:
            sym = state["active_symbol"]
        filter_on = state["news_filter_enabled"]

    if filter_on:
        vetoed, reason = news_filter.check_news_sentiment(sym)
        if vetoed:
            log.warning(f"Evening session blocked by news filter: {reason}")
            socketio.emit("log", {"msg": f"⚠ News filter blocked evening session: {reason}", "level": "warning"})
            return

    with _state_lock:
        state["evening_running"] = True
        state["evening_symbol"]  = sym
    trader.STOP_EVENING.clear()
    _ensure_awake()
    emit_state()

    def run():
        try:
            eh, em = validate_time(state["evening_end"])
            log.info("=" * 50)
            log.info(f"EVENING SESSION STARTED ({sym}) — runs until {eh:02d}:{em:02d} ET")
            log.info("=" * 50)
            prior = _cached_prior_levels(sym)
            trader.evening_session(prior, stop_event=trader.STOP_EVENING,
                                   end_hour=eh, end_minute=em, symbol=sym)
        except Exception as e:
            log.error(f"Evening session error: {e}")
        finally:
            with _state_lock:
                state["evening_running"] = False
                state["evening_symbol"]  = None
            _release_awake()
            refresh_account()
            emit_state()

    evening_thread = threading.Thread(target=run, daemon=True)
    evening_thread.start()


def scheduler():
    """Background task: auto-start sessions at market open/close on weekdays."""
    morning_fired_on = None
    evening_fired_on = None

    while True:
        socketio.sleep(30)
        now = datetime.now(ET)

        if now.weekday() > 4:   # skip weekends
            continue

        with _state_lock:
            if not state["logged_in"] or not state["auto_schedule"]:
                continue
            sym = state["active_symbol"]

        today = now.date()
        h, m  = now.hour, now.minute

        mh, mm = MORNING_AUTO_START
        if (h, m) == (mh, mm) and morning_fired_on != today:
            morning_fired_on = today
            log.info("Auto-scheduler: starting morning session")
            _launch_morning(sym)

        eh, em = EVENING_AUTO_START
        if (h, m) == (eh, em) and evening_fired_on != today:
            evening_fired_on = today
            log.info("Auto-scheduler: starting evening session")
            _launch_evening(sym)


@socketio.on("start_morning")
@require_auth
def on_start_morning():
    _launch_morning()


@socketio.on("stop_morning")
@require_auth
def on_stop_morning():
    trader.STOP_MORNING.set()
    state["morning_running"] = False
    log.info("Morning session stopped by user.")
    emit_state()


@socketio.on("start_evening")
@require_auth
def on_start_evening():
    _launch_evening()


@socketio.on("stop_evening")
@require_auth
def on_stop_evening():
    trader.STOP_EVENING.set()
    state["evening_running"] = False
    log.info("Evening session stopped by user.")
    emit_state()


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
    log.info(f"News filter {'enabled' if state['news_filter_enabled'] else 'disabled'}")
    emit_state()


@socketio.on("refresh")
@require_auth
def on_refresh():
    refresh_account()
    refresh_prices()
    emit_state()


_VALID_TIMEFRAMES = frozenset({"1D", "5D", "1M", "3M", "1Y", "5Y"})

# Chart-bar cache: (symbol, timeframe) -> (bars_list, monotonic_ts)
_chart_cache: dict[tuple[str, str], tuple[list, float]] = {}
_chart_cache_lock = threading.Lock()


def _cached_chart_bars(timeframe: str, symbol: str) -> list:
    """Cache chart bars per (symbol, timeframe) for CHART_CACHE_TTL_SEC.
    Avoids re-fetching the same window when the user toggles tabs/timeframes rapidly."""
    key = (symbol, timeframe)
    now = time.monotonic()
    with _chart_cache_lock:
        cached = _chart_cache.get(key)
        if cached and now - cached[1] < CHART_CACHE_TTL_SEC:
            return cached[0]
    bars = trader.fetch_chart_bars(timeframe, symbol)
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


@socketio.on("get_chart_data")
@require_auth
def on_get_chart_data(data=None):
    """Return bars + signal markers for the active symbol & requested timeframe."""
    timeframe = (data or {}).get("timeframe", "1D")
    if timeframe not in _VALID_TIMEFRAMES:
        timeframe = "1D"
    with _state_lock:
        active = state["active_symbol"]
    symbol = (data or {}).get("symbol") or active
    if symbol not in VALID_SYMBOLS:
        symbol = "SPY"
    try:
        bars = _cached_chart_bars(timeframe, symbol)
        with _state_lock:
            # Show only the markers tagged for this symbol.
            # Older markers without a `symbol` key default to SPY for back-compat.
            signals = [
                m for m in signal_history
                if m.get("symbol", "SPY") == symbol
            ]
        socketio.emit("chart_data", {
            "bars":      bars,
            "signals":   signals,
            "timeframe": timeframe,
            "symbol":    symbol,
        })
    except Exception as e:
        log.warning(f"Chart data error: {e}", exc_info=True)
        socketio.emit("chart_data", {"bars": [], "signals": [], "timeframe": timeframe, "symbol": symbol})


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
    # One last state push so UI knows it stopped
    socketio.emit("state", {
        "logged_in":       state["logged_in"],
        "morning_running": state["morning_running"],
        "evening_running": state["evening_running"],
        "streaming":       False,
        "dry_run":         state["dry_run"],
        "account_value":   state["account_value"],
        "buying_power":    state["buying_power"],
        "spy_price":       state["spy_price"],
        "spy_change_pct":  state["spy_change_pct"],
        "vix":             state["vix"],
        "trades_today":    state["trades_today"],
        "timestamp":       datetime.now(ET).strftime("%H:%M:%S ET"),
    })
    log.info("Live stream paused — UI feed stopped (sessions still run)")


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    socketio.start_background_task(price_ticker)
    socketio.start_background_task(scheduler)

    print("\n" + "=" * 55)
    print("  SPY Auto Trader — Dashboard")
    print("  URL  : http://localhost:5000")
    print("  Logs : spy_trader.log  |  security.log")
    print("=" * 55 + "\n")

    socketio.run(
        app,
        host="127.0.0.1",     # Localhost only — not reachable from outside
        port=5000,
        debug=False,
        allow_unsafe_werkzeug=True,
        log_output=False,
    )
