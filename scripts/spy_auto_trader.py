#!/usr/bin/env python3
"""
Auto Trader — Alpaca Edition
============================
Sessions:
  Morning (9:30–10:00 ET): Opening Range Breakout + Gap Fade
  Evening (3:00–3:30 ET) : VWAP + Momentum Close

Symbols   : SPY, AMZN, GOOG, MSFT, NVDA, META (active tab determines what trades)
Indicators: VWAP, EMA9/21/200, RSI, MACD, Bollinger Bands, ATR
Filters   : VIX level, lunch-hour block, gap size, volume, PDT counter
Risk      : 3% account per trade, ATR-based stops, partial exits at +50%

Broker    : Alpaca (alpaca-py SDK)
Modes     : Paper trading (default) or Live trading

Safety stack:  PAPER_MODE (broker-level fake account) is the primary safety.
               DRY_RUN (orders never sent at all) is optional on top.
               Live-money requires explicitly setting PAPER_MODE = False at login.
"""

import os
import json
import re
import time
import resource
import threading
import logging
from datetime import datetime, timedelta, timezone, time as _dtime
from typing import Optional, Tuple
from zoneinfo import ZoneInfo

import math

import pandas as pd
import numpy as np
import yfinance as yf

# ── Fix: [Errno 24] Too many open files ───────────────────────────────────────
# yfinance 1.3 uses peewee ORM to manage two SQLite caches (tkr-tz.db and
# cookies.db). Under eventlet, every greenlet gets its own peewee connection
# that is never closed. Over hours this exhausts macOS's default per-process
# FD limit (256). Fix has two layers:
#   1. Replace both SQLite caches with yfinance's own dummy (no-op) impls.
#      TZ lookups fall back to an HTTP call per symbol (acceptable — once/run).
#      Cookie lookups regenerate on each fetch (acceptable — cookie TTL is long).
#   2. Raise the soft FD limit to 10 000 as a belt-and-suspenders safety net.
try:
    import yfinance.cache as _yfcache
    _yfcache._TzCacheManager._tz_cache         = _yfcache._TzCacheDummy()
    _yfcache._CookieCacheManager._Cookie_cache  = _yfcache._CookieCacheDummy()
    _yfcache._ISINCacheManager._isin_cache      = _yfcache._ISINCacheDummy()
except Exception:
    pass  # older yfinance versions without these classes — safe to skip

try:
    _soft, _hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    if _soft < 10_000:
        resource.setrlimit(resource.RLIMIT_NOFILE, (min(10_000, _hard), _hard))
except Exception:
    pass
# ─────────────────────────────────────────────────────────────────────────────

from alpaca.trading.client          import TradingClient
from alpaca.data.historical          import StockHistoricalDataClient
from alpaca.data.historical.option   import OptionHistoricalDataClient
from alpaca.data.requests            import (
    StockBarsRequest, StockLatestQuoteRequest, StockLatestTradeRequest,
    OptionLatestQuoteRequest,
)
from alpaca.data.timeframe           import TimeFrame, TimeFrameUnit
from alpaca.trading.requests         import (
    GetOptionContractsRequest, LimitOrderRequest, ClosePositionRequest,
)
from alpaca.trading.enums            import (
    OrderSide, TimeInForce, OrderType, ContractType, AssetStatus,
)


# ── Chart data caches (prevent repeated slow API calls per chart refresh) ─────
# fetch_daily_ema200: 400d yfinance fetch — only changes once/day.
# fetch_prior_day_levels: Alpaca daily-bars call — only changes once/day.
_EMA200_CACHE:        dict[str, tuple] = {}   # sym -> (value, mono_ts)
_PRIOR_LEVELS_CACHE:  dict[str, tuple] = {}   # sym -> (dict,  mono_ts)
_EMA200_TTL       = 3_600.0   # 1 h — daily value, stable all session
_PRIOR_LEVELS_TTL = 3_600.0   # 1 h — prior-day H/L/C never changes intraday

# ── Stop events & approval callback ───────────────────────────────────────────
# Legacy names kept for import compatibility; app.py now uses per-symbol events.
STOP_MORNING = threading.Event()
STOP_EVENING = threading.Event()
TRADE_CONFIRM_CALLBACK = None    # set by UI; signature: (details: dict) -> bool
ADVISORY_SIGNAL_CALLBACK = None  # set by app.py; fired the INSTANT a signal is
                                 # detected (before gates) so the chart shows
                                 # EVERY real signal for human decision-support.
                                 # signature: (symbol, direction, reason, price,
                                 # signal_class) -> None. Decision aid only —
                                 # does NOT place orders.
ON_FILL_CALLBACK       = None    # set by app.py; called after every successful
                                 # fill (entry) or close so the UI can refresh
                                 # account_value / buying_power / max_risk.

def _notify_fill() -> None:
    """Trigger the UI account-state refresh. Safe to call from session/monitor threads."""
    if ON_FILL_CALLBACK is None:
        return
    try:
        ON_FILL_CALLBACK()
    except Exception as e:
        log.warning(f"ON_FILL_CALLBACK error: {e}")

# ── Alpaca clients (initialized via init_clients) ─────────────────────────────
TRADING_CLIENT = None
DATA_CLIENT    = None
OPTION_CLIENT  = None
PAPER_MODE     = True

# ── Risk mode (3R-A) ──────────────────────────────────────────────────────────
# "paper_aggressive" : paper trading, UI overrides honored, max-risk for learning
# "live_disciplined" : live money, disciplined profile FORCED, UI overrides ignored
# Set automatically by init_clients() based on the paper flag.
RISK_MODE: str = "paper_aggressive"

def _is_live() -> bool:
    """True when connected to a real-money Alpaca account (not paper)."""
    return not PAPER_MODE

# ── Trade memory (ChromaDB) ────────────────────────────────────────────────────
from trade_memory import TradeMemory
TRADE_MEMORY: TradeMemory = TradeMemory(enabled=False)  # enabled on login

# ── Bull/Bear debate ────────────────────────────────────────────────────────────
import debate as _debate_mod
DEBATE_ENABLED     = False   # enabled on login if ANTHROPIC_API_KEY present
DEBATE_MIN_CONFIDENCE = _debate_mod.DEBATE_MIN_CONFIDENCE

# ── News filter ─────────────────────────────────────────────────────────────────
import news_filter as _news_mod
NEWS_FILTER_ENABLED = False   # toggled by app.py to mirror the UI checkbox


# ── Config ────────────────────────────────────────────────────────────────────
DRY_RUN         = False   # paper-trading is already simulated — no need for dry-run on top
MAX_RISK_PCT    = 0.005   # 0.5% per trade — allows ~6 concurrent vs MAX_PORTFOLIO_RISK
STOP_LOSS_PCT          = 0.50    # 50% premium stop per knowledge base (Natenberg/Saliba)
PROFIT_TARGET          = 1.00    # +100% final target — let runners run
PARTIAL_QTY_FRAC       = 0.25    # close 25% (not 50%) at the partial trigger
PARTIAL_TRIGGER_PCT    = 0.50    # take a sliver off at +50%
BREAKEVEN_TRIGGER_PCT  = 0.30    # move stop to entry once up +30%
MIN_VOL_RATIO       = 1.5         # ORB requires elevated volume in the opening phase
VWAP_MIN_VOL_RATIO  = 1.0         # VWAP momentum: looser — mid-day vol is naturally lower
RSI_OVERBOUGHT  = 70
RSI_OVERSOLD    = 30
MAX_SPREAD          = 0.05   # absolute floor: never reject for less than $0.05 spread
MAX_SPREAD_PCT      = 0.05   # 5% of mid — primary gate; the dollar floor catches cheap options
DTE_MIN         = 7
DTE_MAX         = 14
VIX_MAX         = 30
ATR_MULT_TREND  = 2.5
ATR_MULT_RANGE  = 1.5
MIN_ORB_ATR_MULT     = 0.5        # ORB acceptable when width >= 0.5 * ATR (volatility-relative)
PDT_REMAINING   = 3       # Only enforced if account.pattern_day_trader is True
                          # AND equity < $25K. Margin accounts ≥$25K are exempt.
ET              = ZoneInfo("America/New_York")

MORNING_START   = (9, 45)    # KB rule: no entries in first 15 min (9:30–9:45 = whipsaw zone)
MORNING_END     = (10, 0)
LUNCH_START     = (11, 30)
LUNCH_END       = (13, 30)
EVENING_START   = (15, 0)
EVENING_END     = (15, 30)
HARD_CLOSE           = (15, 0)
TIME_STOP_MINS         = 60       # exit stalled positions after N min if pnl in [-15%, +10%]
TIME_STOP_RANGE_LO     = -0.15    # don't time-stop a near-stop trade
TIME_STOP_RANGE_HI     = 0.10     # don't time-stop a clear winner — let runners run
POSITION_CLOSE_TIME  = (15, 50)   # hard-close all open option positions at 3:50 ET
FILL_POLL_INTERVAL   = 15         # seconds between fill-status checks
FILL_TIMEOUT_MINS    = 3          # cancel unfilled order after this many minutes
ENTRY_WALK_WAIT_SEC  = 10         # try mid for this long before walking up to ask
MAX_PORTFOLIO_RISK    = 0.03       # 3% max total deployed risk across all symbols
DAILY_LOSS_LIMIT_PCT  = 0.015     # halt new entries if down ≥ 1.5% from day-start equity
DAILY_PROFIT_LOCK_PCT = 0.02      # halt new entries when up ≥ 2% — protect the day's gains

# ── Account-size adapter (sub-$10K profile) ──────────────────────────────────
# At $5K, 0.5% per-trade = $25 risk — can't afford even 1 contract meaningfully,
# and $0.65/contract round-trip fees become a huge % of risk. The defaults
# above were tuned for a ~$100K paper account. When equity < $10K we apply the
# user's locked profile (see CONTEXT.md "Trader profile" — 20% daily DD is the
# user's explicit, aggressive choice, not a recommendation). Precedence:
# UI override > sub-10K profile > module defaults.
SUB10K_THRESHOLD             = 10000
SUB10K_MAX_RISK_PCT          = 0.04    # 4% per trade  ($200 on $5K = 1 real SPY contract)
SUB10K_MAX_PORTFOLIO_RISK    = 0.20    # 20% total deployed (fits the $1K daily budget)
SUB10K_DAILY_LOSS_LIMIT_PCT  = 0.20    # $1,000 on $5K — user's stated max daily loss
SUB10K_DAILY_PROFIT_LOCK_PCT = 0.10    # $500 daily profit lock (scaled for higher variance)
MIN_TRADE_NOTIONAL           = 300     # skip entry if mid×100×contracts < this — below
                                       # it, ~$1.30 round-trip friction eats >0.4% of notional
MAX_SECTOR_POSITIONS  = 2         # max concurrent open positions in the same sector
GLOBAL_COOLDOWN_SEC   = 60        # min seconds between ANY two entries (across all symbols)
WHIPSAW_COOLDOWN_SEC  = 900       # 15min — block opposite-direction signals after a fired one
MAX_DAILY_ENTRIES     = 8         # hard cap on new entries per day; after this, manage-only
# ── PDT (Pattern Day Trader) — sub-$25K accounts ─────────────────────────────
# FINRA: a sub-$25K margin account that does 4+ day-trades in 5 rolling
# business days gets flagged + restricted for 90 days. We enforce our OWN
# count because Alpaca PAPER accounts do NOT set pattern_day_trader / may not
# honor daytrade_count — so the existing pdt_check() (which trusts Alpaca's
# flag) silently never fires on paper. Live day 1 on a real $5K account = lock.
# PDT_RULE_ENABLED — operator switch, NOT a hardcoded "the law changed".
# Set False = stop self-enforcing the FINRA sub-$25K pattern-day-trader cap
# (per operator's call that the rule is being eliminated mid-2026). When False:
#   • pdt_sub25k_ok() never blocks  • badge shows exempt
#   • sub-$25K accounts use the DEFAULT MAX_DAILY_ENTRIES (8), not the 2 throttle
# Flip back to True to instantly restore full PDT protection if the date slips.
# NOTE: paper accounts are never PDT-flagged regardless; this matters for live.
PDT_RULE_ENABLED        = False   # operator decision 2026-05-18 (was self-enforced)
PDT_ACCOUNT_THRESHOLD   = 25000   # accounts ≥ this are exempt from PDT
PDT_MAX_DAY_TRADES_5D   = 3       # 3 allowed in any rolling 5-business-day window; 4th = flag
SUB_PDT_MAX_DAILY_ENTRIES = 2     # when sub-$25K, override MAX_DAILY_ENTRIES (8 → 2)
LAST_ENTRY_HOUR       = 14        # ET — no new entries after 14:00 ET (closing-imbalance flow)
LAST_ENTRY_MINUTE     = 0
CHOP_ATR_RATIO        = 0.5       # if today's 1H ATR < 0.5× of 5-day avg → CHOP → skip trend-cont
CHOP_REGIME_TTL_SEC   = 1800      # 30min — re-evaluate regime; ATR doesn't move fast intraday

# Gap-day handling: large overnight gaps produce maximum first-30-min whipsaw.
# Block new entries until the opening range has fully formed (default 10:00 ET)
# when |open - prev_close| / prev_close exceeds this threshold.
OPEN_GAP_DELAY_PCT     = 0.01      # 1.0% gap → push first-entry to 10:00 ET

# Friday / expiry-week gamma throttle: prevent buying options that expire
# inside the high-gamma final-week zone unless explicitly long-DTE.
FRIDAY_MIN_DTE         = 10        # On Fridays, require 10+ DTE on new entries

SECTOR_MAP: dict[str, str] = {
    "SPY": "index",  "QQQ": "index",  "IWM": "index",  "DIA": "index",
    "AMZN": "tech",  "GOOG": "tech",  "META": "tech",
    "MSFT": "tech",  "NVDA": "tech",  "AAPL": "tech",
}
ETF_SYMBOLS = {"SPY", "QQQ", "IWM", "DIA"}
MIN_OPTION_OI_ETF    = 500        # ETFs have deep OI — require it to ensure tight spreads
MIN_OPTION_OI_STOCK  = 200        # single stocks: lower floor, but still 2× the original
MIN_OPTION_VOLUME    = 10         # minimum contracts traded today at the strike
IV_RANK_MAX          = 70         # skip buying options when IVR > 70% (extreme premium only)
IV_RANK_WARN         = 50         # log a caution when IVR is in the 50–70% zone
IV_RANK_SPREAD       = 30         # KB §2: IVR ≥ 30% → route to debit spread, not naked
DELTA_TARGET_MIN     = 0.40       # prefer contracts with delta in [0.40, 0.65]
DELTA_TARGET_MAX     = 0.65       # outside this range we still trade but log a warning
IV_RANK_REFRESH_MIN  = 60         # re-fetch IV rank every N minutes during a session
STOP_CONFIRM_TICKS   = 2          # require N consecutive monitor cycles below stop before exit

# Trailing stop after T1 (partial close): rather than holding a static T2,
# trail the stop on the remaining contracts at TRAIL_GIVE_BACK below the highest
# mid seen since the partial fired. Lets winners run but locks in gains.
TRAIL_GIVE_BACK_PCT     = 0.20    # give back 20% of premium from the high-water mark
TRAIL_MIN_STOP_AT_ENTRY = True    # never let the trailing stop fall back below entry

# Exchange + clearing fees per option contract (Alpaca options are commission-free
# but exchange/ORF/OCC fees still apply). $0.65 is a conservative round-trip estimate.
OPTION_FEE_PER_CONTRACT = 0.65

# ── Data freshness tracker ────────────────────────────────────────────────────
# Free retail data is delayed (yfinance: ~15 min for bars, VIX, news). Without
# explicit tracking, we have no idea whether a "buy now" signal is reacting to
# data that's 30 seconds old or 30 minutes old. This module-level dict stamps
# every successful fetch so we can:
#   1. Refuse trades when critical data exceeds a freshness threshold
#   2. Surface per-source ages in the UI (red/yellow/green)
#   3. Log a warning when a stale source is consulted for a decision
# Sources are namespaced as "kind:symbol" e.g. "bars:SPY", "price:NVDA", "vix",
# "option_quote:SPY", "news:META".
# key -> (timestamp, source_tag). The key is canonical ("bars:SPY", "vix", "price:NVDA")
# and the source_tag describes where the data came from ("alpaca", "yfinance",
# "alpaca_chain") for UI display. The gate logic only cares about the canonical key.
_data_freshness: dict[str, tuple[float, str]] = {}
_freshness_lock = threading.Lock()

# Per-source max-age (seconds) before stale_data_check refuses a new entry.
# Tuned to the strategy: 5-min bars can be 5 min old; option quotes must be live.
DATA_MAX_AGE_SEC: dict[str, int] = {
    "bars":          360,    # 5-min bar + 1 min refresh tolerance
    "price":         90,     # spot price for sizing/sanity
    "option_quote":  30,     # entry/exit decisions ride on this — must be live
    "vix":           600,    # vol regime changes slowly; 10 min OK
    "news":          900,    # 15 min cache anyway; align with that
}

def stamp_freshness(key: str, source_tag: str = "") -> None:
    """Record that `key` was fetched successfully right now from `source_tag`.

    `key` is canonical ("bars:SPY", "vix", "price:NVDA") — what stale_data_check
    looks up. `source_tag` is for UI display ("alpaca", "yfinance", "alpaca_chain").
    """
    with _freshness_lock:
        _data_freshness[key] = (time.time(), source_tag)

def get_freshness_snapshot() -> dict[str, dict]:
    """Snapshot of all tracked sources for the UI.
    Returns: {key: {"age_sec": float, "stale": bool, "max_age": int, "source": str}}.
    """
    now = time.time()
    out = {}
    with _freshness_lock:
        for key, (ts, source_tag) in _data_freshness.items():
            age = round(now - ts, 1)
            kind = key.split(":", 1)[0]
            max_age = DATA_MAX_AGE_SEC.get(kind, 600)
            out[key] = {
                "age_sec": age,
                "stale":   age > max_age,
                "max_age": max_age,
                "source":  source_tag,
            }
    return out

def stale_data_check(symbol: str, kinds: tuple = ("price", "option_quote")) -> bool:
    """Return True if all `kinds` for `symbol` are fresh enough to trade on.

    Called as an entry gate. Defaults to checking spot price and option quote —
    the two pieces of data we actually trade against. Bars feed signal direction
    but we tolerate a few minutes of lag there since the strategy is bar-based.
    """
    sym = symbol.upper()
    now = time.time()
    with _freshness_lock:
        for kind in kinds:
            key = f"{kind}:{sym}" if kind != "vix" else "vix"
            entry = _data_freshness.get(key)
            max_age = DATA_MAX_AGE_SEC.get(kind, 600)
            if entry is None:
                log.warning(f"  ⛔ Stale data: {key} never fetched — refusing entry")
                return False
            ts, _src = entry
            age = now - ts
            if age > max_age:
                log.warning(
                    f"  ⛔ Stale data: {key} is {age:.0f}s old "
                    f"(max {max_age}s) — refusing entry"
                )
                return False
    return True


# ── Greeks helpers ───────────────────────────────────────────────────────────
def bs_delta(spot: float, strike: float, tte_days: float,
             iv: float, option_type: str = "call") -> float:
    """Black-Scholes delta approximation.

    spot       : underlying price
    strike     : option strike
    tte_days   : calendar days until expiry
    iv         : implied volatility as a decimal (e.g. 0.18 for 18%)
    option_type: "call" or "put"

    Returns delta in [0, 1] for calls, [-1, 0] for puts.
    Falls back to 0.50 on any math error.
    """
    try:
        if tte_days <= 0 or iv <= 0 or spot <= 0 or strike <= 0:
            return 0.50
        T = tte_days / 365.0
        r = 0.05   # approximate risk-free rate
        d1 = (math.log(spot / strike) + (r + 0.5 * iv ** 2) * T) / (iv * math.sqrt(T))
        # Standard normal CDF approximation (Abramowitz & Stegun)
        def _norm_cdf(x):
            sign = 1 if x >= 0 else -1
            x = abs(x)
            t = 1.0 / (1.0 + 0.2316419 * x)
            poly = t * (0.319381530
                        + t * (-0.356563782
                               + t * (1.781477937
                                      + t * (-1.821255978
                                             + t * 1.330274429))))
            return 0.5 + sign * (0.5 - math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi) * poly)
        if option_type == "call":
            return round(_norm_cdf(d1), 3)
        else:
            return round(_norm_cdf(d1) - 1, 3)
    except Exception:
        return 0.50


# ── Logging ───────────────────────────────────────────────────────────────────
from logging.handlers import RotatingFileHandler


class _DedupFilter(logging.Filter):
    """Collapse repeated identical log messages into one + a counter.

    First occurrence passes through normally. Repeats of the same (levelname,
    message) within DEDUP_WINDOW_SEC are suppressed; the first message after
    the window expires emits a summary line "(prev message repeated N times)".
    """
    DEDUP_WINDOW_SEC = 60.0
    MAX_REPEAT_REPORT = 10000

    def __init__(self) -> None:
        super().__init__()
        self._last_key: Optional[tuple] = None
        self._last_ts: float = 0.0
        self._repeat_count: int = 0

    def filter(self, record: logging.LogRecord) -> bool:
        key = (record.levelname, record.getMessage())
        now = time.time()
        if key == self._last_key and (now - self._last_ts) < self.DEDUP_WINDOW_SEC:
            self._repeat_count += 1
            if self._repeat_count > self.MAX_REPEAT_REPORT:
                return False
            return False
        if self._repeat_count > 0 and self._last_key is not None:
            summary = logging.LogRecord(
                name=record.name,
                level=logging.getLevelName(self._last_key[0]),
                pathname=record.pathname,
                lineno=record.lineno,
                msg=f"(previous message repeated {self._repeat_count} times)",
                args=None,
                exc_info=None,
            )
            self._repeat_count = 0
            logging.getLogger(record.name).handle(summary)
        self._last_key = key
        self._last_ts = now
        return True


_LOG_FMT = "%(asctime)s ET %(levelname)-8s  %(message)s"
_LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"


class _ETFormatter(logging.Formatter):
    """Force log timestamps to Eastern Time so they line up with market hours."""
    _et = ZoneInfo("America/New_York")

    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created, tz=self._et)
        return dt.strftime(datefmt or _LOG_DATEFMT)


_log_formatter = _ETFormatter(_LOG_FMT, datefmt=_LOG_DATEFMT)

_main_handler = RotatingFileHandler("auto_trader.log", maxBytes=10_000_000, backupCount=5)
_main_handler.setFormatter(_log_formatter)
_main_handler.setLevel(logging.INFO)

_err_handler = RotatingFileHandler("errors.log", maxBytes=5_000_000, backupCount=5)
_err_handler.setFormatter(_log_formatter)
_err_handler.setLevel(logging.ERROR)
_err_handler.addFilter(_DedupFilter())


class _WebhookAlertHandler(logging.Handler):
    """Best-effort webhook poster for ERROR-level logs.

    Picks up the URL from $ALERT_WEBHOOK_URL (Slack-compatible JSON: {"text": "..."}
    works for Discord and Slack incoming webhooks). Rate-limited to MIN_ALERT_GAP
    seconds between posts so a burst doesn't spam the channel.
    """
    MIN_ALERT_GAP_SEC = 60.0

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self._last_sent: float = 0.0
        self._url: Optional[str] = os.environ.get("ALERT_WEBHOOK_URL", "").strip() or None

    def emit(self, record: logging.LogRecord) -> None:
        if not self._url:
            return
        now = time.time()
        if (now - self._last_sent) < self.MIN_ALERT_GAP_SEC:
            return
        try:
            import json as _json
            import urllib.request
            payload = _json.dumps({"text": f"[SPY Trader] {record.levelname}: {record.getMessage()[:500]}"})
            req = urllib.request.Request(
                self._url,
                data=payload.encode(),
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=3).read()
            self._last_sent = now
        except Exception:
            pass  # Never let logging crash the app


_webhook_handler = _WebhookAlertHandler()

_stream_handler = logging.StreamHandler()
_stream_handler.setFormatter(_log_formatter)
_stream_handler.setLevel(logging.INFO)

_root = logging.getLogger()
_root.setLevel(logging.INFO)
# Idempotent: a re-import / importlib.reload must NOT stack a second set of
# handlers (that was the duplicate-log-line root cause — TODO §P3). The
# sentinel attribute survives on the root logger object across re-imports.
if not getattr(_root, "_spy_handlers_installed", False):
    for h in list(_root.handlers):
        _root.removeHandler(h)
    _root.addHandler(_main_handler)
    _root.addHandler(_err_handler)
    _root.addHandler(_stream_handler)
    _root.addHandler(_webhook_handler)
    _root._spy_handlers_installed = True

log = logging.getLogger(__name__)

# Silence yfinance's own logger — it shouts ERROR for "delisted" tickers like
# ^PCALL/^PCRATIO that we already handle with try/except and graceful fallbacks.
# The bulk-download path emits stderr too, so suppress that as well.
logging.getLogger("yfinance").setLevel(logging.CRITICAL)
logging.getLogger("yfinance.utils").setLevel(logging.CRITICAL)
logging.getLogger("yfinance.data").setLevel(logging.CRITICAL)
logging.getLogger("peewee").setLevel(logging.CRITICAL)   # yfinance cache backend


# ── Client init ───────────────────────────────────────────────────────────────
def init_clients(api_key: str, api_secret: str, paper: bool = True):
    """
    Initialize Alpaca clients. Called by app.py after the user enters credentials.
    Returns (account, success_bool, error_msg_or_None).
    """
    global TRADING_CLIENT, DATA_CLIENT, OPTION_CLIENT, PAPER_MODE, RISK_MODE
    # ── Go-live gate (§P1-F) ── real money requires a fully-signed
    # GO_LIVE_CHECKLIST.md. Paper mode is never gated.
    if not paper:
        ready, missing = check_go_live_readiness()
        if not ready:
            n = len(missing)
            preview = "; ".join(missing[:5]) + (f" …(+{n-5} more)" if n > 5 else "")
            msg = (f"LIVE login refused — GO_LIVE_CHECKLIST.md has {n} "
                   f"unchecked item(s): {preview}")
            log.warning(f"🚫 {msg}")
            return None, False, msg
        log.warning("✅ Go-live checklist fully signed — LIVE mode permitted.")
    try:
        PAPER_MODE      = paper
        RISK_MODE       = "paper_aggressive" if paper else "live_disciplined"
        TRADING_CLIENT  = TradingClient(api_key, api_secret, paper=paper)
        DATA_CLIENT     = StockHistoricalDataClient(api_key, api_secret)
        OPTION_CLIENT   = OptionHistoricalDataClient(api_key, api_secret)
        # Verify by fetching account
        account = TRADING_CLIENT.get_account()
        return account, True, None
    except Exception as e:
        TRADING_CLIENT = DATA_CLIENT = OPTION_CLIENT = None
        return None, False, str(e)


_GO_LIVE_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "GO_LIVE_CHECKLIST.md")

def check_go_live_readiness() -> tuple[bool, list[str]]:
    """Parse GO_LIVE_CHECKLIST.md. Returns (ready, unchecked_lines).

    ready iff: every checkbox is [x] AND the 'Last reviewed' line is not
    'never'. Fail-safe: if the file is missing/unreadable → NOT ready
    (never let a parse error silently enable real money)."""
    try:
        with open(_GO_LIVE_FILE) as f:
            text = f.read()
    except Exception as e:
        return False, [f"GO_LIVE_CHECKLIST.md unreadable ({e}) — refusing live"]
    unchecked = []
    for ln in text.splitlines():
        st = ln.strip()
        if st.startswith("- [ ]"):
            unchecked.append(st[5:].split("—")[0].strip()[:70])
    if "Last reviewed: _never_" in text or "Last reviewed: never" in text.lower():
        unchecked.append("'Last reviewed' still says never — sign + date the file")
    return (len(unchecked) == 0), unchecked


def is_authenticated() -> bool:
    return TRADING_CLIENT is not None


# ── Phase-progression log (3R-B.3) ───────────────────────────────────────────
_PHASE_LOG_FILE = os.path.expanduser("~/.spy_trader/phase_log.json")
_phase_log_lock = threading.Lock()


def phase_log_append(event: str, metrics: dict) -> None:
    """Append an audit entry to the phase-progression log (append-only).

    event   : short label e.g. "paper_incubation_start", "phase1_to_phase2"
    metrics : dict of numeric evidence e.g. {"pf_3bp": 1.31, "pf_5bp": 1.28}

    Called explicitly by the operator (or from app.py at phase-advance) so
    the audit trail proves which numbers justified going live.
    """
    entry = {
        "ts":     datetime.now(ET).isoformat(),
        "event":  event,
        "metrics": metrics,
    }
    with _phase_log_lock:
        try:
            os.makedirs(os.path.dirname(_PHASE_LOG_FILE), exist_ok=True)
            history: list = []
            if os.path.exists(_PHASE_LOG_FILE):
                with open(_PHASE_LOG_FILE) as f:
                    history = json.load(f)
            history.append(entry)
            tmp = _PHASE_LOG_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(history, f, indent=2)
            os.replace(tmp, _PHASE_LOG_FILE)
            log.info(f"[phase-log] {event} — {metrics}")
        except Exception as e:
            log.warning(f"phase_log_append failed: {e}")


def init_memory(enabled: bool = True) -> None:
    """Enable/disable ChromaDB trade memory. Called from app.py on login/toggle."""
    global TRADE_MEMORY
    TRADE_MEMORY = TradeMemory(enabled=enabled)


def init_debate(enabled: bool = True) -> None:
    """Enable/disable the bull/bear debate layer. Called from app.py on login/toggle."""
    global DEBATE_ENABLED
    key_present = bool(os.environ.get("ANTHROPIC_API_KEY", ""))
    DEBATE_ENABLED = enabled and key_present
    if enabled and not key_present:
        log.warning("Debate: ANTHROPIC_API_KEY not set — debate will stay disabled")


def init_news_filter(enabled: bool = True) -> None:
    """Enable/disable per-signal news re-check. Called from app.py on toggle."""
    global NEWS_FILTER_ENABLED
    NEWS_FILTER_ENABLED = enabled


def news_check_ok(symbol: str) -> bool:
    """Returns True if news is clean (or filter disabled). Cached for 10 min.

    Called immediately before placing each entry — fixes the bug where the
    session-start news check missed mid-session halt headlines.
    """
    if not NEWS_FILTER_ENABLED:
        return True
    try:
        vetoed, reason = _news_mod.check_news_sentiment_cached(symbol)
        if vetoed:
            log.warning(f"  ⛔ News veto at signal time ({symbol}): {reason}")
            return False
    except Exception as e:
        log.warning(f"news_check_ok({symbol}) failed: {e} — letting trade proceed")
    return True


# ── Market data ───────────────────────────────────────────────────────────────
# Data source (locked 2026-05-15): yfinance for full-day OHLCV history +
# Alpaca free latest-trade endpoint to patch the forming bar to real-time.
# The old sticky-yfinance pin was removed — it existed to prevent mixing
# Alpaca-bars + yfinance-bars mid-day, but Alpaca's free tier has no
# stock-bars entitlement at all, so there's only one bar source now and
# nothing to drift against. See _alpaca_latest_price() docstring for the
# full diagnosis.


def _alpaca_latest_price(symbol: str) -> Optional[float]:
    """Real-time last trade price from Alpaca's free latest-trade endpoint.

    DIAGNOSIS 2026-05-15: Alpaca's free "Basic" market-data plan has ZERO
    entitlement to the historical stock-bars endpoint (get_stock_bars returns
    0 bars for every symbol incl. SPY, today AND yesterday — not an embargo).
    But get_stock_latest_trade WORKS in real-time on the same free tier (same
    entitlement as option quotes). We use it to patch the forming bar's close
    so a 5-min-bar swing system is effectively real-time on free data.
    """
    if DATA_CLIENT is None:
        return None
    try:
        lt = DATA_CLIENT.get_stock_latest_trade(
            StockLatestTradeRequest(symbol_or_symbols=[symbol], feed="iex")
        )
        if symbol in lt and lt[symbol].price > 0:
            return float(lt[symbol].price)
    except Exception as e:
        log.debug(f"_alpaca_latest_price({symbol}): {type(e).__name__}: {e}")
    return None


def fetch_bars(symbol: str = "SPY", interval_min: int = 5):
    """Fetch intraday bars for `symbol` (today's session) with the indicator stack.

    Data source: yfinance for the full-day OHLCV history (Alpaca free tier has
    no stock-bars entitlement — confirmed dead, see _alpaca_latest_price docstring).
    The most recent (forming) bar's close is then patched with Alpaca's
    real-time latest-trade price so signals fire on current price, not a
    2-3 min-stale yfinance close.
    """
    symbol = symbol.upper()
    try:
        ticker = yf.Ticker(symbol)
        yf_df  = ticker.history(period="1d", interval=f"{interval_min}m")
        if yf_df.empty:
            log.warning(f"fetch_bars({symbol}): yfinance returned 0 bars")
            return None
        yf_df = yf_df.rename(columns={
            "Open": "open_price", "High": "high_price",
            "Low":  "low_price",  "Close": "close_price",
            "Volume": "volume",
        })
        yf_df.index.name = "begins_at"
        yf_df = yf_df.reset_index()[
            ["begins_at", "open_price", "high_price", "low_price", "close_price", "volume"]
        ]
        if yf_df["begins_at"].dt.tz is None:
            yf_df["begins_at"] = yf_df["begins_at"].dt.tz_localize("UTC")
        yf_df["begins_at"] = yf_df["begins_at"].dt.tz_convert(ET)
        yf_df = yf_df.sort_values("begins_at").reset_index(drop=True)
        # Strip pre-market bars so VWAP anchors correctly at 9:30 ET.
        market_open_time = yf_df["begins_at"].iloc[0].replace(
            hour=9, minute=30, second=0, microsecond=0
        )
        yf_df = yf_df[yf_df["begins_at"] >= market_open_time].reset_index(drop=True)
        if yf_df.empty:
            log.warning(f"fetch_bars({symbol}): no bars at or after 9:30 ET")
            return None

        # ── Real-time patch: overwrite the forming bar's close with Alpaca's
        #    live last-trade price. Eliminates yfinance's 2-3 min lag on the
        #    exact bar signals evaluate. Also fix high/low if the live print
        #    exceeds the stale bar's range. $0 — uses free latest-trade endpoint.
        live_px = _alpaca_latest_price(symbol)
        src     = "yfinance"
        if live_px is not None:
            i = yf_df.index[-1]
            stale_close = yf_df.at[i, "close_price"]
            yf_df.at[i, "close_price"] = live_px
            yf_df.at[i, "high_price"]  = max(yf_df.at[i, "high_price"], live_px)
            yf_df.at[i, "low_price"]   = min(yf_df.at[i, "low_price"],  live_px)
            src = f"yfinance+live(${live_px:.2f} was ${stale_close:.2f})"

        log.info(f"fetch_bars({symbol}): {len(yf_df)} bars (from 9:30 ET) [{src}]")
        stamp_freshness(f"bars:{symbol}", source_tag="yfinance+alpaca_live" if live_px else "yfinance")
        return _add_indicators(yf_df)
    except Exception as e:
        log.warning(f"fetch_bars({symbol}): failed: {e}")
        return None


# Backward-compatible alias
def fetch_spy(interval_min: int = 5):
    return fetch_bars("SPY", interval_min)


def _add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    c = df["close_price"]; h = df["high_price"]; l = df["low_price"]

    df["tp"]     = (h + l + c) / 3
    df["tp_vol"] = df["tp"] * df["volume"]
    df["vwap"]   = df["tp_vol"].cumsum() / df["volume"].cumsum()

    df["ema9"]   = c.ewm(span=9,   adjust=False).mean()
    df["ema21"]  = c.ewm(span=21,  adjust=False).mean()
    # ema200 is filled in from daily bars by inject_daily_ema200(); placeholder here.
    if "ema200" not in df.columns:
        df["ema200"] = np.nan

    delta = c.diff()
    gain  = delta.clip(lower=0).ewm(span=14, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(span=14, adjust=False).mean()
    rs    = gain / loss.replace(0, np.inf)
    df["rsi"] = 100 - (100 / (1 + rs))

    ema12           = c.ewm(span=12, adjust=False).mean()
    ema26           = c.ewm(span=26, adjust=False).mean()
    df["macd"]      = ema12 - ema26
    df["macd_sig"]  = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_sig"]

    df["bb_mid"]   = c.rolling(20).mean()
    df["bb_std"]   = c.rolling(20).std()
    df["bb_upper"] = df["bb_mid"] + 2 * df["bb_std"]
    df["bb_lower"] = df["bb_mid"] - 2 * df["bb_std"]
    df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / df["bb_mid"]

    prev_close = c.shift(1)
    tr = pd.concat([h - l, (h - prev_close).abs(), (l - prev_close).abs()], axis=1).max(axis=1)
    df["atr"] = tr.ewm(span=14, adjust=False).mean()

    df["vol_avg20"] = df["volume"].rolling(20).mean()
    df["vol_ratio"] = df["volume"] / df["vol_avg20"].replace(0, 1)

    return df


# yfinance max lookback in calendar days per bar interval
_YF_MAX_DAYS: dict[str, int] = {
    "1m": 7, "5m": 60, "15m": 60, "30m": 60, "1h": 730, "1d": 9999, "1wk": 9999,
}

# Range token → calendar days to look back
_RANGE_DAYS: dict[str, int] = {
    "1D": 5,    # 5 cal-days guarantees we find the latest trading session
    "5D": 10,   # ~7 trading days
    "1M": 35,
    "3M": 95,
    "1Y": 370,
    "5Y": 1830,
}


def fetch_chart_bars(interval: str = "15m", range_: str = "1D", symbol: str = "SPY") -> list:
    """Fetch OHLCV bars via yfinance.

    interval  — bar size  : 1m | 5m | 15m | 30m | 1h | 1d
    range_    — time span : 1D | 5D | 1M | 3M | 1Y | 5Y
    symbol    — ticker

    1D range always filters to the most-recent trading day and includes
    pre/after-market bars so the full extended-hours session is visible.

    If the (interval, range_) combo exceeds yfinance limits (e.g. 1m bars for
    3 months), the lookback is capped to the maximum allowed — no error raised.
    """
    symbol = symbol.upper()

    # Map our interval token to the yfinance interval string
    yf_iv_map = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "1h", "1d": "1d"}
    yf_iv = yf_iv_map.get(interval, "15m")

    # Compute lookback, capping at yfinance's per-interval maximum
    days    = _RANGE_DAYS.get(range_, 10)
    max_d   = _YF_MAX_DAYS.get(yf_iv, 60)
    if days > max_d:
        log.info(f"fetch_chart_bars({symbol}): {interval}+{range_} capped at {max_d}d (yfinance limit)")
        days = max_d

    today_only = (range_ == "1D")
    prepost    = today_only          # extended hours only for single-day view

    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=f"{days}d", interval=yf_iv, prepost=prepost)

        if df.empty:
            log.warning(f"fetch_chart_bars({symbol}, {interval}+{range_}): empty response")
            return []

        # Normalise to ET timezone
        df.index = pd.to_datetime(df.index)
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        df.index = df.index.tz_convert(ET)

        if today_only:
            # Keep only the most-recent trading date (handles weekends/holidays naturally)
            last_date = df.index.max().date()
            df = df[df.index.date == last_date]

        # Two-pass build: first collect valid bars, then filter outliers.
        # yfinance pre/post-market data routinely emits single bars with wild
        # wicks (e.g. SPY pre-market print at $688 when real range is $733-$738).
        # These single bad bars destroy the chart y-axis. Drop any bar whose
        # high-low range or open-close excursion exceeds OUTLIER_PCT of its
        # close — these are almost always thin-liquidity data errors.
        OUTLIER_PCT = 0.02   # 2% intra-bar range = likely garbage on 1m/5m/15m
        rough = []
        for ts, row in df.iterrows():
            o  = float(row["Open"])
            h  = float(row["High"])
            lo = float(row["Low"])
            c  = float(row["Close"])
            if any(x != x for x in (o, h, lo, c)):   # skip NaN rows
                continue
            rough.append({
                "ts":     pd.Timestamp(ts),
                "open":   o, "high": h, "low": lo, "close": c,
                "volume": int(row["Volume"]),
            })

        # Compute median close as the reference; flag bars that diverge wildly.
        if rough:
            closes = sorted(b["close"] for b in rough)
            median_close = closes[len(closes) // 2]
        else:
            median_close = None

        out = []
        dropped = 0
        for b in rough:
            c = b["close"]
            # Drop if the bar's H-L range is unrealistic (data glitch)
            if c > 0 and (b["high"] - b["low"]) / c > OUTLIER_PCT and yf_iv in ("1m", "5m", "15m"):
                dropped += 1
                continue
            # Drop if the bar's close is wildly off the median (pre-market spike)
            if median_close and median_close > 0 and abs(c - median_close) / median_close > 0.03:
                dropped += 1
                continue
            out.append({
                "time":   int(b["ts"].timestamp()),
                "open":   round(b["open"],  2),
                "high":   round(b["high"],  2),
                "low":    round(b["low"],   2),
                "close":  round(b["close"], 2),
                "volume": b["volume"],
            })

        if dropped:
            log.info(f"fetch_chart_bars({symbol}, {interval}+{range_}): "
                     f"{len(out)} bars (dropped {dropped} outliers)")
        else:
            log.info(f"fetch_chart_bars({symbol}, {interval}+{range_}): {len(out)} bars")
        return out

    except Exception as e:
        log.warning(f"fetch_chart_bars({symbol}, {interval}+{range_}): {e}")
        return []


def chart_overlays(bars: list, symbol: str) -> dict:
    """Compute overlay series (VWAP / EMAs / volume ratio / ORB / prior levels)
    aligned to a list of chart bars. Returns a dict the UI can plot directly.

    Light implementation: doesn't reuse _add_indicators because the chart bars
    use yfinance schema (open/high/low/close) and may not align to the 5-min
    signal bars. Keeping it self-contained avoids invariant drift.
    """
    if not bars:
        return {}
    try:
        df = pd.DataFrame(bars)
        c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
        tp = (h + l + c) / 3
        cum_tpv = (tp * v).cumsum()
        cum_v   = v.cumsum().replace(0, np.nan)
        df["vwap"]   = cum_tpv / cum_v
        df["ema9"]   = c.ewm(span=9,  adjust=False).mean()
        df["ema21"]  = c.ewm(span=21, adjust=False).mean()
        df["vol_avg20"] = v.rolling(20).mean()
        df["vol_ratio"] = v / df["vol_avg20"].replace(0, 1)

        # EMA200 daily — fetched separately and broadcast as a flat horizontal line
        ema200d = fetch_daily_ema200(symbol) if "fetch_daily_ema200" in globals() else None

        # ORB: high/low of the first 30 min of the *current* trading day
        df["ts"] = pd.to_datetime(df["time"], unit="s", utc=True).dt.tz_convert(ET)
        today_df = df[df["ts"].dt.date == df["ts"].dt.date.max()]
        morning  = today_df[
            (today_df["ts"].dt.time >= _dtime(MORNING_START[0], MORNING_START[1])) &
            (today_df["ts"].dt.time <  _dtime(MORNING_END[0],   MORNING_END[1]))
        ]
        orb = {}
        if len(morning) >= 2:
            orb = {
                "high": round(float(morning["high"].max()), 2),
                "low":  round(float(morning["low"].min()),  2),
                "formed_at_ts": int(morning["time"].iloc[-1]),
            }

        # Prior day levels (best-effort)
        try:
            pl = fetch_prior_day_levels(symbol) or {}
        except Exception:
            pl = {}

        def _series(col):
            # Vectorized build — avoid iterrows() which is O(n) Python per row.
            times = df["time"].to_numpy()
            vals  = df[col].to_numpy(dtype=float, na_value=float("nan"))
            return [
                {"time": int(t), "value": None if v != v else round(float(v), 4)}
                for t, v in zip(times, vals)
            ]

        return {
            "vwap":      _series("vwap"),
            "ema9":      _series("ema9"),
            "ema21":     _series("ema21"),
            "ema200d":   round(float(ema200d), 2) if ema200d else None,
            "vol_ratio": _series("vol_ratio"),
            "orb":       orb,
            "prior_levels": {
                "prev_high":  pl.get("prev_high"),
                "prev_low":   pl.get("prev_low"),
                "prev_close": pl.get("prev_close"),
            },
        }
    except Exception as e:
        log.warning(f"chart_overlays({symbol}): {e}")
        return {}


def fetch_prior_day_levels(symbol: str = "SPY"):
    """Daily bars for prior trading day. Returns dict with H/L/C and pivot levels.

    Result is cached for _PRIOR_LEVELS_TTL seconds (1 h) — prior-day H/L/C is
    immutable once the day closes, so repeated chart refreshes don't hit Alpaca.
    """
    if not DATA_CLIENT:
        return {}
    sym = symbol.upper()
    now = time.monotonic()
    cached = _PRIOR_LEVELS_CACHE.get(sym)
    if cached and now - cached[1] < _PRIOR_LEVELS_TTL:
        return cached[0]
    try:
        now_et = datetime.now(ET)
        request = StockBarsRequest(
            symbol_or_symbols = [sym],
            timeframe         = TimeFrame.Day,
            start             = (now_et - timedelta(days=10)).astimezone(timezone.utc),
            feed              = "iex",
        )
        bars = DATA_CLIENT.get_stock_bars(request)
        sym_bars = bars[sym] if sym in bars else []
        if len(sym_bars) < 2:
            _PRIOR_LEVELS_CACHE[sym] = ({}, now)
            return {}

        prev = sym_bars[-2]
        ph, pl, pc = float(prev.high), float(prev.low), float(prev.close)
        pp = (ph + pl + pc) / 3
        levels = {
            "prev_high":  ph,  "prev_low":   pl,  "prev_close": pc,
            "pivot": round(pp, 2),
            "r1":    round(2 * pp - pl, 2),
            "s1":    round(2 * pp - ph, 2),
            "r2":    round(pp + (ph - pl), 2),
            "s2":    round(pp - (ph - pl), 2),
        }
        log.info(
            f"  {sym} key levels — PrevH={ph:.2f}  PrevL={pl:.2f}  PrevC={pc:.2f}  "
            f"Pivot={pp:.2f}  R1={levels['r1']:.2f}  S1={levels['s1']:.2f}"
        )
        _PRIOR_LEVELS_CACHE[sym] = (levels, now)
        return levels
    except Exception as e:
        log.warning(f"Could not fetch prior day levels for {sym}: {e}")
        _PRIOR_LEVELS_CACHE[sym] = ({}, now)
        return {}


def check_earnings_risk(symbol: str) -> tuple[bool, str]:
    """Return (risky, reason) if earnings fall within the active DTE window.

    Buying options when earnings land inside DTE_MIN–DTE_MAX means the
    announcement is priced into the premium — IV crush will destroy the trade
    even if price moves the right direction.

    Returns (True, reason_str) to WARN (not block) the session; caller logs it.
    SPY/QQQ/IWM are index ETFs with no earnings — always returns (False, "").
    """
    INDEX_ETFS = {"SPY", "QQQ", "IWM", "DIA", "GLD", "SLV", "TLT", "XLF",
                  "XLK", "XLE", "XLV", "XLI", "XLU", "XLRE", "XLP", "XLY", "XLB"}
    sym = symbol.upper()
    if sym in INDEX_ETFS:
        return False, ""
    try:
        ticker   = yf.Ticker(sym)
        calendar = ticker.calendar
        if not calendar:
            return False, ""

        # yfinance switched ticker.calendar from DataFrame → dict around mid-2025.
        # Old DataFrame: calendar.loc["Earnings Date"]   → row of Timestamps
        # New dict     : calendar["Earnings Date"]       → list of date objects
        if isinstance(calendar, dict):
            earnings_dates = calendar.get("Earnings Date")
            if not earnings_dates:
                return False, ""
        else:
            # DataFrame fallback for older yfinance versions
            if calendar.empty or "Earnings Date" not in calendar.index:
                return False, ""
            earnings_dates = calendar.loc["Earnings Date"]

        today = datetime.now(ET).date()
        # Normalise to iterable (dict path may give a single date)
        if not isinstance(earnings_dates, (list, tuple)) and not hasattr(earnings_dates, "__iter__"):
            earnings_dates = [earnings_dates]

        for ed in earnings_dates:
            try:
                ed_date = pd.Timestamp(ed).date()
            except Exception:
                continue
            days_out = (ed_date - today).days
            if DTE_MIN <= days_out <= DTE_MAX:
                return (True,
                    f"⚠️  EARNINGS RISK: {sym} reports in {days_out}d ({ed_date}) — "
                    f"falls inside DTE window ({DTE_MIN}–{DTE_MAX}d). "
                    f"IV crush likely post-announcement even if direction is correct.")
            if 0 <= days_out < DTE_MIN:
                return (True,
                    f"⚠️  EARNINGS IMMINENT: {sym} reports in {days_out}d ({ed_date}) — "
                    f"IV will be heavily inflated today.")
        return False, ""
    except Exception as e:
        log.warning(f"check_earnings_risk({symbol}): {e}")
        return False, ""


_vix_cache: dict = {"value": None, "ts": 0.0}  # cached VIX value + monotonic timestamp
_VIX_CACHE_TTL = 300  # use cached value for up to 5 minutes on fetch failure


def fetch_vix_live(underlying: str = "SPY") -> Optional[float]:
    """Compute a real-time VIX-equivalent from SPY option chain via Alpaca.

    Implements a simplified CBOE VIX formula on a single ~30-DTE expiry:
        σ² = (2/T) Σ [ΔK_i / K_i² · e^(rT) · Q(K_i)]  -  (1/T) · (F/K_0 - 1)²
        VIX ≈ 100 · √σ²

    Where:
        Q(K_i) = mid quote of the OTM option at strike K_i (puts for K<K_0, calls
                 for K>K_0, average at K_0)
        F      = forward index level via put-call parity at the strike with min |C-P|
        K_0    = highest strike below F
        T      = time to expiry in years

    SPY-derived vol typically tracks SPX VIX within ~1 vol point. Free, real-time
    on Alpaca's options entitlement (no SIP needed). Returns None on insufficient
    data so the caller's fail-safe path triggers.
    """
    if not TRADING_CLIENT or not OPTION_CLIENT:
        return None
    sym = underlying.upper()
    try:
        # 1. Pick the expiration closest to 30 calendar days
        today = datetime.now(ET).date()
        req = GetOptionContractsRequest(
            underlying_symbols  = [sym],
            status              = AssetStatus.ACTIVE,
            expiration_date_gte = today + timedelta(days=23),
            expiration_date_lte = today + timedelta(days=37),
            limit               = 1000,
        )
        contracts = TRADING_CLIENT.get_option_contracts(req).option_contracts or []
        if len(contracts) < 20:
            log.info(f"fetch_vix_live: only {len(contracts)} contracts in 23–37 DTE — insufficient")
            return None
        # Pick expiry closest to 30 DTE
        expiries = sorted({c.expiration_date for c in contracts},
                          key=lambda d: abs((d - today).days - 30))
        target_expiry = expiries[0]
        chain = [c for c in contracts if c.expiration_date == target_expiry]

        # 2. Get current spot — refuse if we can't price the underlying
        spot, _, _ = get_symbol_price(sym)
        if spot is None or spot <= 0:
            return None

        # 3. Filter to ±20% of spot — beyond that, options are too thin to price
        chain = [c for c in chain if abs(float(c.strike_price) - spot) / spot < 0.20]
        if len(chain) < 10:
            return None

        # 4. Batch-fetch quotes for all selected contracts
        occ_symbols = [c.symbol for c in chain]
        quotes: dict = {}
        for i in range(0, len(occ_symbols), 100):
            chunk = occ_symbols[i:i+100]
            qres  = OPTION_CLIENT.get_option_latest_quote(
                OptionLatestQuoteRequest(symbol_or_symbols=chunk)
            )
            quotes.update(qres)

        # 5. Build {strike: mid} maps for calls and puts
        call_mid: dict[float, float] = {}
        put_mid:  dict[float, float] = {}
        for c in chain:
            q = quotes.get(c.symbol)
            if not q:
                continue
            bid = float(q.bid_price or 0)
            ask = float(q.ask_price or 0)
            if bid <= 0 or ask <= 0:
                continue
            mid = (bid + ask) / 2
            strike = float(c.strike_price)
            kind = str(getattr(c, "type", "")).lower()
            if "call" in kind:
                call_mid[strike] = mid
            elif "put" in kind:
                put_mid[strike] = mid

        # 6. Forward F via put-call parity at strike with min |C - P|
        common_strikes = sorted(set(call_mid) & set(put_mid))
        if len(common_strikes) < 5:
            return None
        T = max((target_expiry - today).days, 1) / 365.0
        r = 0.05
        parity = [(k, call_mid[k] - put_mid[k]) for k in common_strikes]
        parity.sort(key=lambda x: abs(x[1]))
        k_min, cp_min = parity[0]
        F = k_min + math.exp(r * T) * cp_min

        # 7. K_0 = highest strike at or below F
        K0 = max((k for k in common_strikes if k <= F), default=common_strikes[0])

        # 8. OTM mid prices: puts for K<K0, calls for K>K0, avg at K0
        otm: dict[float, float] = {}
        for k in common_strikes:
            if k < K0 and k in put_mid:
                otm[k] = put_mid[k]
            elif k > K0 and k in call_mid:
                otm[k] = call_mid[k]
        if K0 in call_mid and K0 in put_mid:
            otm[K0] = (call_mid[K0] + put_mid[K0]) / 2

        # 9. Variance integration: ΔK_i / K_i² · e^(rT) · Q(K_i)
        used = sorted(otm)
        if len(used) < 5:
            return None
        accum = 0.0
        for i, k in enumerate(used):
            if i == 0:
                dk = used[1] - used[0]
            elif i == len(used) - 1:
                dk = used[-1] - used[-2]
            else:
                dk = (used[i+1] - used[i-1]) / 2
            accum += (dk / (k * k)) * math.exp(r * T) * otm[k]
        sigma2 = (2.0 / T) * accum - (1.0 / T) * ((F / K0 - 1.0) ** 2)
        if sigma2 <= 0:
            return None

        vix = round(100.0 * math.sqrt(sigma2), 2)
        # Sanity bounds — anything outside [5, 100] is almost certainly bad data
        if vix < 5 or vix > 100:
            log.warning(f"fetch_vix_live: computed VIX={vix} outside sane range — discarding")
            return None
        log.info(
            f"  Live VIX ({sym}): {vix:.2f}  "
            f"(expiry={target_expiry}, F=${F:.2f}, K0=${K0:.2f}, strikes={len(used)})"
        )
        return vix
    except Exception as e:
        log.warning(f"fetch_vix_live failed: {e}")
        return None


def fetch_vix():
    """Fetch VIX in priority order:
        1. fetch_vix_live  — real-time, computed from Alpaca SPY option chain
        2. yfinance ^VIX   — 15-min delayed, but covers Alpaca outages
        3. last cached     — within _VIX_CACHE_TTL
    Returns None only if all three fail (gate then blocks the session — fail-safe).
    """
    # 1. Live VIX from Alpaca options chain (real-time, free)
    val = fetch_vix_live("SPY")
    if val is not None:
        _vix_cache["value"] = val
        _vix_cache["ts"]    = time.monotonic()
        stamp_freshness("vix", source_tag="alpaca_chain")
        return val

    # 2. yfinance fallback (15-min delayed but better than blocking)
    try:
        ticker = yf.Ticker("^VIX")
        hist   = ticker.history(period="1d", interval="1m", prepost=False)
        if not hist.empty:
            val = round(float(hist["Close"].iloc[-1]), 2)
            _vix_cache["value"] = val
            _vix_cache["ts"]    = time.monotonic()
            stamp_freshness("vix", source_tag="yfinance_delayed")
            log.info(f"fetch_vix: using delayed yfinance VIX={val} (live computation failed)")
            return val
    except Exception as e:
        log.warning(f"fetch_vix yfinance fallback failed: {e}")

    # 3. Last cached
    age = time.monotonic() - _vix_cache["ts"]
    if _vix_cache["value"] is not None and age < _VIX_CACHE_TTL:
        log.warning(f"fetch_vix: using cached VIX={_vix_cache['value']} (age={age:.0f}s)")
        return _vix_cache["value"]

    log.warning("fetch_vix: no source available — VIX gate will BLOCK session (fail-safe)")
    return None


def fetch_futures_context() -> dict:
    """Fetch ES (S&P 500) and NQ (Nasdaq) futures overnight context via yfinance.

    Returns a dict with:
      es_last, es_overnight_high, es_overnight_low, es_overnight_range_pct,
      es_above_midpoint (bool), es_direction ("up"/"down"/"flat"),
      nq_last, nq_direction, futures_bias ("bull"/"bear"/"neutral")

    Called once at session start to add directional context to the log.
    Does NOT block a trade — purely informational signal.
    """
    result = {}
    for sym, key in (("ES=F", "es"), ("NQ=F", "nq")):
        try:
            ticker = yf.Ticker(sym)
            # 2-day 5-min bars covers the overnight session
            df = ticker.history(period="2d", interval="5m", prepost=True)
            if df.empty:
                continue
            df.index = pd.to_datetime(df.index)
            if df.index.tz is None:
                df.index = df.index.tz_localize("UTC")
            df.index = df.index.tz_convert(ET)

            # Overnight = bars from yesterday 18:00 ET through today 09:30 ET
            now = datetime.now(ET)
            overnight_start = now.replace(hour=18, minute=0, second=0, microsecond=0) - timedelta(days=1)
            market_open     = now.replace(hour=9,  minute=30, second=0, microsecond=0)
            overnight = df[(df.index >= overnight_start) & (df.index < market_open)]

            if overnight.empty:
                continue

            o_high  = float(overnight["High"].max())
            o_low   = float(overnight["Low"].min())
            o_range = round((o_high - o_low) / o_low * 100, 2)
            o_mid   = (o_high + o_low) / 2
            last    = float(overnight["Close"].iloc[-1])
            first   = float(overnight["Open"].iloc[0])
            direction = "up" if last > first * 1.001 else "down" if last < first * 0.999 else "flat"
            above_mid = last > o_mid

            result[f"{key}_last"]              = round(last, 2)
            result[f"{key}_overnight_high"]    = round(o_high, 2)
            result[f"{key}_overnight_low"]     = round(o_low, 2)
            result[f"{key}_overnight_range_pct"] = o_range
            result[f"{key}_above_midpoint"]    = above_mid
            result[f"{key}_direction"]         = direction
        except Exception as e:
            log.warning(f"fetch_futures_context({sym}): {e}")

    # Derive overall bias
    es_dir = result.get("es_direction", "flat")
    nq_dir = result.get("nq_direction", "flat")
    if es_dir == "up" and nq_dir in ("up", "flat"):
        result["futures_bias"] = "bull"
    elif es_dir == "down" and nq_dir in ("down", "flat"):
        result["futures_bias"] = "bear"
    else:
        result["futures_bias"] = "neutral"

    if result:
        log.info(
            f"  Futures: ES={result.get('es_last','?')} [{result.get('es_direction','?')}]  "
            f"NQ={result.get('nq_last','?')} [{result.get('nq_direction','?')}]  "
            f"Bias={result.get('futures_bias','?')}  "
            f"ES overnight range={result.get('es_overnight_range_pct','?')}%"
        )
    return result


def fetch_market_breadth() -> dict:
    """Fetch market breadth indicators: put/call ratio and sector relative strength.

    Returns a dict with:
      pcr_equity   : CBOE equity put/call ratio (>0.80 = bearish extremity/contrarian bull;
                     <0.50 = bullish extremity/contrarian bear)
      pcr_total    : Total put/call ratio (equity + index options)
      pcr_signal   : "bullish_extreme" | "bearish_extreme" | "neutral"
      qqq_vs_spy   : QQQ day change minus SPY day change (positive = tech leading)
      iwm_vs_spy   : IWM day change minus SPY day change (negative = risk-off)
      breadth_bias : "bull" | "bear" | "neutral"

    All sourced from free yfinance data.
    """
    result = {"pcr_equity": None, "pcr_total": None, "pcr_signal": "neutral",
              "qqq_vs_spy": None, "iwm_vs_spy": None, "breadth_bias": "neutral"}
    try:
        # CBOE equity put/call ratio — yfinance symbol
        for pcr_sym, pcr_key in (("^PCALL", "pcr_equity"), ("^PCRATIO", "pcr_total")):
            try:
                t = yf.Ticker(pcr_sym)
                hist = t.history(period="1d", interval="1m")
                if not hist.empty:
                    result[pcr_key] = round(float(hist["Close"].iloc[-1]), 2)
            except Exception:
                pass  # P/C ratio tickers are flaky on yfinance — silently skip

        pcr = result["pcr_equity"]
        if pcr is not None:
            if pcr > 0.80:
                result["pcr_signal"] = "bearish_extreme"   # put buyers panicking → contrarian bull
            elif pcr < 0.50:
                result["pcr_signal"] = "bullish_extreme"   # call buyers euphoric → contrarian bear

        # Relative sector strength: compare QQQ, IWM vs SPY
        tickers = yf.download("SPY QQQ IWM", period="2d", interval="1d", progress=False)
        if not tickers.empty and "Close" in tickers:
            closes = tickers["Close"]
            if len(closes) >= 2:
                chg = closes.pct_change().iloc[-1] * 100
                spy_chg = float(chg.get("SPY", 0))
                qqq_chg = float(chg.get("QQQ", 0))
                iwm_chg = float(chg.get("IWM", 0))
                result["qqq_vs_spy"] = round(qqq_chg - spy_chg, 2)
                result["iwm_vs_spy"] = round(iwm_chg - spy_chg, 2)

        # Derive breadth bias
        biases = []
        if result["pcr_signal"] == "bearish_extreme":
            biases.append("bull")   # contrarian
        elif result["pcr_signal"] == "bullish_extreme":
            biases.append("bear")   # contrarian

        qqq_rel = result.get("qqq_vs_spy")
        iwm_rel = result.get("iwm_vs_spy")
        if qqq_rel is not None and iwm_rel is not None:
            if qqq_rel > 0.3 and iwm_rel > -0.2:
                biases.append("bull")   # tech and small-caps both participating
            elif qqq_rel < -0.3 or iwm_rel < -0.5:
                biases.append("bear")   # leadership breaking down

        if biases.count("bull") > biases.count("bear"):
            result["breadth_bias"] = "bull"
        elif biases.count("bear") > biases.count("bull"):
            result["breadth_bias"] = "bear"

        pcr_str = f"{pcr:.2f}" if pcr else "n/a"
        log.info(
            f"  Market breadth: PCR(equity)={pcr_str}  [{result['pcr_signal']}]  "
            f"QQQ-SPY={result.get('qqq_vs_spy','?'):+.2f}%  "
            f"IWM-SPY={result.get('iwm_vs_spy','?'):+.2f}%  "
            f"Bias={result['breadth_bias']}"
        )
    except Exception as e:
        log.warning(f"fetch_market_breadth: {e}")

    return result


def fetch_historical_vol_baseline(symbol: str, days: int = 5, interval_min: int = 5) -> dict:
    """Return mean volume by time-of-day from the prior `days` trading sessions.

    Key  : "HH:MM" (ET), matches begins_at.strftime("%H:%M")
    Value: float — mean intraday volume for that time slot
    Used : override the NaN vol_ratio during the opening phase when the rolling-20
           average hasn't accumulated enough bars yet (needs 100 min of data).
    """
    try:
        ticker = yf.Ticker(symbol.upper())
        df = ticker.history(period=f"{days + 3}d", interval=f"{interval_min}m")
        if df.empty:
            return {}
        df.index = pd.to_datetime(df.index)
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        df.index = df.index.tz_convert(ET)
        today = datetime.now(ET).date()
        df = df[df.index.date < today]
        df = df[(df.index.hour >= 9) & (df.index.hour < 16)]
        if df.empty:
            return {}
        baseline = df.groupby(df.index.strftime("%H:%M"))["Volume"].mean().to_dict()
        log.info(f"  Vol baseline ({symbol}): {len(baseline)} slots from {days} prior sessions")
        return baseline
    except Exception as e:
        log.warning(f"fetch_historical_vol_baseline({symbol}): {e}")
        return {}


def fetch_daily_ema200(symbol: str) -> Optional[float]:
    """Compute EMA200 from the last 400 daily closes.

    Intraday 5-min bars only accumulate ~78 bars/day, so the rolling EMA200
    needs 13+ trading days to have any data and is distorted noise until then.
    A single daily EMA200 value is far more meaningful as a macro trend filter.
    Returns None if insufficient history is available.

    Result is cached for _EMA200_TTL seconds (1 h) — the daily EMA200 is
    stable all session, so repeated chart refreshes don't trigger yfinance fetches.
    """
    sym = symbol.upper()
    now = time.monotonic()
    cached = _EMA200_CACHE.get(sym)
    if cached and now - cached[1] < _EMA200_TTL:
        return cached[0]
    try:
        ticker = yf.Ticker(sym)
        df = ticker.history(period="400d", interval="1d")
        if len(df) < 201:
            log.warning(f"fetch_daily_ema200({sym}): only {len(df)} daily bars — need 201+")
            _EMA200_CACHE[sym] = (None, now)
            return None
        ema200 = round(float(df["Close"].ewm(span=200, adjust=False).mean().iloc[-1]), 2)
        log.info(f"  Daily EMA200 ({sym}): ${ema200:.2f}")
        _EMA200_CACHE[sym] = (ema200, now)
        return ema200
    except Exception as e:
        log.warning(f"fetch_daily_ema200({sym}): {e}")
        _EMA200_CACHE[sym] = (None, now)   # cache failures to avoid hammering yfinance
        return None


def inject_daily_ema200(df: pd.DataFrame, ema200_val: Optional[float]) -> pd.DataFrame:
    """Broadcast the daily EMA200 scalar into every row of the intraday df."""
    if ema200_val is not None:
        df = df.copy()
        df["ema200"] = ema200_val
    return df


def fetch_iv_rank(symbol: str) -> Tuple[Optional[float], Optional[float]]:
    """Compute IV Rank (IVR) from the past 52 weeks of the nearest ATM option IV.

    IVR = (current_iv - 52w_low_iv) / (52w_high_iv - 52w_low_iv) * 100

    Uses yfinance options chain: fetches the nearest expiry, picks the ATM
    call's impliedVolatility, then builds a rolling 1-year IV history from
    weekly closes of the underlying's HV (historical volatility) as a proxy
    when live option history isn't available.

    Returns (current_iv_pct, iv_rank_pct) or (None, None) on failure.
    current_iv_pct: e.g. 18.5 means 18.5% annualised IV
    iv_rank_pct   : 0–100; higher = more expensive relative to past year
    """
    try:
        ticker = yf.Ticker(symbol.upper())

        # --- Current IV: nearest-expiry ATM call ---
        expirations = ticker.options
        if not expirations:
            return None, None
        nearest_expiry = expirations[0]
        chain = ticker.option_chain(nearest_expiry)
        calls = chain.calls
        if calls.empty:
            return None, None

        # Current price for ATM selection
        hist_1d = ticker.history(period="1d", interval="1m")
        if hist_1d.empty:
            return None, None
        spot = float(hist_1d["Close"].iloc[-1])

        # Pick closest strike to spot
        calls = calls.copy()
        calls["dist"] = (calls["strike"] - spot).abs()
        atm_call = calls.sort_values("dist").iloc[0]
        current_iv = float(atm_call["impliedVolatility"]) * 100  # convert to %

        # --- 52-week IV history proxy: 30-day historical volatility ---
        # True option IV history requires expensive data; HV30 correlates well
        # and is derivable from free daily bars.
        daily = ticker.history(period="1y", interval="1d")
        if len(daily) < 31:
            return current_iv, None

        log_ret = np.log(daily["Close"] / daily["Close"].shift(1)).dropna()
        hv30 = log_ret.rolling(21).std() * np.sqrt(252) * 100  # annualised %
        hv30 = hv30.dropna()
        if hv30.empty:
            return current_iv, None

        iv_52w_low  = float(hv30.min())
        iv_52w_high = float(hv30.max())
        iv_range    = iv_52w_high - iv_52w_low
        if iv_range < 0.1:
            return current_iv, 50.0  # flat IV history — treat as neutral

        iv_rank = round((current_iv - iv_52w_low) / iv_range * 100, 1)
        iv_rank = max(0.0, min(100.0, iv_rank))
        log.info(
            f"  IV Rank ({symbol}): current={current_iv:.1f}%  "
            f"52w [{iv_52w_low:.1f}%–{iv_52w_high:.1f}%]  IVR={iv_rank:.0f}%"
        )
        return round(current_iv, 2), iv_rank
    except Exception as e:
        log.warning(f"fetch_iv_rank({symbol}): {e}")
        return None, None


_HTF_SLOPE_BPS_THRESHOLD = 15   # 0.15% slope over 6 bars (~3 hrs of 30-min) = real trend

def fetch_30min_trend(symbol: str) -> str:
    """Return 'bull', 'bear', or 'neutral' based on the SLOPE of the 30-min EMA21.

    A binary EMA9>EMA21 cross is laggy and noisy — by the time it flips, the move
    has typically run, and weak crosses inside chop count as "trend." Slope over
    a 6-bar window measures whether the trend is actually progressing.

    Fetches the last 5 trading days of 30-min bars (~65 bars). Called at session
    start and refreshed every IV_RANK_REFRESH_MIN minutes.
    """
    try:
        ticker = yf.Ticker(symbol.upper())
        df = ticker.history(period="5d", interval="30m")
        if df.empty or len(df) < 22:
            return "neutral"
        closes = df["Close"]
        ema21_series = closes.ewm(span=21, adjust=False).mean()
        if len(ema21_series) < 6:
            return "neutral"
        last  = float(ema21_series.iloc[-1])
        prior = float(ema21_series.iloc[-6])
        slope_pct = (last - prior) / prior * 100  # % change over ~3 hours
        slope_bps = slope_pct * 100               # basis points
        if slope_bps >= _HTF_SLOPE_BPS_THRESHOLD:
            trend = "bull"
        elif slope_bps <= -_HTF_SLOPE_BPS_THRESHOLD:
            trend = "bear"
        else:
            trend = "neutral"
        log.info(
            f"  30-min trend ({symbol}): EMA21 slope={slope_bps:+.0f}bps over 6 bars → {trend.upper()}"
        )
        return trend
    except Exception as e:
        log.warning(f"fetch_30min_trend({symbol}): {e}")
        return "neutral"


# ── Regime detector: chop vs trend ────────────────────────────────────────────
# Trend-continuation strategies bleed money in chop. Computes today's 1H ATR
# vs the 5-day average; if today is < CHOP_ATR_RATIO of average, market is
# range-bound and trend-continuation should sit out.
_chop_regime_cache: dict = {"is_chop": None, "ts": 0.0, "ratio": 0.0}

def is_chop_regime() -> bool:
    """True when SPY's 1H ATR today is significantly below its 5-day average.

    Cached for CHOP_REGIME_TTL_SEC (30min) — ATR doesn't move fast intraday and
    we don't want to thrash yfinance on every signal evaluation. Returns False
    on any fetch error (fail-OPEN — better to miss a regime call than block all
    trades because of a transient API failure).
    """
    now = time.monotonic()
    if (_chop_regime_cache["is_chop"] is not None
            and (now - _chop_regime_cache["ts"]) < CHOP_REGIME_TTL_SEC):
        return _chop_regime_cache["is_chop"]

    try:
        # 6 trading days of 1H bars (today + 5 prior)
        df = yf.Ticker("SPY").history(period="7d", interval="1h")
        if df.empty or len(df) < 30:
            return False  # insufficient data — fail open

        # ATR(14) on 1H bars
        h, l, c = df["High"], df["Low"], df["Close"]
        prev_c = c.shift(1)
        tr = pd.concat([h - l, (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
        atr = tr.ewm(span=14, adjust=False).mean()

        # Localise so we can split today vs prior days
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        df_et = df.copy()
        df_et.index = df.index.tz_convert(ET)
        atr_series = atr.copy()
        atr_series.index = df.index.tz_convert(ET)

        today = datetime.now(ET).date()
        atr_today = atr_series[atr_series.index.date == today]
        atr_prior = atr_series[atr_series.index.date <  today]

        if atr_today.empty or atr_prior.empty:
            return False  # market may not have opened yet — fail open

        today_avg = float(atr_today.mean())
        prior_avg = float(atr_prior.tail(40).mean())  # ~5 trading days × 7-8 bars
        if prior_avg <= 0:
            return False
        ratio = today_avg / prior_avg
        is_chop = ratio < CHOP_ATR_RATIO

        _chop_regime_cache.update(is_chop=is_chop, ts=now, ratio=ratio)
        regime_label = "CHOP (skip trend-cont)" if is_chop else "NORMAL/TREND"
        log.info(
            f"  Regime: SPY 1H ATR today={today_avg:.2f}  5d-avg={prior_avg:.2f}  "
            f"ratio={ratio:.2f}  → {regime_label}"
        )
        return is_chop
    except Exception as e:
        log.warning(f"is_chop_regime() error: {e} — assuming NORMAL (fail open)")
        return False


def detect_gap(df, prior_close):
    if not prior_close or df is None or df.empty:
        return 0.0, None
    today_open = float(df.iloc[0]["open_price"])
    gap_pct    = (today_open - prior_close) / prior_close * 100
    direction  = "up" if gap_pct > 0 else "down" if gap_pct < 0 else None
    return round(gap_pct, 3), direction


def opening_range(df):
    first_time = df["begins_at"].iloc[0].replace(hour=9, minute=30, second=0)
    or_end     = first_time + timedelta(minutes=15)
    or_bars    = df[df["begins_at"] <= or_end]
    if or_bars.empty:
        return None, None
    return float(or_bars["high_price"].max()), float(or_bars["low_price"].min())


# ── Account ───────────────────────────────────────────────────────────────────
def account_value():
    if not TRADING_CLIENT:
        return 0.0
    try:
        return float(TRADING_CLIENT.get_account().equity)
    except Exception:
        return 0.0


def buying_power():
    if not TRADING_CLIENT:
        return 0.0
    try:
        return float(TRADING_CLIENT.get_account().buying_power)
    except Exception:
        return 0.0


# prev_close is fetched from daily bars and only changes once per trading day.
# Cache it per symbol so we don't make a second Alpaca call on every 5-second tick.
_prev_close_cache: dict[str, tuple[float, object]] = {}   # symbol -> (prev_close, date)


def _market_session() -> str:
    """Current ET market session: 'pre', 'regular', 'after', or 'closed'."""
    now = datetime.now(ET)
    if now.weekday() >= 5:
        return "closed"
    mins = now.hour * 60 + now.minute
    if 4 * 60 <= mins < 9 * 60 + 30:
        return "pre"
    if 9 * 60 + 30 <= mins < 16 * 60:
        return "regular"
    if 16 * 60 <= mins < 20 * 60:
        return "after"
    return "closed"


def get_symbol_price(symbol: str = "SPY"):
    """Latest price for any symbol + day change % + market session.

    yfinance is primary — it uses the consolidated tape and works in extended
    hours.  Alpaca IEX is kept as a fallback only (IEX is a single exchange and
    can return stale trades for ETFs that mostly route through NYSE Arca).

    Returns: (price, chg_pct, session)  where session ∈ {'pre','regular','after','closed'}
    """
    symbol = symbol.upper()
    price      = None
    prev_close = None
    today      = datetime.now(ET).date()

    # ── yfinance primary (consolidated tape, extended hours) ─────────────────
    try:
        fi = yf.Ticker(symbol).fast_info
        raw_price = getattr(fi, "last_price", None)
        if raw_price and float(raw_price) > 0:
            price = round(float(raw_price), 2)
            stamp_freshness(f"price:{symbol}", source_tag="yfinance")
        raw_prev = getattr(fi, "previous_close", None)
        if raw_prev and float(raw_prev) > 0:
            prev_close = round(float(raw_prev), 2)
            _prev_close_cache[symbol] = (prev_close, today)
        else:
            cached = _prev_close_cache.get(symbol)
            if cached and cached[1] == today:
                prev_close = cached[0]
    except Exception as e:
        log.warning(f"get_symbol_price({symbol}) yfinance failed: {e}")

    # ── Alpaca IEX fallback (only when yfinance failed) ───────────────────────
    if price is None and DATA_CLIENT:
        try:
            trade_req  = StockLatestTradeRequest(symbol_or_symbols=[symbol], feed="iex")
            trade_data = DATA_CLIENT.get_stock_latest_trade(trade_req)
            if symbol in trade_data:
                price = float(trade_data[symbol].price)
                stamp_freshness(f"price:{symbol}", source_tag="alpaca_iex")
                log.info(f"get_symbol_price({symbol}): using Alpaca IEX fallback ${price:.2f}")
            cached = _prev_close_cache.get(symbol)
            if cached and cached[1] == today:
                prev_close = cached[0]
            elif price is not None:
                try:
                    req  = StockBarsRequest(
                        symbol_or_symbols = [symbol],
                        timeframe         = TimeFrame.Day,
                        start             = (datetime.now(timezone.utc) - timedelta(days=5)),
                        feed              = "iex",
                    )
                    bars     = DATA_CLIENT.get_stock_bars(req)
                    sym_bars = bars.get(symbol, [])
                    if len(sym_bars) >= 2:
                        prev_close = float(sym_bars[-2].close)
                        _prev_close_cache[symbol] = (prev_close, today)
                except Exception:
                    pass
        except Exception as e:
            log.warning(f"get_symbol_price({symbol}) Alpaca fallback error: {e}")

    session = _market_session()

    if price is None:
        return None, None, session

    if prev_close is None:
        prev_close = price

    chg_pct = round((price - prev_close) / prev_close * 100, 2) if prev_close else 0
    return round(price, 2), chg_pct, session


# Backward-compatible alias (returns 2-tuple for old callers)
def get_spy_price():
    price, chg, _ = get_symbol_price("SPY")
    return price, chg


# ── Options helpers ───────────────────────────────────────────────────────────
def target_expiry(symbol: str = "SPY"):
    """Find option expiry between DTE_MIN and DTE_MAX days out for `symbol`."""
    if not TRADING_CLIENT:
        return None
    symbol = symbol.upper()
    today = datetime.now(ET).date()
    try:
        request = GetOptionContractsRequest(
            underlying_symbols  = [symbol],
            status              = AssetStatus.ACTIVE,
            expiration_date_gte = today + timedelta(days=DTE_MIN),
            expiration_date_lte = today + timedelta(days=DTE_MAX),
            limit               = 100,
        )
        response = TRADING_CLIENT.get_option_contracts(request)
        contracts = response.option_contracts or []
        if not contracts:
            return None
        # Pick the closest expiry to DTE_MIN
        expiries = sorted({c.expiration_date for c in contracts})
        return expiries[0].isoformat()
    except Exception as e:
        log.warning(f"Could not fetch expiry dates for {symbol}: {e}")
        return None


def _strike_window(current_price: float) -> float:
    """Adaptive strike-window radius: wider for higher-priced underlyings.
    SPY $580 → ~$15, MSFT $420 → ~$11, META $520 → ~$13, NVDA $130 → ~$5,
    GOOG $170 → ~$5, AMZN $200 → ~$5. Floor of $5 keeps low-priced names
    from getting an empty strike list when spacing is $2.50."""
    return max(5.0, current_price * 0.025)


def find_atm_option(direction, expiry_str, current_price, symbol: str = "SPY",
                    current_iv: Optional[float] = None):
    """Find ATM call (bull) or put (bear) for `symbol` at given expiry.

    current_iv: annualised IV as a percentage (e.g. 18.5 means 18.5%).
    Used for delta scoring; falls back to 25% when None.
    """
    if not TRADING_CLIENT:
        return None, None
    symbol = symbol.upper()
    contract_type = ContractType.CALL if direction == "bull" else ContractType.PUT
    window        = _strike_window(current_price)
    lo            = round(current_price - window, 2)
    hi            = round(current_price + window, 2)

    try:
        request = GetOptionContractsRequest(
            underlying_symbols  = [symbol],
            status              = AssetStatus.ACTIVE,
            expiration_date     = datetime.fromisoformat(expiry_str).date(),
            type                = contract_type,
            strike_price_gte    = str(lo),
            strike_price_lte    = str(hi),
            limit               = 100,
        )
        response = TRADING_CLIENT.get_option_contracts(request)
        contracts = response.option_contracts or []
        if not contracts:
            log.warning(f"No {symbol} {contract_type.value} contracts in [{lo:.2f}, {hi:.2f}] for {expiry_str}")
            return None, None

        # Filter by open interest — low OI means illiquid exit.
        # NOTE: c.close_price on an option contract is the option's CLOSE PRICE
        # (a decimal like '10.85'), NOT daily volume — the old comment was wrong
        # and `int(c.close_price)` crashed on every signal with a ValueError,
        # killing every potential trade. The volume field isn't reliably populated
        # on the contract object anyway; OI is the trustworthy liquidity signal.
        min_oi = MIN_OPTION_OI_ETF if symbol in ETF_SYMBOLS else MIN_OPTION_OI_STOCK
        liquid = []
        for c in contracts:
            oi = int(c.open_interest or 0)
            if oi >= min_oi:
                liquid.append(c)
            else:
                log.info(
                    f"  Skipping {c.symbol} strike=${c.strike_price} "
                    f"OI={oi} (min {min_oi}) — too illiquid"
                )

        if not liquid:
            # Fall back to full list with a warning so we don't block trading on
            # symbols that simply have low OI reported (data can lag by a day)
            log.warning(
                f"find_atm_option({symbol}): no contracts pass OI≥{min_oi} — "
                f"falling back to full list (OI data may be stale)"
            )
            liquid = contracts

        # Compute BS delta for each liquid contract and prefer those closest to
        # DELTA_TARGET (0.50 ideal for directional bets). Sort by |delta - 0.50|
        # rather than purely by strike distance — avoids picking far-OTM contracts
        # when the ATM strike happens to be mid-spread.
        today = datetime.now(ET).date()
        expiry_date = datetime.fromisoformat(expiry_str).date()
        tte_days = max(1, (expiry_date - today).days)
        opt_type_str = "call" if contract_type == ContractType.CALL else "put"

        iv_decimal = (current_iv / 100.0) if (current_iv and current_iv > 0) else 0.25

        def _score(c):
            strike = float(c.strike_price)
            delta = bs_delta(current_price, strike, tte_days, iv=iv_decimal, option_type=opt_type_str)
            return abs(abs(delta) - 0.50)   # 0 = perfect ATM delta

        contracts_sorted = sorted(liquid, key=_score)
        c = contracts_sorted[0]
        oi_val = int(c.open_interest or 0)

        chosen_delta = bs_delta(
            current_price, float(c.strike_price), tte_days,
            iv=iv_decimal, option_type=opt_type_str
        )
        if abs(chosen_delta) < DELTA_TARGET_MIN or abs(chosen_delta) > DELTA_TARGET_MAX:
            log.warning(
                f"  Delta={chosen_delta:.2f} outside target [{DELTA_TARGET_MIN},{DELTA_TARGET_MAX}] "
                f"— best available strike=${c.strike_price}"
            )
        else:
            log.info(
                f"  Selected: {c.symbol}  strike=${c.strike_price}  "
                f"delta≈{chosen_delta:.2f}  OI={oi_val}"
            )

        return {
            "symbol":           c.symbol,        # OCC symbol (used for orders)
            "id":               c.id,
            "strike_price":     str(c.strike_price),
            "expiration_date":  c.expiration_date.isoformat(),
            "type":             opt_type_str,
            "underlying":       symbol,
            "open_interest":    oi_val,
            "delta":            chosen_delta,
        }, float(c.strike_price)
    except Exception as e:
        log.warning(f"Could not find ATM option for {symbol}: {e}")
        return None, None


def find_otm_option(direction: str, expiry_str: str, long_strike: float,
                    current_price: float, symbol: str = "SPY",
                    current_iv: Optional[float] = None):
    """Find the OTM short leg for a debit spread (KB §5).

    KB §5: "Buy ATM (delta ~0.50), sell 1–2 strikes further OTM (delta ~0.20–0.30)."
    For SPY: spread width $1–$3. Target short leg delta ~0.25.
    Returns (option_dict, strike_price) matching find_atm_option convention, or (None, None).
    """
    if not TRADING_CLIENT:
        return None, None
    symbol = symbol.upper()
    contract_type = ContractType.CALL if direction == "bull" else ContractType.PUT

    # Search window: 1–5 strikes past the long strike (KB §5: $1–$3 width for SPY)
    if direction == "bull":
        lo = round(long_strike + 0.50, 2)
        hi = round(long_strike + 5.00, 2)
    else:
        lo = round(long_strike - 5.00, 2)
        hi = round(long_strike - 0.50, 2)

    try:
        request = GetOptionContractsRequest(
            underlying_symbols  = [symbol],
            status              = AssetStatus.ACTIVE,
            expiration_date     = datetime.fromisoformat(expiry_str).date(),
            type                = contract_type,
            strike_price_gte    = str(min(lo, hi)),
            strike_price_lte    = str(max(lo, hi)),
            limit               = 20,
        )
        response  = TRADING_CLIENT.get_option_contracts(request)
        contracts = response.option_contracts or []
        if not contracts:
            log.warning(f"find_otm_option({symbol}): no OTM contracts in range [{lo:.2f}, {hi:.2f}]")
            return None, None

        min_oi = MIN_OPTION_OI_ETF if symbol in ETF_SYMBOLS else MIN_OPTION_OI_STOCK
        liquid = [c for c in contracts if int(c.open_interest or 0) >= min_oi]
        if not liquid:
            liquid = contracts  # OI data may lag; fall back

        today       = datetime.now(ET).date()
        expiry_date = datetime.fromisoformat(expiry_str).date()
        tte_days    = max(1, (expiry_date - today).days)
        opt_type_str = "call" if contract_type == ContractType.CALL else "put"
        iv_decimal   = (current_iv / 100.0) if (current_iv and current_iv > 0) else 0.25

        # Target delta ~0.25 for the short leg (KB §5: "sell 1–2 strikes OTM, delta ~0.20–0.30")
        OTM_DELTA_TARGET = 0.25

        def _score(c):
            strike = float(c.strike_price)
            delta  = bs_delta(current_price, strike, tte_days, iv=iv_decimal, option_type=opt_type_str)
            return abs(abs(delta) - OTM_DELTA_TARGET)

        contracts_sorted = sorted(liquid, key=_score)
        c = contracts_sorted[0]

        chosen_delta = bs_delta(
            current_price, float(c.strike_price), tte_days,
            iv=iv_decimal, option_type=opt_type_str
        )
        log.info(
            f"  Spread short leg: {c.symbol}  strike=${c.strike_price}  "
            f"delta≈{chosen_delta:.2f}  OI={int(c.open_interest or 0)}"
        )
        return {
            "symbol":          c.symbol,
            "id":              c.id,
            "strike_price":    str(c.strike_price),
            "expiration_date": c.expiration_date.isoformat(),
            "type":            opt_type_str,
            "underlying":      symbol,
            "open_interest":   int(c.open_interest or 0),
            "delta":           chosen_delta,
        }, float(c.strike_price)
    except Exception as e:
        log.warning(f"find_otm_option({symbol}): {e}")
        return None, None


# Time-of-day spread tightening (§P1-E). The first and last few minutes
# have 3-5× normal option spreads (opening auction unwind / closing
# imbalance). A fill there silently pays that spread as slippage. We
# tighten the % gate during those windows so only genuinely-tight books
# get through when spreads are structurally wide.
OPEN_WIDE_UNTIL  = (9, 35)    # 9:30–9:35 ET
CLOSE_WIDE_FROM  = (15, 55)   # 15:55–16:00 ET
WIDE_WINDOW_SPREAD_PCT = 0.03 # 3% (vs normal 5%) during those windows

def _in_wide_spread_window() -> bool:
    now = datetime.now(ET)
    hm = (now.hour, now.minute)
    if (9, 30) <= hm < OPEN_WIDE_UNTIL:
        return True
    if CLOSE_WIDE_FROM <= hm <= (16, 0):
        return True
    return False


def spread_acceptable(mid: float, spread: float) -> bool:
    """Spread gate: percent-relative with an absolute floor for cheap options.

    A $0.30 spread is fine on a $5 option (6%) but terrible on a $0.50 option (60%).
    Reject when spread / mid exceeds the % limit, but never reject for less than
    the MAX_SPREAD dollar floor (avoids over-rejecting cheap weeklies with $0.05 ticks).

    During the open/close wide-spread windows (§P1-E) the % limit tightens
    from 5% → 3% so we don't silently overpay the structurally-wide book.
    """
    if mid <= 0:
        return False
    pct = WIDE_WINDOW_SPREAD_PCT if _in_wide_spread_window() else MAX_SPREAD_PCT
    limit = max(MAX_SPREAD, mid * pct)
    ok = spread <= limit
    if not ok and _in_wide_spread_window():
        log.info(
            f"  ⏰ Wide-window spread gate ({pct*100:.0f}%): "
            f"spread ${spread:.2f} > ${limit:.2f} on ${mid:.2f} mid — "
            f"skipping open/close illiquidity."
        )
    return ok


def option_mid_and_spread(option):
    """Return (mid, spread, bid, ask) for an option using its OCC symbol."""
    if not OPTION_CLIENT:
        return 0.0, 999.0, 0.0, 0.0
    try:
        request = OptionLatestQuoteRequest(symbol_or_symbols=[option["symbol"]])
        result  = OPTION_CLIENT.get_option_latest_quote(request)
        quote   = result.get(option["symbol"])
        if quote:
            bid    = float(quote.bid_price or 0)
            ask    = float(quote.ask_price or 0)
            spread = round(ask - bid, 2)
            mid    = round((bid + ask) / 2, 2) if (bid > 0 and ask > 0) else 0
            if bid > 0 or ask > 0:
                # Stamp under the underlying so stale_data_check can find it.
                underlying = option.get("underlying", "").upper()
                if underlying:
                    stamp_freshness(f"option_quote:{underlying}", source_tag="alpaca")
            return mid, spread, bid, ask
    except Exception as e:
        log.warning(f"Could not fetch option quote: {e}")
    return 0.0, 999.0, 0.0, 0.0


def size_contracts(acct_val, mid_price):
    if mid_price <= 0:
        return 0
    max_risk = acct_val * eff_max_risk_pct()   # sub-$10K → 4%, else 0.5%
    # Risk at stop = STOP_LOSS_PCT of premium (not full cost).
    # Sizing on full cost wastes half the risk budget since max loss is only 50%.
    risk_per_contract = mid_price * STOP_LOSS_PCT * 100
    n = int(max_risk / risk_per_contract)
    if n == 0:
        log.warning(
            f"size_contracts: stop-risk ${risk_per_contract:.0f}/contract exceeds "
            f"budget ${max_risk:.0f} — skipping"
        )
        return 0
    # Friction floor: below MIN_TRADE_NOTIONAL the ~$1.30 round-trip fee +
    # bid/ask is too large a fraction of the trade. Trim n until notional
    # clears, or skip entirely if even 1 contract is below the floor.
    notional = mid_price * 100 * n
    if notional < MIN_TRADE_NOTIONAL:
        one_contract = mid_price * 100
        if one_contract < MIN_TRADE_NOTIONAL:
            log.warning(
                f"size_contracts: notional ${one_contract:.0f}/contract < "
                f"MIN_TRADE_NOTIONAL ${MIN_TRADE_NOTIONAL} — fee drag too high, skipping"
            )
            return 0
    log.info(
        f"  Sizing: {n} contract(s)  entry=${mid_price:.2f}  "
        f"risk/contract=${risk_per_contract:.0f}  total-risk=${risk_per_contract*n:.0f}  "
        f"notional=${mid_price*100*n:,.0f}"
    )
    return n


# ── Filters ───────────────────────────────────────────────────────────────────
def is_lunch_hour(symbol: str = "SPY") -> bool:
    """Lunch-hour block (11:30–13:30 ET) — ETFs only.

    Single stocks (NVDA/META/MSFT/etc) trade plenty during lunch with real volume,
    and the post-lunch resumption (1:00–1:30) is often the day's best risk/reward.
    The "lunch is dead" folklore is for index ETFs only.
    """
    if symbol.upper() not in ETF_SYMBOLS:
        return False
    now = datetime.now(ET)
    s   = now.replace(hour=LUNCH_START[0], minute=LUNCH_START[1], second=0)
    e   = now.replace(hour=LUNCH_END[0],   minute=LUNCH_END[1],   second=0)
    return s <= now < e


def sector_risk_check(symbol: str) -> bool:
    """Return False when MAX_SECTOR_POSITIONS already open in the same sector."""
    sector = SECTOR_MAP.get(symbol.upper(), symbol.upper())
    with _positions_lock:
        sector_count = sum(
            1 for p in _open_positions
            if p["remaining"] > 0 and SECTOR_MAP.get(p["symbol"], p["symbol"]) == sector
        )
    if sector_count >= MAX_SECTOR_POSITIONS:
        log.warning(
            f"  Sector cap: {sector_count} open {sector} positions "
            f"(max {MAX_SECTOR_POSITIONS}) — skipping {symbol} entry."
        )
        return False
    return True


def pdt_check():
    """Block new entries if PDT rule applies and we're out of day trades.

    Only relevant for sub-$25K margin accounts flagged as `pattern_day_trader`.
    For accounts ≥$25K (or anyone Alpaca hasn't flagged), Alpaca returns
    daytrade_count without enforcing a 4-in-5 cap, so we never block.

    Reads the live remaining count from Alpaca instead of trusting a static
    module constant — the previous behavior (constant `3`) was wrong for any
    sub-$25K account that had already used some day trades.
    """
    if not TRADING_CLIENT:
        return True  # no broker → no enforcement
    try:
        acct = TRADING_CLIENT.get_account()
        is_pdt = bool(getattr(acct, "pattern_day_trader", False))
        if not is_pdt:
            return True  # rule doesn't apply
        day_trades = int(getattr(acct, "daytrade_count", 0) or 0)
        remaining  = max(0, 3 - day_trades)  # PDT allows 3 in any rolling 5-day window
        if remaining <= 0:
            log.warning(f"PDT limit reached ({day_trades} day-trades used). No new entries.")
            return False
        log.info(f"PDT day trades remaining: {remaining}")
        return True
    except Exception as e:
        log.warning(f"pdt_check: account lookup failed ({e}) — allowing entry")
        return True


# ── Self-enforced PDT day-trade tracking ─────────────────────────────────────
# A "day trade" (FINRA) = open + close the SAME security on the SAME trading
# day. We record one whenever a position opened today is fully closed today.
# Persisted so the rolling 5-day count survives restarts. This is OUR
# enforcement, independent of Alpaca's pattern_day_trader flag (which paper
# never sets) — see PDT_* constants above.
_DAY_TRADES_FILE = os.path.join(os.path.expanduser("~/.spy_trader"), "day_trades.json")
_day_trades_lock = threading.Lock()


def _load_day_trades() -> list:
    try:
        if os.path.exists(_DAY_TRADES_FILE):
            with open(_DAY_TRADES_FILE) as f:
                return json.load(f)
    except Exception as e:
        log.warning(f"_load_day_trades failed: {e}")
    return []


def _record_day_trade(occ: str, opened_at: str) -> None:
    """Called from _remove_position on a FULL close. Records a day-trade only
    if the position was opened on the same trading day it closed."""
    try:
        opened_d = datetime.fromisoformat(opened_at).astimezone(ET).date()
    except Exception:
        return  # no/invalid opened_at → can't classify; skip (conservative: don't over-count)
    today = datetime.now(ET).date()
    if opened_d != today:
        return  # overnight hold → NOT a day trade
    with _day_trades_lock:
        events = _load_day_trades()
        events.append({"ts": datetime.now(ET).isoformat(), "occ": occ})
        # Keep only the last ~30 days so the file doesn't grow unbounded.
        cutoff = (datetime.now(ET) - timedelta(days=30)).isoformat()
        events = [e for e in events if e.get("ts", "") >= cutoff]
        try:
            os.makedirs(os.path.dirname(_DAY_TRADES_FILE), exist_ok=True)
            tmp = _DAY_TRADES_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(events, f)
            os.replace(tmp, _DAY_TRADES_FILE)
        except Exception as e:
            log.warning(f"_record_day_trade persist failed: {e}")
    log.info(f"  📋 Day-trade recorded: {occ} (opened+closed {today}). "
             f"5-day count now {count_day_trades_5d()}.")


def _business_days_ago(n: int) -> datetime:
    """Datetime n business days back from now (skips weekends; ignores
    holidays — that only makes the window LONGER = more conservative/safer
    for PDT protection)."""
    d = datetime.now(ET)
    step = 0
    while step < n:
        d -= timedelta(days=1)
        if d.weekday() < 5:   # Mon–Fri
            step += 1
    return d.replace(hour=0, minute=0, second=0, microsecond=0)


def count_day_trades_5d() -> int:
    """Day-trades within the last 5 business days (the PDT rolling window)."""
    cutoff = _business_days_ago(5).isoformat()
    with _day_trades_lock:
        return sum(1 for e in _load_day_trades() if e.get("ts", "") >= cutoff)


def _is_sub_pdt_account() -> bool:
    """True if the live account equity is below the PDT threshold ($25K).
    Cached for 60s to avoid hammering the Alpaca account endpoint."""
    if not PDT_RULE_ENABLED:
        return False  # operator disabled PDT self-enforcement → treat as exempt
    global _sub_pdt_cache
    now = time.time()
    if _sub_pdt_cache["ts"] and (now - _sub_pdt_cache["ts"]) < 60:
        return _sub_pdt_cache["val"]
    val = True  # fail-safe: if we can't tell, assume sub-PDT (stricter = safer)
    try:
        av = account_value()
        if av > 0:
            val = av < PDT_ACCOUNT_THRESHOLD
    except Exception:
        pass
    _sub_pdt_cache.update(ts=now, val=val)
    return val


_sub_pdt_cache = {"ts": 0.0, "val": True}


# ── Account-size adapter accessors ───────────────────────────────────────────
_sub10k_cache = {"ts": 0.0, "val": False}


def _is_sub10k_account() -> bool:
    """True if live equity < $10K. 60s-cached. Fail-safe = False (use the
    conservative module defaults if equity can't be read — never silently
    apply the looser sub-10K risk caps without confirming the account size)."""
    now = time.time()
    if _sub10k_cache["ts"] and (now - _sub10k_cache["ts"]) < 60:
        return _sub10k_cache["val"]
    val = False
    try:
        av = account_value()
        if av > 0:
            val = av < SUB10K_THRESHOLD
    except Exception:
        pass
    _sub10k_cache.update(ts=now, val=val)
    return val


# Precedence for paper mode: UI override > sub-10K profile > module defaults.
# In live_disciplined mode, UI overrides are IGNORED — the disciplined profile
# is always forced to protect real capital from paper-aggressive settings leaking in.
# The disciplined profile values are the sub-10K constants (4%/20%/20% tuned for $5K).
_ui_risk_override: Optional[float] = None

def eff_max_risk_pct() -> float:
    if RISK_MODE == "live_disciplined":
        return SUB10K_MAX_RISK_PCT   # 4% — forced; no UI override in live mode
    if _ui_risk_override is not None:
        return _ui_risk_override
    return SUB10K_MAX_RISK_PCT if _is_sub10k_account() else MAX_RISK_PCT

_ui_portfolio_risk_override: Optional[float] = None

def eff_max_portfolio_risk() -> float:
    if RISK_MODE == "live_disciplined":
        return SUB10K_MAX_PORTFOLIO_RISK   # 20% — forced
    if _ui_portfolio_risk_override is not None:
        return _ui_portfolio_risk_override
    return SUB10K_MAX_PORTFOLIO_RISK if _is_sub10k_account() else MAX_PORTFOLIO_RISK

def eff_daily_loss_limit_pct() -> float:
    if RISK_MODE == "live_disciplined":
        return SUB10K_DAILY_LOSS_LIMIT_PCT   # 20% — forced
    return SUB10K_DAILY_LOSS_LIMIT_PCT if _is_sub10k_account() else DAILY_LOSS_LIMIT_PCT

def eff_daily_profit_lock_pct() -> float:
    if RISK_MODE == "live_disciplined":
        return SUB10K_DAILY_PROFIT_LOCK_PCT   # 10% — forced
    return SUB10K_DAILY_PROFIT_LOCK_PCT if _is_sub10k_account() else DAILY_PROFIT_LOCK_PCT


def log_account_profile() -> None:
    """One-line profile banner at session start so it's unambiguous which
    risk regime is active. Called from all_day_session startup."""
    try:
        av = account_value()
    except Exception:
        av = 0.0
    if av and av < SUB10K_THRESHOLD:
        log.warning(
            f"  💰 SUB-$10K ACCOUNT (${av:,.2f}) — applying sub-10K profile: "
            f"per-trade {SUB10K_MAX_RISK_PCT*100:.0f}% (${av*SUB10K_MAX_RISK_PCT:,.0f}) · "
            f"daily-loss {SUB10K_DAILY_LOSS_LIMIT_PCT*100:.0f}% (${av*SUB10K_DAILY_LOSS_LIMIT_PCT:,.0f}) · "
            f"profit-lock {SUB10K_DAILY_PROFIT_LOCK_PCT*100:.0f}% · "
            f"portfolio-cap {SUB10K_MAX_PORTFOLIO_RISK*100:.0f}% · "
            f"max {SUB_PDT_MAX_DAILY_ENTRIES} entries/day (PDT-aware) · "
            f"min-notional ${MIN_TRADE_NOTIONAL} · "
            f"⚠️ ~$1.30 round-trip fee drag (~0.65%/trade)"
        )
    else:
        log.info(
            f"  💰 Account ${av:,.2f} — standard profile: "
            f"per-trade {MAX_RISK_PCT*100:.1f}% · daily-loss {DAILY_LOSS_LIMIT_PCT*100:.1f}% · "
            f"portfolio-cap {MAX_PORTFOLIO_RISK*100:.0f}%"
        )


def pdt_day_trades_remaining() -> Optional[int]:
    """For the UI badge. None if account is PDT-exempt (≥$25K); else
    the number of day-trades left before the 5-day cap locks new entries."""
    if not _is_sub_pdt_account():
        return None
    return max(0, PDT_MAX_DAY_TRADES_5D - count_day_trades_5d())


def pdt_sub25k_ok() -> bool:
    """Hard entry gate. Blocks a new entry that could become the 3rd+
    day-trade in the rolling 5-day window on a sub-$25K account. Independent
    of Alpaca's pattern_day_trader flag — we enforce it ourselves so paper
    behaves like live.

    Conservative: blocks at >= PDT_MAX_DAY_TRADES_5D (3) because the NEW
    entry, if closed same-day, would be day-trade #4 = the one that triggers
    the FINRA flag. We never want to take the trade that flags the account.
    """
    if not _is_sub_pdt_account():
        return True  # ≥ $25K → PDT rule doesn't apply
    used = count_day_trades_5d()
    if used >= PDT_MAX_DAY_TRADES_5D:
        log.warning(
            f"  🚫 PDT block: {used} day-trades in last 5 business days "
            f"(sub-$25K account). A 4th day-trade flags the account for 90 "
            f"days. No new entries until the window clears."
        )
        return False
    return True


_vix_prev_close: Optional[float] = None
VIX_SPIKE_PCT  = 0.15   # block new entries if VIX up >15% from yesterday's close


def gap_day_delay_ok(symbol: str = "SPY") -> bool:
    """Return False if today opened with a big gap AND we're still inside the
    first 30 min of the session (before 10:00 ET). The opening-range
    whipsaw window is the worst time to enter on a gap day.
    """
    now = datetime.now(ET)
    if now.hour > 10 or (now.hour == 10 and now.minute > 0):
        return True  # Past 10:00 ET — opening range has formed; gap is digested.
    try:
        prior = fetch_prior_day_levels(symbol)
        prev_close = prior.get("close") if prior else None
        if not prev_close or prev_close <= 0:
            return True
        spot = get_symbol_price(symbol) or 0.0
        if spot <= 0:
            return True
        gap = abs(spot - prev_close) / prev_close
        if gap >= OPEN_GAP_DELAY_PCT:
            log.warning(
                f"  ⏸  Gap-day delay ({symbol}): gap={gap*100:+.2f}% > "
                f"{OPEN_GAP_DELAY_PCT*100:.1f}% — waiting until 10:00 ET."
            )
            return False
    except Exception as e:
        log.warning(f"gap_day_delay_ok({symbol}): {e}")
    return True


# ── Macro event blackout ──────────────────────────────────────────────────────
# Hardcoded calendar of known high-impact macro events. Format: ISO date + ET time
# of release. Blackout window = MACRO_BLACKOUT_BEFORE_MIN before to AFTER_MIN after.
# Update this list periodically; ideally swap for an API (FRED / TradingEconomics).
MACRO_BLACKOUT_BEFORE_MIN = 30
MACRO_BLACKOUT_AFTER_MIN  = 30
MACRO_EVENTS: list[tuple[str, str, str]] = [
    # (date YYYY-MM-DD, ET time HH:MM, label)
    # 2026 FOMC dates (placeholder — verify before live trading):
    ("2026-01-28", "14:00", "FOMC"),
    ("2026-03-18", "14:00", "FOMC"),
    ("2026-04-29", "14:00", "FOMC"),
    ("2026-06-17", "14:00", "FOMC"),
    ("2026-07-29", "14:00", "FOMC"),
    ("2026-09-16", "14:00", "FOMC"),
    ("2026-11-04", "14:00", "FOMC"),
    ("2026-12-16", "14:00", "FOMC"),
    # Monthly CPI releases (2nd Tue/Wed at 8:30 — verify with BLS schedule):
    ("2026-01-14", "08:30", "CPI"),
    ("2026-02-11", "08:30", "CPI"),
    ("2026-03-11", "08:30", "CPI"),
    ("2026-04-15", "08:30", "CPI"),
    ("2026-05-13", "08:30", "CPI"),
    ("2026-06-10", "08:30", "CPI"),
    ("2026-07-15", "08:30", "CPI"),
    ("2026-08-12", "08:30", "CPI"),
    ("2026-09-09", "08:30", "CPI"),
    ("2026-10-14", "08:30", "CPI"),
    ("2026-11-12", "08:30", "CPI"),
    ("2026-12-10", "08:30", "CPI"),
    # NFP — first Friday of month at 8:30 ET:
    ("2026-01-02", "08:30", "NFP"),
    ("2026-02-06", "08:30", "NFP"),
    ("2026-03-06", "08:30", "NFP"),
    ("2026-04-03", "08:30", "NFP"),
    ("2026-05-01", "08:30", "NFP"),
    ("2026-06-05", "08:30", "NFP"),
    ("2026-07-02", "08:30", "NFP"),
    ("2026-08-07", "08:30", "NFP"),
    ("2026-09-04", "08:30", "NFP"),
    ("2026-10-02", "08:30", "NFP"),
    ("2026-11-06", "08:30", "NFP"),
    ("2026-12-04", "08:30", "NFP"),
]


def macro_event_blackout_ok() -> bool:
    """Return False if we're currently inside a macro event blackout window.

    Windows: BEFORE_MIN before release through AFTER_MIN after. Catches FOMC,
    CPI, NFP. The hardcoded list must be kept current — see TODO #5 for the
    longer-term plan to source from an API.
    """
    now = datetime.now(ET)
    today_str = now.strftime("%Y-%m-%d")
    for date_str, time_str, label in MACRO_EVENTS:
        if date_str != today_str:
            continue
        try:
            hh, mm = map(int, time_str.split(":"))
            event_time = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            window_start = event_time - timedelta(minutes=MACRO_BLACKOUT_BEFORE_MIN)
            window_end   = event_time + timedelta(minutes=MACRO_BLACKOUT_AFTER_MIN)
            if window_start <= now <= window_end:
                log.warning(
                    f"  📰 Macro blackout: {label} at {time_str} ET — "
                    f"no entries from {window_start.strftime('%H:%M')} "
                    f"to {window_end.strftime('%H:%M')}."
                )
                return False
        except Exception as e:
            log.warning(f"macro_event_blackout_ok parse error for {date_str} {time_str}: {e}")
    return True


def friday_gamma_ok(expiry_date) -> bool:
    """Return False if entering on a Friday with DTE < FRIDAY_MIN_DTE.

    Buying short-dated options on Fridays loads up on gamma right when theta
    accelerates over the weekend. expiry_date can be a date or YYYY-MM-DD string.
    """
    now = datetime.now(ET)
    if now.weekday() != 4:  # 4 = Friday
        return True
    if expiry_date is None:
        return True
    try:
        if isinstance(expiry_date, str):
            exp = datetime.strptime(expiry_date, "%Y-%m-%d").date()
        elif hasattr(expiry_date, "date"):
            exp = expiry_date.date()
        else:
            exp = expiry_date
        dte = (exp - now.date()).days
        if dte < FRIDAY_MIN_DTE:
            log.warning(
                f"  📅 Friday gamma throttle: DTE={dte} < {FRIDAY_MIN_DTE} — "
                f"skipping short-dated entry on Friday."
            )
            return False
    except Exception as e:
        log.warning(f"friday_gamma_ok: {e}")
    return True


def vix_check(vix):
    if vix is None:
        log.warning("VIX unavailable — blocking session (fail-safe). Retry in a few minutes.")
        return False
    if vix > VIX_MAX:
        log.warning(f"VIX={vix:.1f} > {VIX_MAX} — too volatile. Skipping session.")
        return False
    # Rate-of-change check: even within absolute bounds, a sharp intraday spike
    # is a regime change and a bad time to add directional vega.
    prev = _get_vix_prev_close()
    if prev and prev > 0:
        change = (vix - prev) / prev
        if change >= VIX_SPIKE_PCT:
            log.warning(
                f"VIX={vix:.1f} up {change*100:+.1f}% from prev close {prev:.1f} "
                f"(threshold {VIX_SPIKE_PCT*100:.0f}%) — regime shift, skipping entries."
            )
            return False
    regime = "Calm" if vix < 14 else "Normal" if vix < 20 else "Elevated" if vix < 28 else "High"
    log.info(f"VIX={vix:.1f} [{regime}]")
    return True


def _get_vix_prev_close() -> Optional[float]:
    """Cached fetch of yesterday's VIX close via yfinance (^VIX)."""
    global _vix_prev_close
    if _vix_prev_close is not None:
        return _vix_prev_close
    try:
        import yfinance as yf
        hist = yf.Ticker("^VIX").history(period="5d", interval="1d")
        if len(hist) >= 2:
            _vix_prev_close = float(hist["Close"].iloc[-2])
            return _vix_prev_close
    except Exception as e:
        log.warning(f"_get_vix_prev_close failed: {e}")
    return None


# ── Daily loss circuit-breaker ────────────────────────────────────────────────
_day_start_equity: float = 0.0
_day_start_date:   object = None   # datetime.date
_daily_loss_halt:  bool   = False  # True = ALL symbols blocked for the rest of the day
_equity_lock = threading.Lock()

# Multi-day equity history persisted to disk so weekly/monthly drawdown can
# be computed across restarts. Stored as a JSON list of {"date","equity"}.
_EQUITY_HISTORY_FILE = os.path.expanduser("~/.spy_trader/equity_history.json")
WEEKLY_LOSS_HALT_PCT = 0.04   # halt new entries if 5-day rolling DD >= 4%


def _load_equity_history() -> list:
    if not os.path.exists(_EQUITY_HISTORY_FILE):
        return []
    try:
        with open(_EQUITY_HISTORY_FILE) as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_equity_history(history: list) -> None:
    try:
        os.makedirs(os.path.dirname(_EQUITY_HISTORY_FILE), exist_ok=True)
        tmp = _EQUITY_HISTORY_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(history, f)
        os.replace(tmp, _EQUITY_HISTORY_FILE)
    except Exception as e:
        log.warning(f"_save_equity_history failed: {e}")


def record_eod_equity(acct_val: float) -> None:
    """Append today's end-of-day equity to history (idempotent per day)."""
    today = datetime.now(ET).date().isoformat()
    history = _load_equity_history()
    history = [h for h in history if h.get("date") != today]
    history.append({"date": today, "equity": round(acct_val, 2)})
    history = history[-90:]  # keep last 90 trading days
    _save_equity_history(history)


def rolling_drawdown_pct(window_days: int = 5) -> float:
    """Compute rolling drawdown over the last N entries in equity history.

    Returns the worst peak-to-current drop as a fraction (e.g., 0.04 = 4%).
    """
    history = _load_equity_history()
    if len(history) < 2:
        return 0.0
    window = history[-window_days:]
    peak = max(h["equity"] for h in window)
    current = window[-1]["equity"]
    if peak <= 0:
        return 0.0
    return max(0.0, (peak - current) / peak)


def equity_curve_snapshot(live_equity: float = 0.0) -> dict:
    """Compact equity-curve summary for the UI (Settings card).

    Returns history points + headline metrics. `live_equity` (if >0) is
    appended as a provisional 'today' point so the curve reflects intraday
    state before the EOD snapshot lands.
    """
    hist = _load_equity_history()
    pts = [{"date": h["date"], "equity": h["equity"]} for h in hist]
    today = datetime.now(ET).date().isoformat()
    if live_equity and live_equity > 0:
        if pts and pts[-1]["date"] == today:
            pts = pts[:-1]  # replace stale same-day point with live
        pts.append({"date": today, "equity": round(live_equity, 2)})
    if not pts:
        return {"points": [], "n": 0}
    equities = [p["equity"] for p in pts]
    start, cur = equities[0], equities[-1]
    peak = max(equities)
    return {
        "points":      pts[-30:],                       # last 30 for the sparkline
        "n":           len(pts),
        "current":     round(cur, 2),
        "start":       round(start, 2),
        "total_ret_pct": round((cur - start) / start * 100, 2) if start else 0.0,
        "peak":        round(peak, 2),
        "max_dd_pct":  round((peak - min(equities[equities.index(peak):] or [peak])) / peak * 100, 2) if peak else 0.0,
        "dd5_pct":     round(rolling_drawdown_pct(5) * 100, 2),
        "dd20_pct":    round(rolling_drawdown_pct(20) * 100, 2),
        "dd30_pct":    round(rolling_drawdown_pct(30) * 100, 2),
    }


_weekly_halt: bool = False

def weekly_drawdown_check(acct_val: float) -> bool:
    """Return False (halt entries) if 5-day rolling DD exceeds WEEKLY_LOSS_HALT_PCT.

    Uses the CURRENT live equity vs. the recent peak (history + today's live).
    Cleared automatically once the peak refreshes.
    """
    global _weekly_halt
    with _equity_lock:
        if _weekly_halt:
            log.info("  📉 Weekly drawdown halt active — entries blocked.")
            return False
        history = _load_equity_history()
        if len(history) < 2:
            return True
        recent = [h["equity"] for h in history[-5:]] + [acct_val]
        peak = max(recent)
        if peak <= 0:
            return True
        dd = (peak - acct_val) / peak
        if dd >= WEEKLY_LOSS_HALT_PCT:
            _weekly_halt = True
            log.warning(
                f"  📉 Weekly drawdown limit reached: {dd*100:.2f}% from 5-day peak "
                f"(limit {WEEKLY_LOSS_HALT_PCT*100:.1f}%). Halting new entries."
            )
            return False
    return True

def set_day_start_equity(acct_val: float) -> None:
    """Record start-of-day equity once per calendar day (first symbol to call wins).
    Resets both halt flags on a new day.
    """
    global _day_start_equity, _day_start_date, _daily_loss_halt, _daily_profit_halt
    today = datetime.now(ET).date()
    with _equity_lock:
        if _day_start_date != today:
            _day_start_equity   = acct_val
            _day_start_date     = today
            _daily_loss_halt    = False   # new day — lift the halt
            _daily_profit_halt  = False
            log.info(f"Day-start equity set: ${acct_val:,.2f}")

def daily_loss_check(acct_val: float) -> bool:
    """Return False (halt ALL entries) if today's cumulative loss >= DAILY_LOSS_LIMIT_PCT.
    Once tripped, ALL symbols are blocked for the rest of the day.
    """
    global _daily_loss_halt
    with _equity_lock:
        if _daily_loss_halt:
            log.warning("  ⛔ Daily loss halt active — no new entries today.")
            return False
        if _day_start_equity <= 0:
            return True
        loss_pct = (_day_start_equity - acct_val) / _day_start_equity
        _loss_limit = eff_daily_loss_limit_pct()
        if loss_pct >= _loss_limit:
            _daily_loss_halt = True
            log.warning(
                f"  ⛔ Daily loss limit reached: down {loss_pct*100:.2f}% "
                f"(limit {_loss_limit*100:.1f}%). "
                f"ALL symbols halted for the rest of the day."
            )
            return False
    return True


_daily_profit_halt: bool = False  # True after profit-lock fires (entries only; positions still managed)

def daily_profit_check(acct_val: float) -> bool:
    """Return False (halt new entries) once we're up >= DAILY_PROFIT_LOCK_PCT.

    Open positions keep being managed by the monitor — we just stop opening new
    risk. Pros take chips off when up; this is the bot equivalent.
    """
    global _daily_profit_halt
    with _equity_lock:
        if _daily_profit_halt:
            log.info("  💰 Daily profit lock active — protecting today's gains.")
            return False
        if _day_start_equity <= 0:
            return True
        gain_pct = (acct_val - _day_start_equity) / _day_start_equity
        _profit_lock = eff_daily_profit_lock_pct()
        if gain_pct >= _profit_lock:
            _daily_profit_halt = True
            log.info(
                f"  💰 Daily profit lock reached: up {gain_pct*100:.2f}% "
                f"(target {_profit_lock*100:.1f}%). "
                f"No new entries — open positions still managed."
            )
            return False
    return True


# ── Global cross-symbol cooldown ──────────────────────────────────────────────
# Without this, two symbols can fire within the same second and bypass the
# portfolio risk gate (which is checked before, not after, both submissions).
_last_global_trade_ts: float = 0.0  # time.monotonic() of the most recent entry
_global_cooldown_lock = threading.Lock()

def global_cooldown_ok() -> bool:
    """Return True if at least GLOBAL_COOLDOWN_SEC have passed since any symbol traded."""
    with _global_cooldown_lock:
        elapsed = time.monotonic() - _last_global_trade_ts
        return elapsed >= GLOBAL_COOLDOWN_SEC

def _record_global_trade() -> None:
    """Stamp the global last-trade timestamp. Called after any place_trade attempt."""
    global _last_global_trade_ts
    with _global_cooldown_lock:
        _last_global_trade_ts = time.monotonic()


# ── Anti-whipsaw: don't fire opposite direction within WHIPSAW_COOLDOWN_SEC ───
# Today's log showed BULL → BEAR signals 6 SECONDS apart on correlated symbols.
# Net result: flat exposure with double the spread cost. Track the most recent
# fired-signal direction (across all symbols) and reject the opposite within 15min.
_last_signal_direction: Optional[str] = None
_last_signal_ts: float = 0.0
_whipsaw_lock = threading.Lock()

def whipsaw_ok(direction: str) -> bool:
    """True if `direction` is safe to fire — i.e. opposite-direction wasn't just signalled."""
    with _whipsaw_lock:
        if _last_signal_direction is None:
            return True
        if _last_signal_direction == direction:
            return True   # same-direction continuation is fine
        elapsed = time.monotonic() - _last_signal_ts
        return elapsed >= WHIPSAW_COOLDOWN_SEC

def record_signal_direction(direction: str) -> None:
    """Stamp the most recent fired signal's direction + timestamp."""
    global _last_signal_direction, _last_signal_ts
    with _whipsaw_lock:
        _last_signal_direction = direction
        _last_signal_ts        = time.monotonic()


# ── Daily entry cap: hard limit MAX_DAILY_ENTRIES per calendar day ────────────
# 26 simulated entries in 4 hours today — half of those were re-entering the
# same symbol while it didn't move. After N entries, the bot enters manage-only
# mode for the rest of the day. Forces selectivity.
_daily_entries_count: int = 0
_daily_entries_date:  object = None  # datetime.date
_daily_entries_lock = threading.Lock()

def daily_entries_ok() -> bool:
    """True if we haven't hit the per-day entry cap (resets at new date).
    Sub-$25K accounts use the tighter SUB_PDT_MAX_DAILY_ENTRIES (PDT-aware)
    instead of the default MAX_DAILY_ENTRIES."""
    global _daily_entries_count, _daily_entries_date
    today = datetime.now(ET).date()
    cap = SUB_PDT_MAX_DAILY_ENTRIES if _is_sub_pdt_account() else MAX_DAILY_ENTRIES
    with _daily_entries_lock:
        if _daily_entries_date != today:
            _daily_entries_count = 0
            _daily_entries_date  = today
        return _daily_entries_count < cap

def record_daily_entry() -> int:
    """Increment the daily-entry counter. Returns the new count."""
    global _daily_entries_count, _daily_entries_date
    today = datetime.now(ET).date()
    with _daily_entries_lock:
        if _daily_entries_date != today:
            _daily_entries_count = 0
            _daily_entries_date  = today
        _daily_entries_count += 1
        return _daily_entries_count


# ── First-entry-time gate: no NEW entries before 9:45 ET ─────────────────────
# First 15 min (9:30–9:45) are pure whipsaw — wide spreads, algos shaking out
# retail, ORB not yet formed. KB rule: never enter in the first 15 min.
FIRST_ENTRY_HOUR   = 9
FIRST_ENTRY_MINUTE = 45

def first_entry_time_ok() -> bool:
    now = datetime.now(ET)
    earliest = now.replace(hour=FIRST_ENTRY_HOUR, minute=FIRST_ENTRY_MINUTE,
                           second=0, microsecond=0)
    if now < earliest:
        log.info(f"  Too early for entry ({now.strftime('%H:%M')} ET) — wait until 09:45 ET (KB: no entries in first 15 min)")
        return False
    return True


# ── Last-entry-time gate: no NEW entries after 14:00 ET ──────────────────────
# After ~14:00 ET, price action is increasingly dominated by closing-imbalance
# flow rather than directional moves. Stop opening new positions; manage existing.
def last_entry_time_ok() -> bool:
    now = datetime.now(ET)
    cutoff = now.replace(hour=LAST_ENTRY_HOUR, minute=LAST_ENTRY_MINUTE, second=0, microsecond=0)
    return now < cutoff


# ── Trade execution ───────────────────────────────────────────────────────────
def place_trade(option, contracts, mid_price, direction, reason, atr=None, symbol: str = "SPY",
                indicators: dict = None, ask_price: float = 0.0,
                underlying_price: float = 0.0, signal_class: str = "unknown"):
    symbol     = symbol.upper()
    opt_type   = option.get("type", "?")
    strike     = option.get("strike_price", "?")
    expiry     = option.get("expiration_date", "?")
    occ_symbol = option.get("symbol", "?")
    # Two-stage entry: try mid first (capture half the spread), walk to ask if it
    # doesn't fill within ENTRY_WALK_WAIT_SEC. The "walk_limit" below is the final
    # stop — what we'd accept after walking. mid_limit is the initial try.
    mid_limit = round(mid_price, 2)
    if ask_price > 0:
        walk_limit = round(ask_price * 1.002, 2)   # final fallback after walking
    else:
        walk_limit = round(mid_price + 0.05, 2)
    limit      = mid_limit                         # logged as the initial limit
    stop_opt   = round(mid_price * (1 - STOP_LOSS_PCT), 2)
    target_50  = round(mid_price * 1.50, 2)
    target_75  = round(mid_price * (1 + PROFIT_TARGET), 2)
    max_loss   = round(mid_price * 100 * contracts, 2)

    # ATR-based underlying stop: "if SPY drops below $X, exit the option position."
    # Applies to the underlying price, NOT the option premium.
    atr_stop_und = None
    if atr and underlying_price > 0:
        atr_stop_und = round(underlying_price - (atr * ATR_MULT_TREND), 2) if direction == "bull" \
                       else round(underlying_price + (atr * ATR_MULT_TREND), 2)

    log.info("─" * 60)
    log.info(f"SIGNAL [{direction.upper()}]  {reason}")
    log.info(f"  Option   : {symbol} {expiry} ${strike} {opt_type.upper()} ({occ_symbol})")
    log.info(f"  Size     : {contracts} contract(s)  entry ${mid_price:.2f}  limit ${limit:.2f}")
    log.info(f"  Max loss : ${max_loss:,.2f}")
    log.info(f"  Stop     : ${stop_opt:.2f}  (-{int(STOP_LOSS_PCT*100)}%)")
    log.info(f"  Target 1 : ${target_50:.2f}  (+50% → close 50%)")
    log.info(f"  Target 2 : ${target_75:.2f}  (+{int(PROFIT_TARGET*100)}% → trail rest)")
    if atr_stop_und:
        log.info(f"  ATR stop : {symbol} underlying ${atr_stop_und:.2f}  (ATR={atr:.2f} × {ATR_MULT_TREND})")
    log.info(f"  Mode     : {'PAPER' if PAPER_MODE else 'LIVE'}  |  Hard close {HARD_CLOSE[0]}:{HARD_CLOSE[1]:02d} ET")
    log.info("─" * 60)

    details = {
        "direction":   direction,
        "reason":      reason,
        "symbol":      symbol,
        "occ_symbol":  occ_symbol,
        "expiry":      expiry,
        "strike":      float(strike) if strike != "?" else 0,
        "type":        opt_type,
        "contracts":   contracts,
        "mid_price":   mid_price,
        "limit_price": limit,
        "stop_price":  stop_opt,
        "target_50":   target_50,
        "target_75":   target_75,
        "max_loss":    max_loss,
        "atr_stop":    atr_stop_und,
        "dry_run":      DRY_RUN,
        "paper":        PAPER_MODE,
        "_indicators":  indicators or {},
    }

    # Approval
    if TRADE_CONFIRM_CALLBACK is not None:
        approved = TRADE_CONFIRM_CALLBACK(details)
    elif DRY_RUN:
        approved = False
    else:
        confirm = input(f"\n⚠️  ORDER: {contracts}x {occ_symbol} @ ${limit}? (yes/no): ").strip().lower()
        approved = confirm == "yes"

    if DRY_RUN:
        verdict = "ALLOWED" if approved else "SKIPPED"
        log.info(f"[DRY RUN] User {verdict} — no order placed.")
        if approved:
            # Unique per-trade id so ChromaDB doesn't collide across dry-runs.
            dry_id = f"DRY_{occ_symbol}_{int(time.time() * 1000)}"
            TRADE_MEMORY.record(
                symbol=symbol, direction=direction,
                indicators=details.get("_indicators", {}),
                entry_price=mid_price, trade_id=dry_id,
                is_dry_run=True,
            )
            _narr = generate_signal_narrative(details)
            register_trade(occ_symbol, mid_price, contracts, direction, symbol,
                           order_id=dry_id, is_dry_run=True, narrative=_narr,
                           signal_class=signal_class)
            _notify_fill()  # refresh UI: deployed_risk_pct ticks even in dry-run
        return None

    if not approved:
        log.info("Trade skipped by user.")
        return None

    if not pdt_check():
        return None

    # Submit option order via Alpaca — two-stage walk:
    # 1. Submit at mid, wait ENTRY_WALK_WAIT_SEC.
    # 2. If not filled, cancel and resubmit at walk_limit (ask × 1.002).
    # Both submissions carry a unique client_order_id for broker-side dedupe.
    try:
        cid_base = f"buy_{occ_symbol}_{int(time.time())}"
        order = TRADING_CLIENT.submit_order(LimitOrderRequest(
            symbol         = occ_symbol,
            qty            = contracts,
            side           = OrderSide.BUY,
            type           = OrderType.LIMIT,
            time_in_force  = TimeInForce.DAY,
            limit_price    = mid_limit,
            client_order_id= f"{cid_base}_mid",
        ))
        log.info(f"Order submitted (mid ${mid_limit:.2f}) — ID: {order.id}  Status: {order.status}")

        # Brief poll — if mid filled, we saved half the spread.
        if mid_limit < walk_limit:
            time.sleep(ENTRY_WALK_WAIT_SEC)
            try:
                refreshed = TRADING_CLIENT.get_order_by_id(str(order.id))
                status = str(refreshed.status).lower()
            except Exception:
                refreshed, status = order, "unknown"

            if status not in ("filled", "partially_filled"):
                # Walk up: cancel mid order, resubmit at walk_limit (ask).
                try:
                    TRADING_CLIENT.cancel_order_by_id(str(order.id))
                except Exception:
                    pass
                log.info(f"  Mid order didn't fill in {ENTRY_WALK_WAIT_SEC}s — walking to ask ${walk_limit:.2f}")
                order = TRADING_CLIENT.submit_order(LimitOrderRequest(
                    symbol         = occ_symbol,
                    qty            = contracts,
                    side           = OrderSide.BUY,
                    type           = OrderType.LIMIT,
                    time_in_force  = TimeInForce.DAY,
                    limit_price    = walk_limit,
                    client_order_id= f"{cid_base}_walk",
                ))
                log.info(f"Order resubmitted (walk ${walk_limit:.2f}) — ID: {order.id}  Status: {order.status}")

        TRADE_MEMORY.record(
            symbol=symbol, direction=direction,
            indicators=details.get("_indicators", {}),
            entry_price=mid_price, trade_id=str(order.id),
            is_dry_run=False,
        )
        _narr = generate_signal_narrative(details)
        register_trade(occ_symbol, mid_price, contracts, direction, symbol,
                       order_id=str(order.id), is_dry_run=False, narrative=_narr,
                       signal_class=signal_class)
        return order
    except Exception as e:
        log.error(f"Order failed: {e}")
        return None


# ── JSON-safe indicator snapshot ──────────────────────────────────────────────
# bar.to_dict() returns pandas/numpy types (Timestamp, np.float64, NaN) that
# blow up the SocketIO json serialiser when the trade-approval modal is emitted.
# Every signal was crashing here ("Object of type Timestamp is not JSON
# serializable") which silently killed every would-be trade.
def _to_json_safe(v):
    if v is None:
        return None
    if isinstance(v, pd.Timestamp):
        return v.isoformat()
    if hasattr(v, "item"):                         # numpy scalars
        try:
            v = v.item()
        except Exception:
            pass
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    if isinstance(v, (int, bool, str)):
        return v
    try:
        f = float(v)
        return None if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return str(v)

def _sanitize_indicators(d: dict) -> dict:
    return {k: _to_json_safe(v) for k, v in d.items()}


# ── Setup evaluation ──────────────────────────────────────────────────────────
def evaluate_orb(bar, prev_bar, or_high, or_low, df):
    current   = float(bar["close_price"])
    rsi       = float(bar["rsi"])       if not np.isnan(bar["rsi"])       else 50
    vol_ratio = float(bar["vol_ratio"]) if not np.isnan(bar["vol_ratio"]) else 1
    vwap      = float(bar["vwap"])
    ema9      = float(bar["ema9"])
    ema21     = float(bar["ema21"])
    ema200    = float(bar["ema200"])    if not np.isnan(bar["ema200"])    else current
    macd_hist = float(bar["macd_hist"]) if not np.isnan(bar["macd_hist"]) else 0

    # Filter stack: break + volume + above VWAP + short-term EMA cross + above EMA200 + MACD
    bull_fail = []
    if not (current > or_high):           bull_fail.append(f"close ${current:.2f}<=ORhigh ${or_high:.2f}")
    if not (vol_ratio >= MIN_VOL_RATIO):  bull_fail.append(f"vol {vol_ratio:.2f}<{MIN_VOL_RATIO}")
    if not (current > vwap):              bull_fail.append("close<=VWAP")
    if not (ema9 > ema21):                bull_fail.append("EMA9<=EMA21")
    if not (current > ema200):            bull_fail.append("close<=EMA200d")
    if not (macd_hist > 0):               bull_fail.append(f"MACD={macd_hist:.3f}<=0")

    if not bull_fail:
        return "bull", (f"ORB bull: ${current:.2f} > OR high ${or_high:.2f} | "
                        f"vol {vol_ratio:.1f}x | above VWAP & EMA200 | RSI={rsi:.0f}")

    bear_fail = []
    if not (current < or_low):            bear_fail.append(f"close ${current:.2f}>=ORlow ${or_low:.2f}")
    if not (vol_ratio >= MIN_VOL_RATIO):  bear_fail.append(f"vol {vol_ratio:.2f}<{MIN_VOL_RATIO}")
    if not (current < vwap):              bear_fail.append("close>=VWAP")
    if not (ema9 < ema21):                bear_fail.append("EMA9>=EMA21")
    if not (current < ema200):            bear_fail.append("close>=EMA200d")
    if not (macd_hist < 0):               bear_fail.append(f"MACD={macd_hist:.3f}>=0")

    if not bear_fail:
        return "bear", (f"ORB bear: ${current:.2f} < OR low ${or_low:.2f} | "
                        f"vol {vol_ratio:.1f}x | below VWAP & EMA200 | RSI={rsi:.0f}")

    log.info(
        f"  ORB no-fire: bull[{', '.join(bull_fail)}] | "
        f"bear[{', '.join(bear_fail)}]"
    )
    return None, None


def evaluate_gap_fade(bar, gap_pct, gap_direction, df):
    current   = float(bar["close_price"])
    rsi       = float(bar["rsi"])       if not np.isnan(bar["rsi"])       else 50
    vwap      = float(bar["vwap"])
    macd_hist = float(bar["macd_hist"]) if not np.isnan(bar["macd_hist"]) else 0
    abs_gap   = abs(gap_pct)

    # 0.50% lower bound: anything smaller is intraday noise, not a real gap.
    if not (0.50 <= abs_gap <= 2.50):
        return None, None

    if gap_direction == "up":
        bear_fail = []
        if not (current < vwap):    bear_fail.append("close>=VWAP (gap not rolling over)")
        if not (rsi < 55):          bear_fail.append(f"RSI={rsi:.0f}>=55")
        if not (macd_hist < 0):     bear_fail.append(f"MACD={macd_hist:.3f}>=0")
        if not bear_fail:
            return "bear", (f"Gap fade: gapped up {gap_pct:+.2f}% but rolling over | "
                            f"below VWAP | RSI={rsi:.0f}")
        log.info(f"  Gap-fade(up) no-fire: {', '.join(bear_fail)}")

    elif gap_direction == "down":
        bull_fail = []
        if not (current > vwap):    bull_fail.append("close<=VWAP (gap not recovering)")
        if not (rsi > 45):          bull_fail.append(f"RSI={rsi:.0f}<=45")
        if not (macd_hist > 0):     bull_fail.append(f"MACD={macd_hist:.3f}<=0")
        if not bull_fail:
            return "bull", (f"Gap fade: gapped down {gap_pct:+.2f}% but recovering | "
                            f"above VWAP | RSI={rsi:.0f}")
        log.info(f"  Gap-fade(down) no-fire: {', '.join(bull_fail)}")

    return None, None


def evaluate_vwap_momentum(bar, prev_bar, df):
    current        = float(bar["close_price"])
    rsi            = float(bar["rsi"])       if not np.isnan(bar["rsi"])       else 50
    vol_ratio      = float(bar["vol_ratio"]) if not np.isnan(bar["vol_ratio"]) else 1
    vwap           = float(bar["vwap"])
    ema9           = float(bar["ema9"])
    ema21          = float(bar["ema21"])
    macd_hist      = float(bar["macd_hist"]) if not np.isnan(bar["macd_hist"]) else 0
    closing_up     = float(bar["close_price"]) > float(prev_bar["close_price"])
    # Use the LAST 30 BARS (~2.5 hrs at 5-min) instead of whole-session average.
    # Whole-day above_vwap_pct goes stale by 3pm: a stock that ran above VWAP all
    # morning then dipped reads 0.85 — false bull. Recent window tracks current regime.
    recent_window  = df.tail(30) if len(df) >= 30 else df
    above_vwap_pct = float((recent_window["close_price"] > recent_window["vwap"]).mean())

    # Filter stack: dropped the RSI band — it was rejecting strong-trend setups
    # (RSI 70+ on a clean breakout is the *signal*, not a problem). EMA9>EMA21 +
    # MACD>0 + closing_up + above-VWAP-recent already enforce direction.
    # Vol threshold also lowered to VWAP_MIN_VOL_RATIO (1.0×) — most mid-day bars
    # run below 1.2× even on real moves.
    bull_fail = []
    if not (current > vwap):                       bull_fail.append("close<=VWAP")
    if not (above_vwap_pct > 0.50):                bull_fail.append(f"above_vwap_pct={above_vwap_pct:.0%}<=50%")
    if not (ema9 > ema21):                         bull_fail.append("EMA9<=EMA21")
    if not (vol_ratio >= VWAP_MIN_VOL_RATIO):      bull_fail.append(f"vol {vol_ratio:.2f}<{VWAP_MIN_VOL_RATIO}")
    if not (macd_hist > 0):                        bull_fail.append(f"MACD={macd_hist:.3f}<=0")
    if not closing_up:                             bull_fail.append("not closing up")

    if not bull_fail:
        return "bull", (f"VWAP momentum: above VWAP {above_vwap_pct:.0%} of recent | "
                        f"RSI={rsi:.0f} | MACD green | {vol_ratio:.1f}x vol")

    bear_fail = []
    if not (current < vwap):                       bear_fail.append("close>=VWAP")
    if not (above_vwap_pct < 0.50):                bear_fail.append(f"above_vwap_pct={above_vwap_pct:.0%}>=50%")
    if not (ema9 < ema21):                         bear_fail.append("EMA9>=EMA21")
    if not (vol_ratio >= VWAP_MIN_VOL_RATIO):      bear_fail.append(f"vol {vol_ratio:.2f}<{VWAP_MIN_VOL_RATIO}")
    if not (macd_hist < 0):                        bear_fail.append(f"MACD={macd_hist:.3f}>=0")
    if not (not closing_up):                       bear_fail.append("not closing down")

    if not bear_fail:
        return "bear", (f"VWAP momentum: below VWAP {(1-above_vwap_pct):.0%} of recent | "
                        f"RSI={rsi:.0f} | MACD red | {vol_ratio:.1f}x vol")

    log.info(
        f"  VWAP-momentum no-fire: bull[{', '.join(bull_fail)}] | "
        f"bear[{', '.join(bear_fail)}]"
    )
    return None, None


# ── Trend-continuation + mean-reversion (added when strict gates produced 0 trades) ──
# ⚠️ DISABLED BY DEFAULT 2026-05-17 (TODO item 17, commit-justified by
# backtest_v2 / 57bac3e). This evaluator was the "trade more" fallback —
# and the 60d/6-symbol backtest proved trading more = losing more:
#   trend_cont: PF 0.49, −4.19%/trade, −1692% over 404 trades (75% of book)
#   vwap_momentum: PF 1.75, +3.68%/trade (the actual edge)
# The aggregate was net-negative ONLY because trend_cont drowned the good
# signal. Gated behind a flag (not deleted) so the paid 3-yr backtest can
# re-confirm and flip it back if 3-yr data disagrees with the 60d result.
# Includes the mean_rev lane (PF 0.50, n=6) — also negative, also gated.
TREND_CONT_ENABLED         = False  # set True only with 3-yr backtest proof
# gap_fade disabled 2026-05-18 — confirmed NOISE by two independent methods:
# real-3yr backtest PF 0.46 (catastrophic) AND signal_diagnostic.py shows
# ~48% underlying-direction hit-rate / ~0 ATR excursion (no predictive
# power at any horizon). Same justified+reversible pattern as item 17.
GAP_FADE_ENABLED           = False  # set True only with backtest proof
TREND_CONT_SCORE_THRESHOLD = 5   # 5 of 6 conditions agree on direction
TREND_CONT_VOL_MIN         = 0.5 # mid-day volume gate (looser than VWAP momentum)
MEAN_REV_RSI_OVERSOLD      = 28  # RSI ≤ this + MACD turning green = bounce setup
MEAN_REV_RSI_OVERBOUGHT    = 72  # RSI ≥ this + MACD turning red = fade setup

def evaluate_trend_continuation(bar, prev_bar, df):
    """Score-based continuation + mean-reversion at extremes.

    Two sub-strategies in priority order:

    1. SCORE-BASED CONTINUATION
       Tally bull/bear conditions across {VWAP, EMA cross, MACD, RSI half, regime,
       volume}. Fire when 4+ agree on the same direction AND RSI hasn't yet hit
       an extreme (bull only when RSI<72, bear only when RSI>28). The RSI bound
       prevents firing late into mature moves where the next probable action is
       a reversal, not a continuation.

    2. MEAN-REVERSION AT EXTREMES
       RSI ≤ 28 + MACD just turned positive  → bull (oversold bounce starting)
       RSI ≥ 72 + MACD just turned negative → bear (overbought fade starting)
       The "MACD turning" check waits for the reversal to actually begin so we
       don't catch a falling knife.

    Both lanes share the standard cooldown / gate stack downstream.
    """
    current        = float(bar["close_price"])
    rsi            = float(bar["rsi"])       if not np.isnan(bar["rsi"])       else 50
    vol_ratio      = float(bar["vol_ratio"]) if not np.isnan(bar["vol_ratio"]) else 1
    vwap           = float(bar["vwap"])
    ema9           = float(bar["ema9"])
    ema21          = float(bar["ema21"])
    macd_hist      = float(bar["macd_hist"]) if not np.isnan(bar["macd_hist"]) else 0
    prev_macd      = float(prev_bar["macd_hist"]) if "macd_hist" in prev_bar and not np.isnan(prev_bar["macd_hist"]) else macd_hist
    recent_window  = df.tail(20) if len(df) >= 20 else df
    above_vwap_pct = float((recent_window["close_price"] > recent_window["vwap"]).mean())

    # ── 1. Score-based continuation ──────────────────────────────────────────
    bull_score = 0
    if current > vwap:                       bull_score += 1
    if ema9 > ema21:                         bull_score += 1
    if macd_hist > 0:                        bull_score += 1
    if rsi >= 50:                            bull_score += 1
    if above_vwap_pct >= 0.65:               bull_score += 1
    if vol_ratio >= TREND_CONT_VOL_MIN:      bull_score += 1

    bear_score = 0
    if current < vwap:                       bear_score += 1
    if ema9 < ema21:                         bear_score += 1
    if macd_hist < 0:                        bear_score += 1
    if rsi <= 50:                            bear_score += 1
    if above_vwap_pct <= 0.35:               bear_score += 1
    if vol_ratio >= TREND_CONT_VOL_MIN:      bear_score += 1

    # Score threshold of 5 means MACD's score-point IS the agreement check —
    # if MACD disagrees you can hit at most 5/6, which means 5 OTHER conditions
    # all agree (a genuine high-conviction setup with lagging MACD). Below 5
    # was firing on weak setups; an additional hard MACD gate was too strict
    # in chop. RSI bounds still prevent firing into mature mean-reversion zones.
    if (bull_score >= TREND_CONT_SCORE_THRESHOLD
            and bull_score > bear_score
            and rsi < MEAN_REV_RSI_OVERBOUGHT):
        return "bull", (
            f"Trend-cont bull score={bull_score}/6 | RSI={rsi:.0f} | "
            f"MACD={macd_hist:+.2f} | vol={vol_ratio:.1f}x"
        )

    if (bear_score >= TREND_CONT_SCORE_THRESHOLD
            and bear_score > bull_score
            and rsi > MEAN_REV_RSI_OVERSOLD):
        return "bear", (
            f"Trend-cont bear score={bear_score}/6 | RSI={rsi:.0f} | "
            f"MACD={macd_hist:+.2f} | vol={vol_ratio:.1f}x"
        )

    # ── 2. Mean-reversion at extremes ────────────────────────────────────────
    # MACD reversal detector: requires the histogram to have moved a meaningful
    # distance back toward zero — at least 50% of its prior magnitude. Avoids
    # firing on a tiny tick-up while MACD is still deep in the trend (e.g.
    # -0.452 → -0.448 is noise, not a reversal).
    macd_turning_up = (
        prev_macd <= -0.05
        and macd_hist > prev_macd
        and abs(macd_hist) < abs(prev_macd) * 0.5
    )
    macd_turning_down = (
        prev_macd >= 0.05
        and macd_hist < prev_macd
        and abs(macd_hist) < abs(prev_macd) * 0.5
    )

    if rsi <= MEAN_REV_RSI_OVERSOLD and macd_turning_up:
        return "bull", (
            f"Mean-rev bounce: RSI={rsi:.0f} oversold + MACD turning green "
            f"({prev_macd:+.2f}→{macd_hist:+.2f})"
        )

    if rsi >= MEAN_REV_RSI_OVERBOUGHT and macd_turning_down:
        return "bear", (
            f"Mean-rev fade: RSI={rsi:.0f} overbought + MACD turning red "
            f"({prev_macd:+.2f}→{macd_hist:+.2f})"
        )

    log.info(
        f"  Trend-cont/mean-rev no-fire: "
        f"bull_score={bull_score} bear_score={bear_score} "
        f"RSI={rsi:.0f} MACD={macd_hist:+.3f}({prev_macd:+.3f})"
    )
    return None, None


# ── Session runner ────────────────────────────────────────────────────────────
def run_session(session_name, session_end_hour, session_end_min,
                evaluate_fn, prior_levels, gap_info=None, stop_event=None,
                symbol: str = "SPY", daily_ema200: Optional[float] = None,
                iv_rank: Optional[float] = None, current_iv: Optional[float] = None):
    symbol = symbol.upper()
    session_end = datetime.now(ET).replace(
        hour=session_end_hour, minute=session_end_min, second=0, microsecond=0
    )
    acct_val = account_value()
    traded   = False

    log.info(f"Account: ${acct_val:,.2f}  |  Max risk: ${acct_val * eff_max_risk_pct():,.2f}  |  Trading: {symbol}")
    if prior_levels:
        log.info(
            f"Levels — Pivot={prior_levels.get('pivot')}  "
            f"R1={prior_levels.get('r1')}  S1={prior_levels.get('s1')}"
        )

    while datetime.now(ET) < session_end and not traded:
        if stop_event and stop_event.is_set():
            log.info(f"{session_name}: stopped by user.")
            break
        if is_lunch_hour(symbol):
            log.info(f"Lunch-hour block (11:30–13:30 ET) for ETF {symbol}. Waiting...")
            # Interruptible 5-minute wait
            if stop_event:
                if stop_event.wait(timeout=300):
                    log.info(f"{session_name}: stopped during lunch block.")
                    break
            else:
                time.sleep(300)
            continue

        df = fetch_bars(symbol)
        if df is None or len(df) < 5:
            if stop_event:
                if stop_event.wait(timeout=60):
                    break
            else:
                time.sleep(60)
            continue

        df       = inject_daily_ema200(df, daily_ema200)
        bar      = df.iloc[-1]
        prev_bar = df.iloc[-2] if len(df) > 1 else bar
        current  = float(bar["close_price"])
        atr      = float(bar["atr"]) if not np.isnan(bar["atr"]) else None
        ema200_str = f"{daily_ema200:.2f}" if daily_ema200 else "—"

        atr_str = f"{atr:.2f}" if atr else "—"
        log.info(
            f"  {bar['begins_at'].strftime('%H:%M')}  "
            f"{symbol}=${current:.2f}  VWAP={bar['vwap']:.2f}  "
            f"EMA9={bar['ema9']:.2f}  EMA21={bar['ema21']:.2f}  EMA200d={ema200_str}  "
            f"RSI={bar['rsi']:.1f}  MACD={bar['macd_hist']:.3f}  "
            f"ATR={atr_str}  Vol={bar['vol_ratio']:.2f}x  "
            f"BB[{bar['bb_lower']:.2f}–{bar['bb_upper']:.2f}]"
        )

        direction, reason = evaluate_fn(bar, prev_bar, df)
        signal_class = classify_signal(evaluate_fn.__name__, reason or "")

        if direction:
            # IV Rank gate — skip buying when options are too expensive
            if iv_rank is not None:
                if iv_rank > IV_RANK_MAX:
                    log.warning(
                        f"  IV Rank={iv_rank:.0f}% > {IV_RANK_MAX}% — options overpriced. "
                        f"Skipping entry to avoid paying inflated premium."
                    )
                    if stop_event:
                        stop_event.wait(timeout=60)
                    else:
                        time.sleep(60)
                    continue
                elif iv_rank > IV_RANK_WARN:
                    log.warning(
                        f"  IV Rank={iv_rank:.0f}% — elevated. Proceeding with caution."
                    )

            # Surface similar past setups from memory before proceeding
            indicators_snapshot = _sanitize_indicators(bar.to_dict())
            memory_context = TRADE_MEMORY.retrieve_similar(symbol, direction, indicators_snapshot)
            if memory_context:
                log.info(memory_context)

            # Bull/Bear debate gate
            if DEBATE_ENABLED:
                proceed, conf, summary = _debate_mod.run_debate(
                    symbol, direction, indicators_snapshot, memory_context=memory_context
                )
                if not proceed or conf < DEBATE_MIN_CONFIDENCE:
                    log.warning(
                        f"Debate suppressed signal: conf={conf:.0%}  {summary or 'low confidence'}"
                    )
                    if stop_event:
                        stop_event.wait(timeout=60)
                    else:
                        time.sleep(60)
                    continue

            # Daily loss circuit-breaker + profit lock + global cooldown + per-signal news + time gates
            if (not first_entry_time_ok() or not last_entry_time_ok()
                    or not daily_loss_check(acct_val) or not daily_profit_check(acct_val)
                    or not global_cooldown_ok() or not news_check_ok(symbol)):
                if stop_event:
                    stop_event.wait(timeout=60)
                else:
                    time.sleep(60)
                continue

            # Portfolio-level risk gate — refuse new entries when total deployed
            # premium already consumes the daily risk budget across all symbols.
            deployed = deployed_risk_pct(acct_val)
            _port_cap = eff_max_portfolio_risk()
            if deployed >= _port_cap:
                log.warning(
                    f"  Portfolio risk {deployed*100:.1f}% >= max {_port_cap*100:.0f}% "
                    f"— no new entries until positions close."
                )
            elif not sector_risk_check(symbol):
                pass  # warning already logged inside sector_risk_check
            elif position_exists_for_symbol_direction(symbol, direction):
                log.info(f"  Duplicate guard: {symbol} {direction.upper()} position already open — skipping.")
            else:
                expiry = target_expiry(symbol)
                if not expiry:
                    log.warning(f"No {symbol} expiry in DTE range. Skipping.")
                else:
                    option, strike = find_atm_option(direction, expiry, current, symbol,
                                                        current_iv=current_iv)
                    if option:
                        mid, spread, _bid, ask = option_mid_and_spread(option)
                        log.info(f"  Found: ${strike} {expiry}  mid=${mid:.2f}  ask=${ask:.2f}  spread=${spread:.2f}")
                        if spread_acceptable(mid, spread):
                            contracts = size_contracts(acct_val, mid)
                            if contracts > 0:
                                place_trade(option, contracts, mid, direction, reason, atr, symbol,
                                            indicators=indicators_snapshot, ask_price=ask,
                                            underlying_price=current, signal_class=signal_class)
                                _record_global_trade()
                                traded = True
                        else:
                            spread_pct = spread / mid * 100 if mid > 0 else 999
                            log.warning(f"Spread ${spread:.2f} ({spread_pct:.0f}% of mid) too wide. Skipping.")
                    else:
                        log.warning(f"Could not find ATM {symbol} option. Skipping.")

        if not traded:
            if stop_event:
                stop_event.wait(timeout=60)
            else:
                time.sleep(60)

    if not traded:
        log.info(f"{session_name}: no valid setup triggered. Staying flat.")


# ── Sessions ──────────────────────────────────────────────────────────────────
def morning_session(prior_levels, vix, stop_event=None, end_hour=None, end_minute=None,
                    symbol: str = "SPY"):
    symbol = symbol.upper()
    eh = end_hour   if end_hour   is not None else MORNING_END[0]
    em = end_minute if end_minute is not None else MORNING_END[1]
    log.info("=" * 60)
    log.info(f"MORNING SESSION ({symbol})  —  ends at {eh:02d}:{em:02d} ET")
    log.info("=" * 60)

    earnings_risky, earnings_msg = check_earnings_risk(symbol)
    if earnings_risky:
        log.warning(earnings_msg)

    fetch_futures_context()    # logged; morning sessions don't gate on it
    fetch_market_breadth()     # logged; context only
    daily_ema200 = fetch_daily_ema200(symbol)
    _current_iv, iv_rank = fetch_iv_rank(symbol)
    if iv_rank is not None and iv_rank > IV_RANK_WARN:
        log.warning(f"  IV Rank={iv_rank:.0f}% — {'EXPENSIVE, entries will be skipped' if iv_rank > IV_RANK_MAX else 'elevated, proceed with caution'}")

    df = fetch_bars(symbol)
    if df is None:
        log.warning(f"Could not fetch {symbol} data. Skipping morning session.")
        return
    df = inject_daily_ema200(df, daily_ema200)

    prior_close = prior_levels.get("prev_close")
    gap_pct, gap_dir = detect_gap(df, prior_close)
    if gap_pct != 0:
        log.info(f"Pre-market gap: {gap_pct:+.2f}% ({gap_dir})")

    or_high, or_low = opening_range(df)
    if or_high is None:
        log.warning("Not enough bars for opening range.")
        return

    or_width = or_high - or_low
    or_width_pct = or_width / or_low
    last_atr = float(df["atr"].iloc[-1]) if "atr" in df.columns and not np.isnan(df["atr"].iloc[-1]) else None
    log.info(f"Opening range: ${or_low:.2f}–${or_high:.2f} (width {or_width_pct:.2%})")

    # ATR-relative tight check: range must be at least MIN_ORB_ATR_MULT * ATR.
    # Falls back to a tiny absolute floor (0.05%) when ATR is unavailable.
    width_too_tight = (
        (last_atr and or_width < MIN_ORB_ATR_MULT * last_atr)
        or (not last_atr and or_width_pct < 0.0005)
    )
    if width_too_tight:
        if last_atr:
            log.info(f"OR width ${or_width:.2f} < {MIN_ORB_ATR_MULT}×ATR ${last_atr:.2f} — ORB skipped, trying gap fade.")
        else:
            log.info("OR width too tight (no ATR) — ORB skipped, trying gap fade.")
        def gap_only(bar, prev_bar, df):
            return evaluate_gap_fade(bar, gap_pct, gap_dir, df)
        run_session("Morning (gap fade)", eh, em, gap_only, prior_levels,
                    stop_event=stop_event, symbol=symbol, daily_ema200=daily_ema200,
                    iv_rank=iv_rank, current_iv=_current_iv)
        return

    def morning_eval(bar, prev_bar, df):
        d, r = evaluate_orb(bar, prev_bar, or_high, or_low, df)
        if d: return d, r
        return evaluate_gap_fade(bar, gap_pct, gap_dir, df)

    run_session("Morning", eh, em, morning_eval, prior_levels,
                stop_event=stop_event, symbol=symbol, daily_ema200=daily_ema200,
                iv_rank=iv_rank, current_iv=_current_iv)


def evening_session(prior_levels, stop_event=None, end_hour=None, end_minute=None,
                    symbol: str = "SPY"):
    symbol = symbol.upper()
    eh = end_hour   if end_hour   is not None else EVENING_END[0]
    em = end_minute if end_minute is not None else EVENING_END[1]
    log.info("=" * 60)
    log.info(f"EVENING SESSION ({symbol})  —  ends at {eh:02d}:{em:02d} ET")
    log.info("=" * 60)

    earnings_risky, earnings_msg = check_earnings_risk(symbol)
    if earnings_risky:
        log.warning(earnings_msg)

    fetch_futures_context()    # logged; evening sessions don't gate on it
    fetch_market_breadth()     # logged; context only
    daily_ema200 = fetch_daily_ema200(symbol)
    _current_iv, iv_rank = fetch_iv_rank(symbol)
    if iv_rank is not None and iv_rank > IV_RANK_WARN:
        log.warning(f"  IV Rank={iv_rank:.0f}% — {'EXPENSIVE, entries will be skipped' if iv_rank > IV_RANK_MAX else 'elevated, proceed with caution'}")

    def evening_eval(bar, prev_bar, df):
        return evaluate_vwap_momentum(bar, prev_bar, df)

    run_session("Evening", eh, em, evening_eval, prior_levels,
                stop_event=stop_event, symbol=symbol, daily_ema200=daily_ema200,
                iv_rank=iv_rank, current_iv=_current_iv)


# ── All-day session (replaces separate morning/evening) ───────────────────────
def all_day_session(symbol: str = "SPY", prior_levels=None, vix=None,
                    stop_event=None, end_hour: int = 15, end_minute: int = 45):
    """All-day trading session: 9:30–end_hour:end_minute ET.

    Evaluator schedule:
      • 9:30–10:30  → ORB breakout + gap fade (opening-range phase)
      • All day      → VWAP momentum + gap fade as additional signals

    Multiple trades per day are allowed with a 5-minute cool-down between
    entries. Lunch-hour block (11:30–13:30 ET) is respected. The session stops
    when the stop_event fires or when the wall-clock passes end_hour:end_minute.
    """
    symbol = symbol.upper()
    prior_levels = prior_levels or {}

    log.info("=" * 60)
    log.info(f"ALL-DAY SESSION ({symbol}) — ends at {end_hour:02d}:{end_minute:02d} ET")
    log.info("=" * 60)
    log_account_profile()   # banner: which risk regime (sub-$10K vs standard) is active

    if not vix_check(vix):
        log.warning(f"VIX too high — {symbol} all-day session blocked.")
        return

    earnings_risky, earnings_msg = check_earnings_risk(symbol)
    if earnings_risky:
        log.warning(earnings_msg)

    futures_ctx    = fetch_futures_context()
    breadth_ctx    = fetch_market_breadth()

    acct_val = account_value()
    set_day_start_equity(acct_val)
    _load_positions()       # restore full position state (entry, stop, target, narrative)
    reconcile_positions()   # cross-check with Alpaca; add any positions missed by JSON
    log.info(f"Account: ${acct_val:,.2f}  |  Max risk: ${acct_val * eff_max_risk_pct():,.2f}  |  {symbol}")
    if prior_levels:
        log.info(
            f"Levels — Pivot={prior_levels.get('pivot')}  "
            f"R1={prior_levels.get('r1')}  S1={prior_levels.get('s1')}"
        )

    # Historical volume baseline — fixes NaN vol_ratio during the opening phase
    # (rolling-20 needs 100 min of today's bars; this uses prior sessions instead)
    hist_vol_baseline = fetch_historical_vol_baseline(symbol)

    def _apply_vol_baseline(df_in: pd.DataFrame) -> pd.DataFrame:
        """Override vol_ratio with historical baseline where the rolling avg is NaN."""
        if not hist_vol_baseline:
            return df_in
        df_out = df_in.copy()
        def _ratio(row):
            avg = hist_vol_baseline.get(row["begins_at"].strftime("%H:%M"))
            if avg and avg > 0:
                return round(float(row["volume"]) / avg, 3)
            return row["vol_ratio"]
        df_out["vol_ratio"] = df_out.apply(_ratio, axis=1)
        return df_out

    # Daily EMA200 — fetched once; injected into every intraday bar fetch.
    # Intraday EMA200 is meaningless (needs 13+ days of 5-min bars to stabilize).
    daily_ema200 = fetch_daily_ema200(symbol)

    # IV Rank + 30-min trend — computed once at session start, refreshed hourly.
    _current_iv, iv_rank = fetch_iv_rank(symbol)
    if iv_rank is not None:
        if iv_rank > IV_RANK_MAX:
            log.warning(
                f"  ⚠️  IVR={iv_rank:.0f}% — options EXPENSIVE. "
                f"Entries will be skipped until IV normalises below {IV_RANK_MAX}%."
            )
        elif iv_rank >= IV_RANK_SPREAD:
            log.warning(
                f"  ⚠️  IVR={iv_rank:.0f}% ≥ {IV_RANK_SPREAD}% — routing to debit spread (KB §2/§5)."
            )
        elif iv_rank > IV_RANK_WARN:
            log.warning(f"  ⚠️  IVR={iv_rank:.0f}% — elevated. Proceeding with caution.")
    htf_trend = fetch_30min_trend(symbol)

    # Compute opening-range data once at session start
    df_init = fetch_bars(symbol)
    if df_init is not None and not df_init.empty:
        df_init = _apply_vol_baseline(df_init)
        df_init = inject_daily_ema200(df_init, daily_ema200)
    or_high = or_low = None
    gap_pct = gap_dir = None

    if df_init is not None and not df_init.empty:
        prior_close = prior_levels.get("prev_close")
        gap_pct, gap_dir = detect_gap(df_init, prior_close)
        if gap_pct:
            log.info(f"Pre-market gap: {gap_pct:+.2f}% ({gap_dir})")
        or_high, or_low = opening_range(df_init)
        if or_high:
            width = (or_high - or_low) / or_low
            log.info(f"Opening range: ${or_low:.2f}–${or_high:.2f} (width {width:.2%})")

    session_end        = datetime.now(ET).replace(
        hour=end_hour, minute=end_minute, second=0, microsecond=0
    )
    last_trade_ts      = None  # 5-minute cool-down guard
    iv_rank_fetched_at = datetime.now(ET)  # track when IV rank was last refreshed
    last_bar_ts        = None  # same-bar guard: skip re-evaluation if bar hasn't advanced

    while datetime.now(ET) < session_end:
        if stop_event and stop_event.is_set():
            log.info(f"All-day session ({symbol}): stopped by user.")
            break

        now = datetime.now(ET)

        # Refresh IV rank + 30-min trend every IV_RANK_REFRESH_MIN minutes
        if (now - iv_rank_fetched_at).total_seconds() >= IV_RANK_REFRESH_MIN * 60:
            _current_iv, iv_rank = fetch_iv_rank(symbol)
            htf_trend = fetch_30min_trend(symbol)
            iv_rank_fetched_at = now
            if iv_rank is not None:
                tag = "EXPENSIVE" if iv_rank > IV_RANK_MAX else "elevated" if iv_rank > IV_RANK_WARN else "normal"
                log.info(f"  IV Rank refresh ({symbol}): IVR={iv_rank:.0f}% [{tag}]")

        if is_lunch_hour(symbol):
            log.info(f"Lunch-hour block (11:30–13:30 ET) for ETF {symbol}. Waiting 5 min…")
            if stop_event:
                if stop_event.wait(timeout=300):
                    break
            else:
                time.sleep(300)
            continue

        # Refresh account value each iteration for accurate loss checks and sizing
        acct_val = account_value()

        df = fetch_bars(symbol)
        if df is None or len(df) < 5:
            if stop_event:
                if stop_event.wait(timeout=60):
                    break
            else:
                time.sleep(60)
            continue

        df       = _apply_vol_baseline(df)
        df       = inject_daily_ema200(df, daily_ema200)
        # Bar selection: prefer the LIVE bar (-1) once its volume has matured to
        # ~60% of the historical average for that minute-of-day. Otherwise fall back
        # to the last completed bar (-2). This cuts reaction time from up-to-5-min
        # down to ~30s on most signals while still rejecting half-formed candles.
        live_bar = df.iloc[-1]
        last_completed = df.iloc[-2] if len(df) >= 2 else live_bar
        bar = last_completed
        if len(df) >= 2 and hist_vol_baseline:
            try:
                slot = live_bar["begins_at"].strftime("%H:%M")
                hist_avg = hist_vol_baseline.get(slot, 0)
                bar_age_min = max(0.0, (datetime.now(ET) - live_bar["begins_at"]).total_seconds() / 60)
                expected = hist_avg * (bar_age_min / 5.0) if hist_avg > 0 else 0
                if expected > 0 and float(live_bar["volume"]) >= 0.6 * expected:
                    bar = live_bar
            except Exception:
                pass  # any timestamp/lookup error → keep the safe last-completed bar
        prev_bar = (
            df.iloc[-2] if (bar is live_bar and len(df) >= 2)
            else (df.iloc[-3] if len(df) >= 3 else (df.iloc[-2] if len(df) >= 2 else df.iloc[-1]))
        )
        current  = float(bar["close_price"])
        atr      = float(bar["atr"]) if not np.isnan(bar["atr"]) else None
        ema200_str = f"{daily_ema200:.2f}" if daily_ema200 else "—"

        log.info(
            f"  {bar['begins_at'].strftime('%H:%M')}  "
            f"{symbol}=${current:.2f}  VWAP={bar['vwap']:.2f}  "
            f"EMA9={bar['ema9']:.2f}  EMA21={bar['ema21']:.2f}  EMA200d={ema200_str}  "
            f"RSI={bar['rsi']:.1f}  MACD={bar['macd_hist']:.3f}  "
            f"ATR={f'{atr:.2f}' if atr else '—'}  Vol={bar['vol_ratio']:.2f}x  "
            f"BB[{bar['bb_lower']:.2f}–{bar['bb_upper']:.2f}]"
        )

        # Same-bar guard — if the feed hasn't advanced, wait and retry
        bar_ts = bar["begins_at"]
        if bar_ts == last_bar_ts:
            if stop_event:
                stop_event.wait(timeout=60)
            else:
                time.sleep(60)
            continue
        last_bar_ts = bar_ts

        # Phase-based evaluator selection
        is_opening_phase = (now.hour == 9) or (now.hour == 10 and now.minute < 30)
        direction = reason = None
        signal_class = "unknown"

        if is_opening_phase and or_high and or_low:
            or_width = or_high - or_low
            # ATR-relative width gate: range must be >= MIN_ORB_ATR_MULT * ATR
            if atr and or_width >= MIN_ORB_ATR_MULT * atr:
                direction, reason = evaluate_orb(bar, prev_bar, or_high, or_low, df)
                if direction: signal_class = "orb_breakout"
            elif not atr and (or_width / or_low) >= 0.0005:
                # Fallback when ATR unavailable: tiny absolute floor
                direction, reason = evaluate_orb(bar, prev_bar, or_high, or_low, df)
                if direction: signal_class = "orb_breakout"

        if not direction and GAP_FADE_ENABLED and gap_pct and gap_dir:
            direction, reason = evaluate_gap_fade(bar, gap_pct, gap_dir, df)
            if direction: signal_class = "gap_fade"

        if not direction:
            direction, reason = evaluate_vwap_momentum(bar, prev_bar, df)
            if direction: signal_class = "vwap_momentum"

        # Last lane: trend-continuation by score + mean-reversion at extremes.
        # Catches the setups the strict gates above filter out (mid-day flow,
        # established trends, oversold bounces). Looser by design — relies on
        # the downstream gate stack (cooldown, IV rank, sector cap, etc).
        if not direction and TREND_CONT_ENABLED:   # item 17: gated off — the bleed
            direction, reason = evaluate_trend_continuation(bar, prev_bar, df)
            if direction:
                # Same evaluator returns both lanes — distinguish by reason prefix
                signal_class = "mean_rev" if (reason or "").startswith("Mean-rev") else "trend_cont"

        if direction:
            # ── Advisory chart marker — fire BEFORE the gate stack so the
            #    user sees EVERY real signal (currently vwap_momentum only;
            #    trend_cont/gap_fade are disabled noise) and decides for
            #    themselves. Decision-support, NOT an order. Wrapped so a
            #    callback error never breaks the trading loop.
            if ADVISORY_SIGNAL_CALLBACK is not None:
                try:
                    ADVISORY_SIGNAL_CALLBACK(symbol, direction, reason,
                                             current, signal_class)
                except Exception as _adv_e:
                    log.debug(f"advisory marker cb failed: {_adv_e}")

            # Cool-down: 5 min normally; 20 min after a stop hit
            last_stop = get_last_stop(symbol)
            stop_recently = (
                last_stop is not None
                and (now - last_stop["time"]).total_seconds() < STOP_COOLDOWN_SEC
            )
            cooldown_sec = STOP_COOLDOWN_SEC if stop_recently else 300
            if last_trade_ts and (now - last_trade_ts).total_seconds() < cooldown_sec:
                mins = cooldown_sec // 60
                log.info(f"  Cool-down active (< {mins} min since last entry). Waiting.")
                if stop_event:
                    stop_event.wait(timeout=60)
                else:
                    time.sleep(60)
                continue

            # Same-direction block after stop — don't re-enter the direction that lost
            if last_stop and (now - last_stop["time"]).total_seconds() < STOP_COOLDOWN_SEC:
                if last_stop["direction"] == direction:
                    log.warning(
                        f"  ⛔ Same-direction block: last stop was {direction.upper()} "
                        f"— waiting {STOP_COOLDOWN_SEC//60} min before re-entering same side."
                    )
                    if stop_event:
                        stop_event.wait(timeout=60)
                    else:
                        time.sleep(60)
                    continue

            # 30-min higher-timeframe trend filter — skip when signal opposes trend
            if htf_trend != "neutral" and htf_trend != direction:
                log.warning(
                    f"  ⚠️  HTF filter: 30-min trend={htf_trend.upper()} opposes "
                    f"{direction.upper()} signal — skipping counter-trend entry."
                )
                if stop_event:
                    stop_event.wait(timeout=60)
                else:
                    time.sleep(60)
                continue

            # IV Rank gate — skip when options are too expensive
            if iv_rank is not None and iv_rank > IV_RANK_MAX:
                log.warning(
                    f"  IV Rank={iv_rank:.0f}% > {IV_RANK_MAX}% — options overpriced. "
                    f"Skipping entry to avoid paying inflated premium."
                )
                if stop_event:
                    stop_event.wait(timeout=60)
                else:
                    time.sleep(60)
                continue
            if iv_rank is not None and iv_rank > IV_RANK_WARN:
                log.warning(f"  IV Rank={iv_rank:.0f}% — elevated. Proceeding with caution.")

            indicators_snapshot = _sanitize_indicators(bar.to_dict())
            if futures_ctx:
                indicators_snapshot["futures_bias"]           = futures_ctx.get("futures_bias", "neutral")
                indicators_snapshot["es_direction"]           = futures_ctx.get("es_direction", "flat")
                indicators_snapshot["es_overnight_range_pct"] = futures_ctx.get("es_overnight_range_pct", 0)
            if breadth_ctx:
                indicators_snapshot["breadth_bias"]  = breadth_ctx.get("breadth_bias", "neutral")
                indicators_snapshot["pcr_equity"]    = breadth_ctx.get("pcr_equity")
                indicators_snapshot["qqq_vs_spy"]    = breadth_ctx.get("qqq_vs_spy")
                indicators_snapshot["pcr_signal"]    = breadth_ctx.get("pcr_signal", "neutral")

            # Log breadth/futures alignment warning if they oppose the signal
            if breadth_ctx:
                b_bias = breadth_ctx.get("breadth_bias", "neutral")
                if b_bias != "neutral" and b_bias != direction:
                    log.warning(
                        f"  ⚠️  Breadth bias={b_bias} opposes {direction} signal — "
                        f"proceed with reduced conviction."
                    )
            if futures_ctx:
                f_bias = futures_ctx.get("futures_bias", "neutral")
                if f_bias != "neutral" and f_bias != direction:
                    log.warning(
                        f"  ⚠️  Futures bias={f_bias} opposes {direction} signal — "
                        f"proceed with reduced conviction."
                    )

            memory_context = TRADE_MEMORY.retrieve_similar(symbol, direction, indicators_snapshot)
            if memory_context:
                log.info(memory_context)

            if DEBATE_ENABLED:
                proceed, conf, summary = _debate_mod.run_debate(
                    symbol, direction, indicators_snapshot, memory_context=memory_context
                )
                if not proceed or conf < DEBATE_MIN_CONFIDENCE:
                    log.warning(
                        f"Debate suppressed signal: conf={conf:.0%}  "
                        f"{summary or 'low confidence'}"
                    )
                    if stop_event:
                        stop_event.wait(timeout=60)
                    else:
                        time.sleep(60)
                    continue

            if not first_entry_time_ok() or not last_entry_time_ok():
                if stop_event:
                    stop_event.wait(timeout=60)
                else:
                    time.sleep(60)
                continue

            if not daily_loss_check(acct_val):
                if stop_event:
                    stop_event.wait(timeout=60)
                else:
                    time.sleep(60)
                continue

            if not daily_profit_check(acct_val):
                if stop_event:
                    stop_event.wait(timeout=60)
                else:
                    time.sleep(60)
                continue

            if not weekly_drawdown_check(acct_val):
                if stop_event:
                    stop_event.wait(timeout=60)
                else:
                    time.sleep(60)
                continue

            if emergency_halt_active():
                log.info(f"  🛑 Emergency halt active — skipping {symbol}.")
                if stop_event:
                    stop_event.wait(timeout=60)
                else:
                    time.sleep(60)
                continue

            if not gap_day_delay_ok(symbol):
                if stop_event:
                    stop_event.wait(timeout=120)
                else:
                    time.sleep(120)
                continue

            if not macro_event_blackout_ok():
                if stop_event:
                    stop_event.wait(timeout=180)
                else:
                    time.sleep(180)
                continue

            # PDT guard (self-enforced, sub-$25K accounts) — never take the
            # trade that would become the 4th day-trade in 5 business days.
            if not pdt_sub25k_ok():
                if stop_event:
                    stop_event.wait(timeout=300)
                else:
                    time.sleep(300)
                continue

            # Global cross-symbol cooldown — prevent two symbols firing in the same second
            if not global_cooldown_ok():
                log.info(f"  Global cooldown ({GLOBAL_COOLDOWN_SEC}s) active across symbols — waiting.")
                if stop_event:
                    stop_event.wait(timeout=30)
                else:
                    time.sleep(30)
                continue

            # Per-signal news re-check — catches mid-session halt headlines
            # that the session-start filter missed.
            if not news_check_ok(symbol):
                if stop_event:
                    stop_event.wait(timeout=60)
                else:
                    time.sleep(60)
                continue

            # Data-staleness gate: refuse to trade if bars are older than
            # DATA_MAX_AGE_SEC. The signal direction comes from bars — if those
            # are stale we're trading old data. Option-quote staleness is checked
            # implicitly below: a stale quote returns $0 mid which short-circuits
            # via `if mid <= 0`. Spot price (used by chart) is intentionally not
            # gated here — it's not on the trade's critical path.
            if not stale_data_check(symbol, kinds=("bars",)):
                if stop_event:
                    stop_event.wait(timeout=60)
                else:
                    time.sleep(60)
                continue

            deployed = deployed_risk_pct(acct_val)
            _port_cap = eff_max_portfolio_risk()
            if deployed >= _port_cap:
                log.warning(
                    f"  Portfolio risk {deployed*100:.1f}% >= max {_port_cap*100:.0f}% "
                    f"— no new entries until positions close."
                )
            elif not sector_risk_check(symbol):
                pass  # warning already logged inside sector_risk_check
            elif not portfolio_delta_check(acct_val, intended_direction=direction):
                pass  # warning already logged
            elif not daily_entries_ok():
                _cap = SUB_PDT_MAX_DAILY_ENTRIES if _is_sub_pdt_account() else MAX_DAILY_ENTRIES
                log.info(f"  Daily entry cap reached ({_cap}/day{' — sub-$25K PDT-aware' if _is_sub_pdt_account() else ''}) — manage-only for the rest of the day.")
            elif position_exists_for_symbol_direction(symbol, direction):
                log.info(f"  Duplicate guard: {symbol} {direction.upper()} position already open — skipping.")
            else:
                expiry = target_expiry(symbol)
                if not expiry:
                    log.warning(f"No {symbol} expiry in DTE range. Skipping.")
                elif not friday_gamma_ok(expiry):
                    pass  # warning already logged
                else:
                    option, strike = find_atm_option(direction, expiry, current, symbol,
                                                        current_iv=_current_iv)
                    if option:
                        mid, spread, _bid, ask = option_mid_and_spread(option)
                        # KB §2: IVR ≥ IV_RANK_SPREAD → debit spread; else naked long
                        use_spread = (iv_rank is not None and iv_rank >= IV_RANK_SPREAD)
                        route_tag  = f"SPREAD (IVR={iv_rank:.0f}%)" if use_spread else "NAKED"
                        log.info(
                            f"  Found: ${strike} {expiry}  mid=${mid:.2f}  "
                            f"ask=${ask:.2f}  spread=${spread:.2f}  route={route_tag}"
                        )
                        if spread_acceptable(mid, spread):
                            order = None
                            if use_spread:
                                # ── Debit spread path (KB §2, §5) ──────────────
                                short_option, short_strike = find_otm_option(
                                    direction, expiry, strike, current, symbol,
                                    current_iv=_current_iv,
                                )
                                if short_option:
                                    _, _s, short_bid, _sa = option_mid_and_spread(short_option)
                                    net_debit = round(mid - short_bid, 2)
                                    width     = abs(float(short_option["strike_price"]) - strike)
                                    ratio     = net_debit / width if width > 0 else 999
                                    if net_debit > 0 and 0.20 <= ratio <= 0.50:
                                        contracts = size_contracts(acct_val, net_debit)
                                        if contracts > 0:
                                            try:
                                                order = place_spread_trade(
                                                    option, short_option, contracts, net_debit,
                                                    direction, reason, atr, symbol,
                                                    indicators=indicators_snapshot,
                                                    underlying_price=current,
                                                    signal_class=signal_class,
                                                )
                                            except Exception as _exc:
                                                log.error(f"place_spread_trade raised: {_exc}", exc_info=True)
                                    else:
                                        log.warning(
                                            f"  Spread ratio {ratio:.2f} outside 0.20–0.50 or debit≤0 "
                                            f"— falling back to naked."
                                        )
                                else:
                                    log.warning("  Spread short leg not found — falling back to naked.")

                            if not use_spread or order is None:
                                # ── Naked long path (KB §2: IVR < 30%) ─────────
                                contracts = size_contracts(acct_val, mid)
                                if contracts > 0:
                                    try:
                                        order = place_trade(
                                            option, contracts, mid, direction, reason, atr, symbol,
                                            indicators=indicators_snapshot, ask_price=ask,
                                            underlying_price=current, signal_class=signal_class,
                                        )
                                    except Exception as _place_exc:
                                        log.error(f"place_trade raised unexpectedly: {_place_exc}", exc_info=True)
                                        order = None

                            last_trade_ts = now
                            _record_global_trade()
                            if order:
                                record_daily_entry()
                            if order and not DRY_RUN:
                                filled_qty = wait_for_fill(str(order.id), stop_event=stop_event)
                                if filled_qty > 0:
                                    acct_val = account_value()
                                    update_slippage_for_order(str(order.id), target_mid=mid)
                                    _notify_fill()
                                else:
                                    log.warning(
                                        f"Entry order {order.id} not filled — removing position."
                                    )
                                    with _positions_lock:
                                        _open_positions[:] = [
                                            p for p in _open_positions
                                            if p.get("order_id") != str(order.id)
                                        ]
                        elif mid <= 0:
                            log.warning(
                                f"  Option quote returned mid=$0 — Alpaca returned no bid/ask. "
                                f"Market may be closed or option data unavailable for {symbol}."
                            )
                        else:
                            spread_pct = spread / mid * 100 if mid > 0 else 999
                            log.warning(
                                f"  Spread ${spread:.2f} ({spread_pct:.0f}% of mid) too wide — skipping {symbol}."
                            )

        if stop_event:
            stop_event.wait(timeout=60)
        else:
            time.sleep(60)

    log.info(f"All-day session ({symbol}) complete.")


# ── Position registry ─────────────────────────────────────────────────────────
_open_positions: list[dict] = []
_positions_lock = threading.Lock()

# ── Position persistence ──────────────────────────────────────────────────────
_SPY_DIR        = os.path.expanduser("~/.spy_trader")
_POSITIONS_FILE = os.path.join(_SPY_DIR, "open_positions.json")

def _save_positions() -> None:
    """Persist _open_positions to disk (must be called while holding _positions_lock)."""
    try:
        os.makedirs(_SPY_DIR, exist_ok=True)
        tmp = _POSITIONS_FILE + ".tmp"
        data = json.dumps(_open_positions, default=str)
        with open(tmp, "w") as fh:
            fh.write(data)
        os.replace(tmp, _POSITIONS_FILE)
    except Exception as e:
        log.warning(f"_save_positions failed: {e}")




def _load_positions() -> int:
    """Load persisted positions from disk into _open_positions. Returns count loaded.

    Called once at session start before reconcile_positions(). Real-Alpaca
    positions that exist in both sources are de-duped by occ_symbol — the
    persisted entry wins because it has our original stop/T1/T2 levels.
    Dry-run positions (is_dry_run=True) come back exactly as they were.
    """
    if not os.path.exists(_POSITIONS_FILE):
        return 0
    try:
        with open(_POSITIONS_FILE) as f:
            saved = json.load(f)
        if not isinstance(saved, list):
            return 0
        loaded = 0
        with _positions_lock:
            known = {p["occ_symbol"] for p in _open_positions}
            for p in saved:
                if not isinstance(p, dict) or "occ_symbol" not in p:
                    continue
                if p.get("remaining", 0) <= 0:
                    continue  # closed positions left over from a partial save
                if p["occ_symbol"] in known:
                    continue
                # Defensive defaults for fields added after the file was written
                p.setdefault("is_dry_run", False)
                p.setdefault("breakeven_armed", False)
                p.setdefault("stop_breach_count", 0)
                p.setdefault("close_attempted", False)
                p.setdefault("close_client_id", None)
                p.setdefault("partial_done", False)
                p.setdefault("peak_mid_after_t1", 0.0)
                p.setdefault("narrative", "")
                p.setdefault("signal_class", "unknown")  # legacy positions before signal-class attribution
                _open_positions.append(p)
                known.add(p["occ_symbol"])
                loaded += 1
        if loaded:
            log.info(f"Restored {loaded} open position(s) from {_POSITIONS_FILE}")
        return loaded
    except Exception as e:
        log.warning(f"_load_positions failed: {e}")
        return 0

# ── Stop-hit registry ─────────────────────────────────────────────────────────
# Maps symbol → {"direction": str, "time": datetime} for the most recent stop.
# Written by check_positions(); read by all_day_session() to extend cooldown
# and block same-direction re-entry.
_last_stop: dict[str, dict] = {}
_stop_lock = threading.Lock()

# Negative cache: remember (symbol, tf) pairs where Alpaca returned 0 bars so
# subsequent calls skip the 3-feed retry loop and go straight to yfinance.
_alpaca_zero_cache: dict[tuple, float] = {}
_ALPACA_ZERO_TTL = 300  # seconds — re-try Alpaca after 5 min (catches market-open transitions)
STOP_COOLDOWN_SEC  = 1200   # 20-min cooldown after a stop hit (vs 5 min normally)

def record_stop_hit(symbol: str, direction: str) -> None:
    with _stop_lock:
        _last_stop[symbol.upper()] = {
            "direction": direction,
            "time":      datetime.now(ET),
        }

def get_last_stop(symbol: str) -> Optional[dict]:
    with _stop_lock:
        return _last_stop.get(symbol.upper())


def classify_signal(evaluator_name: str, reason: str = "") -> str:
    """Map an evaluator function name + reason string to a signal_class tag.

    See knowledge_base.md §17c (Cofnas's 11 categories) for the taxonomy.
    Used by register_trade() to persist per-trade strategy attribution so
    EOD review can split P&L by signal class.
    """
    if evaluator_name == "evaluate_orb":
        return "orb_breakout"
    if evaluator_name == "evaluate_gap_fade":
        return "gap_fade"
    if evaluator_name == "evaluate_vwap_momentum":
        return "vwap_momentum"
    if evaluator_name == "evaluate_trend_continuation":
        # This evaluator has two lanes — distinguish by reason prefix.
        if reason.startswith("Mean-rev"):
            return "mean_rev"
        return "trend_cont"
    return "unknown"


def place_spread_trade(long_option, short_option, contracts: int, net_debit: float,
                       direction: str, reason: str, atr=None, symbol: str = "SPY",
                       indicators: dict = None, underlying_price: float = 0.0,
                       signal_class: str = "unknown"):
    """
    Submit a debit spread (BTO long leg + STO short leg) and register the position.

    KB §5: debit spread for IVR 30–70%. Stop = 50% of net debit (KB §9).
    Net debit = long_mid − short_bid. Max loss = net_debit × contracts × 100.

    Spread exit logic piggybacks on the existing check_positions() monitor via the
    long-leg OCC symbol. short_occ is stored in the position dict so _close_spread_short_leg()
    can BTC it alongside every STC of the long leg.
    """
    symbol     = symbol.upper()
    long_occ   = long_option["symbol"]
    short_occ  = short_option["symbol"]
    long_strike  = long_option["strike_price"]
    short_strike = short_option["strike_price"]
    expiry       = long_option["expiration_date"]
    opt_type     = long_option["type"]
    width        = abs(float(short_strike) - float(long_strike))
    max_loss     = round(net_debit * contracts * 100, 2)

    stop_opt   = round(net_debit * (1 - STOP_LOSS_PCT), 2)   # KB §9: 50% stop
    target_50  = round(net_debit * 1.50, 2)
    target_75  = round(net_debit * (1 + PROFIT_TARGET), 2)

    log.info("─" * 60)
    log.info(f"SPREAD SIGNAL [{direction.upper()}]  {reason}")
    log.info(f"  Long leg : {symbol} {expiry} ${long_strike} {opt_type.upper()} ({long_occ})")
    log.info(f"  Short leg: {symbol} {expiry} ${short_strike} {opt_type.upper()} ({short_occ})")
    log.info(f"  Width    : ${width:.2f}  Net debit: ${net_debit:.2f}  ({contracts} contract(s))")
    log.info(f"  Max loss : ${max_loss:,.2f}  |  Stop: ${stop_opt:.2f} (-{int(STOP_LOSS_PCT*100)}%)")
    log.info(f"  Target 1 : ${target_50:.2f}  (+50%)  Target 2: ${target_75:.2f}  (+{int(PROFIT_TARGET*100)}%)")
    log.info(f"  Mode     : {'PAPER' if PAPER_MODE else 'LIVE'}  [KB §5 debit spread, IVR≥{IV_RANK_SPREAD}%]")
    log.info("─" * 60)

    details = {
        "direction":   direction, "reason": reason, "symbol": symbol,
        "occ_symbol":  long_occ,  "short_occ": short_occ,
        "expiry":      expiry,    "type": opt_type,
        "contracts":   contracts, "net_debit": net_debit,
        "stop_price":  stop_opt,  "target_50": target_50, "target_75": target_75,
        "max_loss":    max_loss,  "width": width,
        "dry_run":     DRY_RUN,   "paper": PAPER_MODE,
        "_indicators": indicators or {},
    }

    if TRADE_CONFIRM_CALLBACK is not None:
        approved = TRADE_CONFIRM_CALLBACK(details)
    elif DRY_RUN:
        approved = False
    else:
        confirm = input(
            f"\n⚠️  SPREAD ORDER: {contracts}x {long_occ}/{short_occ} net=${net_debit:.2f}? (yes/no): "
        ).strip().lower()
        approved = confirm == "yes"

    if DRY_RUN:
        verdict = "ALLOWED" if approved else "SKIPPED"
        log.info(f"[DRY RUN] Spread {verdict} — no order placed.")
        if approved:
            dry_id = f"DRY_SPR_{long_occ}_{int(time.time() * 1000)}"
            _narr  = generate_signal_narrative(details)
            pos_record = register_trade(
                long_occ, net_debit, contracts, direction, symbol,
                order_id=dry_id, is_dry_run=True, narrative=_narr,
                signal_class=signal_class,
            )
            # Tag the position dict with short_occ for spread close
            with _positions_lock:
                for p in _open_positions:
                    if p["occ_symbol"] == long_occ and p.get("order_id") == dry_id:
                        p["short_occ"] = short_occ
                        p["net_debit"] = net_debit
                        p["spread_width"] = width
                        break
            _notify_fill()
        return None

    if not approved:
        log.info("Spread trade skipped by user.")
        return None

    if not pdt_check():
        return None

    # BTO long leg
    try:
        cid_long = f"spr_long_{long_occ}_{int(time.time())}"
        long_mid, _spread, _bid, long_ask = option_mid_and_spread(long_option)
        long_limit = round(long_mid + 0.05, 2)
        long_order = TRADING_CLIENT.submit_order(LimitOrderRequest(
            symbol          = long_occ,
            qty             = contracts,
            side            = OrderSide.BUY,
            type            = OrderType.LIMIT,
            time_in_force   = TimeInForce.DAY,
            limit_price     = long_limit,
            client_order_id = f"{cid_long}_mid",
        ))
        log.info(f"BTO {contracts}x {long_occ} @ ${long_limit:.2f}  id={long_order.id}")
    except Exception as e:
        log.error(f"BTO {long_occ} failed: {e}")
        return None

    # STO short leg
    short_order_id = None
    try:
        cid_short = f"spr_short_{short_occ}_{int(time.time())}"
        short_mid, _spread, short_bid, _ask = option_mid_and_spread(short_option)
        short_limit = round(max(short_bid - 0.05, short_bid * 0.90, 0.01), 2)
        short_order = TRADING_CLIENT.submit_order(LimitOrderRequest(
            symbol          = short_occ,
            qty             = contracts,
            side            = OrderSide.SELL,
            type            = OrderType.LIMIT,
            time_in_force   = TimeInForce.DAY,
            limit_price     = short_limit,
            client_order_id = f"{cid_short}_mid",
        ))
        short_order_id = str(short_order.id)
        log.info(f"STO {contracts}x {short_occ} @ ${short_limit:.2f}  id={short_order_id}")
    except Exception as e:
        log.warning(f"STO {short_occ} failed: {e} — spread now naked long, monitor closely")

    # Register position using long leg — stop/targets based on net_debit
    _narr = generate_signal_narrative(details)
    register_trade(
        long_occ, net_debit, contracts, direction, symbol,
        order_id=str(long_order.id), is_dry_run=False,
        narrative=_narr, signal_class=signal_class,
    )
    # Attach spread metadata so _close_spread_short_leg() can BTC the short leg
    with _positions_lock:
        for p in _open_positions:
            if p["occ_symbol"] == long_occ and p.get("order_id") == str(long_order.id):
                p["short_occ"]    = short_occ
                p["net_debit"]    = net_debit
                p["spread_width"] = width
                break
    _notify_fill()
    TRADE_MEMORY.record(
        symbol=symbol, direction=direction,
        indicators=details.get("_indicators", {}),
        entry_price=net_debit, trade_id=str(long_order.id),
        is_dry_run=False,
    )
    return long_order


def register_trade(occ_symbol: str, entry_price: float, contracts: int,
                   direction: str, symbol: str, order_id: Optional[str] = None,
                   is_dry_run: bool = False, narrative: str = "",
                   signal_class: str = "unknown") -> None:
    """Register a new position for the monitor after an order is submitted.

    Stop/target levels follow the swing-style risk profile:
      stop      = entry × (1 - STOP_LOSS_PCT)            — initial protective stop
      partial   = entry × (1 + PARTIAL_TRIGGER_PCT)      — close PARTIAL_QTY_FRAC here
      target    = entry × (1 + PROFIT_TARGET)            — close remainder
      breakeven = stop is moved to entry once pnl_frac >= BREAKEVEN_TRIGGER_PCT

    signal_class taxonomy (Cofnas-mapped — see knowledge_base.md §17c):
      "orb_breakout"   — first 30 min ORB break with volume confirmation
      "gap_fade"       — gap > GAP_THRESHOLD, fade back to VWAP
      "vwap_momentum"  — price above/below VWAP with EMA alignment + volume
      "trend_cont"     — multi-factor score (EMA stacking + RSI + MACD)
      "mean_rev"       — extreme RSI bounce (oversold/overbought reversal)
      "reconciled"     — orphan position recovered from Alpaca (no original signal)
      "unknown"        — caller didn't tag (legacy / dry-run / etc.)
    """
    stop_price = round(entry_price * (1 - STOP_LOSS_PCT), 2)
    tgt_50     = round(entry_price * (1 + PARTIAL_TRIGGER_PCT), 2)
    tgt_75     = round(entry_price * (1 + PROFIT_TARGET),       2)
    pos = {
        "occ_symbol":   occ_symbol,
        "symbol":       symbol.upper(),
        "direction":    direction,
        "entry_price":  entry_price,
        "stop_price":   stop_price,
        "target_50":    tgt_50,
        "target_75":    tgt_75,
        "contracts":    contracts,
        "remaining":    contracts,
        "order_id":     order_id,
        "partial_done":    False,
        "close_attempted": False,  # prevents duplicate close orders on full exits
        "opened_at":       datetime.now(ET).isoformat(),
        "stop_breach_count": 0,    # consecutive monitor cycles below stop_price (bid)
        "close_client_id": None,   # idempotency for close orders — reused on retry
        "breakeven_armed": False,  # set True once stop_price moved to entry on +30%
        "is_dry_run":      is_dry_run,  # captured at entry — close path branches on this
        "peak_mid_after_t1": 0.0,  # high-water mark for the trailing stop
        "narrative":       narrative,  # LLM-generated rationale for this entry
        "signal_class":    signal_class,  # for per-strategy P&L attribution in EOD
    }
    with _positions_lock:
        _open_positions.append(pos)
    _save_positions()
    log.info(
        f"Position registered: {occ_symbol} {contracts}x  "
        f"entry=${entry_price:.2f}  stop=${stop_price:.2f}  "
        f"T1=${tgt_50:.2f} (+{int(PARTIAL_TRIGGER_PCT*100)}% close {int(PARTIAL_QTY_FRAC*100)}%)  "
        f"T2=${tgt_75:.2f} (+{int(PROFIT_TARGET*100)}%)  "
        f"class={signal_class}"
    )


_SLIPPAGE_FILE = os.path.expanduser("~/.spy_trader/slippage_history.json")
_slippage_lock = threading.Lock()


def _record_slippage(order_id: str, bps: float, modeled_bps: float = 3.0) -> None:
    """Append a realized-slippage observation (3R-C.2).

    bps         : realized slippage in basis points (positive = paid up vs mid)
    modeled_bps : the assumed slippage used in the backtest (default 3 bp).
                  If realized > 2× modeled, a warning is logged.

    Persistent so the UI can show a rolling trend and delta vs model.
    """
    delta = round(bps - modeled_bps, 1)
    if abs(delta) > modeled_bps * 2:
        log.warning(
            f"  ⚠ Slippage alert: order={order_id} realized={bps:+.1f}bp "
            f"vs modeled={modeled_bps:.1f}bp (delta={delta:+.1f}bp — >2× modeled)"
        )
    with _slippage_lock:
        try:
            hist = []
            if os.path.exists(_SLIPPAGE_FILE):
                with open(_SLIPPAGE_FILE) as f:
                    hist = json.load(f)
            hist.append({
                "ts":          datetime.now(ET).isoformat(),
                "order":       order_id,
                "bps":         bps,
                "modeled_bps": modeled_bps,
                "delta_bps":   delta,
            })
            hist = hist[-200:]   # keep last 200 fills
            os.makedirs(os.path.dirname(_SLIPPAGE_FILE), exist_ok=True)
            tmp = _SLIPPAGE_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(hist, f)
            os.replace(tmp, _SLIPPAGE_FILE)
        except Exception as e:
            log.warning(f"_record_slippage failed: {e}")


def slippage_snapshot() -> dict:
    """Rolling slippage stats for the UI (3R-C.2).

    Includes vs-modeled delta: if realized slippage consistently exceeds the
    backtest assumption the edge degrades silently — this surfaces it.
    """
    try:
        with _slippage_lock:
            if not os.path.exists(_SLIPPAGE_FILE):
                return {"n": 0}
            with open(_SLIPPAGE_FILE) as f:
                hist = json.load(f)
    except Exception:
        return {"n": 0}
    if not hist:
        return {"n": 0}
    recent_hist = hist[-30:]
    last = [h["bps"] for h in recent_hist]
    n = len(last)
    avg = round(sum(last) / n, 1)
    trend = "flat"
    if n >= 6:
        half = n // 2
        prior = sum(last[:half]) / half
        recent = sum(last[half:]) / (n - half)
        if recent > prior + 2:   trend = "worsening"
        elif recent < prior - 2: trend = "improving"
    # vs-modeled delta (3R-C.2): avg delta over last 30 fills
    deltas = [h.get("delta_bps", h["bps"] - 3.0) for h in recent_hist]
    avg_delta = round(sum(deltas) / len(deltas), 1) if deltas else 0.0
    return {
        "n": n,
        "avg_bps": avg,
        "last_bps": round(last[-1], 1),
        "worst_bps": round(max(last), 1),
        "trend": trend,
        "spark": [round(x, 1) for x in last],
        "avg_delta_vs_model": avg_delta,
        "model_alert": avg_delta > 3.0,   # realizing >2× the 3bp assumption
    }


# ── Gate-fire telemetry (3R-C.3) ─────────────────────────────────────────────
_GATE_STATS_FILE = os.path.expanduser("~/.spy_trader/gate_stats.json")
_gate_stats_lock = threading.Lock()


def _record_gate_stats(counts: dict, n_closed: int, win_rate: float,
                       profit_factor: float, expectancy: float) -> None:
    """Append a per-session gate-fire record. Called from eod_review().

    Captures: signals fired, suppressed per gate, taken — so Phase 1 produces
    *learning* (gate behavior data) not just a vanity P&L curve.
    """
    entry = {
        "date":              datetime.now(ET).strftime("%Y-%m-%d"),
        "signals_fired":     counts.get("signal", 0),
        "orders_placed":     counts.get("order", 0),
        "dry_run_skipped":   counts.get("dry_run", 0),
        "gates": {
            "iv_rank":    counts.get("iv_gate", 0),
            "volume":     counts.get("vol_gate", 0),
            "news_veto":  counts.get("news_veto", 0),
            "debate_no":  counts.get("debate_no", 0),
            "debate_ok":  counts.get("debate_ok", 0),
        },
        "exits": {
            "stops":      counts.get("stop", 0),
            "t1_partial": counts.get("target1", 0),
            "t2_full":    counts.get("target2", 0),
            "hard_close": counts.get("hard_close", 0),
        },
        "closed_trades":  n_closed,
        "win_rate":       round(win_rate, 1),
        "profit_factor":  round(profit_factor, 3) if profit_factor != float("inf") else None,
        "expectancy_pct": round(expectancy, 3),
        "paper_mode":     PAPER_MODE,
    }
    with _gate_stats_lock:
        try:
            os.makedirs(os.path.dirname(_GATE_STATS_FILE), exist_ok=True)
            history: list = []
            if os.path.exists(_GATE_STATS_FILE):
                with open(_GATE_STATS_FILE) as f:
                    history = json.load(f)
            history.append(entry)
            tmp = _GATE_STATS_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(history, f, indent=2)
            os.replace(tmp, _GATE_STATS_FILE)
        except Exception as e:
            log.warning(f"_record_gate_stats failed: {e}")


# ── Failure-mode log (3R-C.4) ────────────────────────────────────────────────
_FAILURE_LOG_FILE = os.path.expanduser("~/.spy_trader/failure_log.json")
_failure_log_lock = threading.Lock()


def log_failure(event_type: str, detail: str, context: Optional[dict] = None) -> None:
    """Append a failure-mode event to the append-only failure log.

    event_type : short category e.g. "crash", "reconcile_drift", "fill_timeout",
                 "watchdog_restart", "desync"
    detail     : human-readable description
    context    : optional dict of relevant state at the time of failure

    This is what paper trading is legitimately for — learning failure modes
    cheaply before they happen with real money. Every crash/desync/retry
    should be logged here so Phase-1→2 gate can verify "no unsolved crashes."
    """
    entry = {
        "ts":         datetime.now(ET).isoformat(),
        "event_type": event_type,
        "detail":     detail,
        "context":    context or {},
        "paper_mode": PAPER_MODE,
    }
    with _failure_log_lock:
        try:
            os.makedirs(os.path.dirname(_FAILURE_LOG_FILE), exist_ok=True)
            history: list = []
            if os.path.exists(_FAILURE_LOG_FILE):
                with open(_FAILURE_LOG_FILE) as f:
                    history = json.load(f)
            history.append(entry)
            tmp = _FAILURE_LOG_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(history, f, indent=2)
            os.replace(tmp, _FAILURE_LOG_FILE)
            log.warning(f"[failure-log] {event_type}: {detail}")
        except Exception as e:
            log.warning(f"log_failure write failed: {e}")


def update_slippage_for_order(order_id: str, target_mid: float) -> None:
    """Look up the actual fill price for a recently-submitted order and compute
    realized slippage in basis points vs the target mid we aimed for.

    Stored on the position dict under `entry_slippage_bps`. Negative = filled
    cheaper than mid (rare); positive = paid up vs mid (the usual case).
    """
    if not TRADING_CLIENT or not order_id or target_mid <= 0:
        return
    try:
        order = TRADING_CLIENT.get_order_by_id(order_id)
        fill = float(order.filled_avg_price or 0)
        if fill <= 0:
            return
        slip_bps = round((fill - target_mid) / target_mid * 10000, 1)
        _record_slippage(order_id, slip_bps)   # persist for the trend tile
        with _positions_lock:
            for p in _open_positions:
                if p.get("order_id") == order_id:
                    p["actual_fill_price"]   = fill
                    p["target_mid"]          = target_mid
                    p["entry_slippage_bps"]  = slip_bps
                    log.info(
                        f"  Slippage {p['occ_symbol']}: fill=${fill:.2f} vs target=${target_mid:.2f} "
                        f"→ {slip_bps:+.1f} bps"
                    )
                    break
        _save_positions()
    except Exception as e:
        log.warning(f"update_slippage_for_order({order_id}): {e}")


def open_positions_snapshot() -> list[dict]:
    """Thread-safe copy of the open positions list for the UI."""
    with _positions_lock:
        return [dict(p) for p in _open_positions]


def position_exists_for_symbol_direction(symbol: str, direction: str) -> bool:
    """True if any open position matches symbol+direction.

    Stops the "open AMZN calls 9 separate times" averaging-into-non-mover
    pattern observed today. Cool-down only protects against time-too-close;
    this protects against duplicate exposure regardless of cool-down state.
    """
    sym = symbol.upper()
    with _positions_lock:
        for p in _open_positions:
            if p.get("remaining", 0) > 0 and p.get("symbol") == sym and p.get("direction") == direction:
                return True
    return False


def _fetch_real_entry(occ_symbol: str, fallback: float) -> float:
    """Look up the most recent filled BUY order for `occ_symbol` and return its
    filled_avg_price — the actual premium we paid.

    Critical for reconciliation: register_trade() derives stop/target from the
    entry price we pass in. avg_entry_price from get_all_positions() is fine for
    P&L but it includes any partial closes, so a position that filled at $5.00
    and partially closed at $7.50 reports avg_entry_price as something else.
    """
    if not TRADING_CLIENT:
        return fallback
    try:
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums    import QueryOrderStatus
        orders = TRADING_CLIENT.get_orders(filter=GetOrdersRequest(
            status  = QueryOrderStatus.CLOSED,
            symbols = [occ_symbol],
            side    = OrderSide.BUY,
            limit   = 20,
        ))
        for o in orders:
            if str(o.status).lower() == "filled" and o.filled_avg_price:
                price = float(o.filled_avg_price)
                if price > 0:
                    return price
    except Exception as e:
        log.warning(f"_fetch_real_entry({occ_symbol}): {e}")
    return fallback


def reconcile_positions() -> int:
    """Sync _open_positions with persisted state + actual Alpaca option positions.

    Pipeline:
      1. Load anything we persisted to disk (carries our original stop/T1/T2 +
         dry-run flag through the restart).
      2. Query Alpaca for real option positions; add any that aren't already
         tracked (covers orphans from a different host or external close).

    Returns count of NEW positions added from Alpaca (persisted ones don't count
    as new). Call at session start and after any unexpected restart.

    Entry price for orphans is fetched from order history (via _fetch_real_entry)
    so that stop/target levels are computed from the *actual* fill, not the
    current avg_entry_price (which can be skewed by partial closes).
    """
    # 1. Restore persisted positions first — these have our original risk plan.
    _load_positions()

    if not TRADING_CLIENT:
        return 0
    added = 0
    try:
        all_positions = TRADING_CLIENT.get_all_positions()
        # Detect options by asset_class OR by OCC symbol pattern (17-char alphanum with C/P)
        # Alpaca sometimes returns asset_class as "us_option", "us_equity", or None for options
        def _is_option(p) -> bool:
            ac = str(getattr(p, "asset_class", "") or "").lower()
            if "option" in ac:
                return True
            sym = str(p.symbol or "")
            return bool(re.match(r'^[A-Z]{1,6}\d{6}[CP]\d{8}$', sym))
        option_positions = [p for p in all_positions if _is_option(p)]
        log.info(f"reconcile_positions: {len(all_positions)} total Alpaca positions, "
                 f"{len(option_positions)} option(s): {[str(p.symbol) for p in option_positions]}")

        with _positions_lock:
            known_occs = {p["occ_symbol"] for p in _open_positions}

        for ap in option_positions:
            occ = str(ap.symbol)
            if occ in known_occs:
                continue
            qty   = int(float(ap.qty or 0))
            fallback_price = float(ap.avg_entry_price or ap.cost_basis or 0)
            if qty <= 0 or fallback_price <= 0:
                continue
            # Real entry from order history — falls back to avg_entry_price on lookup failure.
            real_entry = _fetch_real_entry(occ, fallback_price)
            # Best-guess direction from OCC symbol: find C or P before the 8-digit strike
            _m = re.search(r'([CP])\d{8}$', occ)
            direction = "bull" if (_m and _m.group(1) == "C") else "bear"
            underlying = re.match(r'^([A-Z]+)', occ).group(1) if re.match(r'^([A-Z]+)', occ) else occ[:6].rstrip()
            # Orphaned Alpaca positions are by definition real (they exist at the broker).
            register_trade(occ, real_entry, qty, direction, underlying,
                           order_id=None, is_dry_run=False, signal_class="reconciled")
            entry_note = (
                f"@ ${real_entry:.2f}" if real_entry == fallback_price
                else f"@ ${real_entry:.2f} (avg shown ${fallback_price:.2f})"
            )
            log.warning(
                f"reconcile_positions: added orphaned position {occ} "
                f"{qty}x {entry_note} (direction={direction}) — "
                f"likely from a previous session."
            )
            added += 1

        if added:
            log.warning(f"reconcile_positions: {added} orphaned position(s) recovered.")

        # ── Two-way sync: remove local positions Alpaca no longer holds ──────
        alpaca_occs = {str(ap.symbol) for ap in option_positions}
        with _positions_lock:
            stale = [
                p for p in _open_positions
                if p["occ_symbol"] not in alpaca_occs and not p.get("is_dry_run")
            ]
            for p in stale:
                _open_positions.remove(p)
                log.warning(
                    f"reconcile_positions: removed stale local position "
                    f"{p['occ_symbol']} — not found in Alpaca (closed externally or expired)"
                )
            if stale:
                _save_positions()

        if not added and not stale:
            log.info("reconcile_positions: local positions match Alpaca.")
    except Exception as e:
        log.warning(f"reconcile_positions failed: {e}")
    return added


def deployed_risk_pct(acct_val: float) -> float:
    """Fraction of account currently at risk across all open positions.
    Each position's risk = entry_price * remaining_contracts * 100 (full premium)."""
    if acct_val <= 0:
        return 0.0
    with _positions_lock:
        total_at_risk = sum(
            p["entry_price"] * p["remaining"] * 100
            for p in _open_positions
            if p["remaining"] > 0
        )
    return total_at_risk / acct_val


# Correlation-adjusted portfolio delta cap. With 6 high-beta tech names + SPY
# in the watchlist, six 0.5% directional bets in the same direction = effectively
# one 3% market bet. This cap measures the actual signed delta exposure.
MAX_NET_PORTFOLIO_DELTA_PCT = 0.05   # |net signed delta-$| / equity must stay ≤ 5%


def net_portfolio_delta_dollars() -> float:
    """Sum of signed delta-dollars across all open positions.

    Signed: long calls = +delta×spot×100×qty, long puts = -|delta|×spot×100×qty.
    Spot is fetched from the position's underlying; if unavailable, the position
    contributes 0 (conservative — won't trip the gate spuriously).
    """
    total = 0.0
    with _positions_lock:
        positions = [dict(p) for p in _open_positions if p.get("remaining", 0) > 0]
    for pos in positions:
        try:
            occ = pos.get("occ_symbol", "")
            # OCC: SYM + YYMMDD + C|P + 8-digit strike (in 1/1000 of $)
            m = re.match(r"^([A-Z]+)(\d{6})([CP])(\d{8})$", occ)
            if not m:
                continue
            sym, ymd, cp, strike_str = m.group(1), m.group(2), m.group(3), m.group(4)
            strike = int(strike_str) / 1000.0
            # get_symbol_price returns (price, chg_pct, session) — must unpack.
            # The old `spot = get_symbol_price(sym) or 0.0` set spot to the
            # whole tuple → `spot <= 0` raised TypeError → caught by the bare
            # except → EVERY position contributed 0 → net delta always 0.0 →
            # this entire correlation cap was silently dead. Fixed 2026-05-15.
            _px = get_symbol_price(sym)
            spot = float(_px[0]) if (_px and _px[0]) else 0.0
            if spot <= 0:
                continue
            exp_date = datetime.strptime(ymd, "%y%m%d").date()
            tte_days = max(1, (exp_date - datetime.now(ET).date()).days)
            # bs_delta signature is (spot, strike, tte_days, iv, option_type).
            # The old call `bs_delta(..., is_call=...)` raised TypeError (no
            # such kwarg + missing required `iv`) → caught by the bare except
            # → 0. Second silent bug stacked on the tuple bug. Fixed
            # 2026-05-15. IV: a coarse 0.30 proxy is fine here — this is a
            # risk *cap*, not a pricing engine; we need approximate signed
            # delta, not exact. (Could refine to per-symbol IV later.)
            d = bs_delta(spot, strike, tte_days, 0.30,
                         option_type=("call" if cp == "C" else "put"))
            # bs_delta returns + for calls, − for puts; normalize by direction
            d = abs(d) if cp == "C" else -abs(d)
            total += d * spot * 100 * pos["remaining"]
        except Exception:
            continue
    return total


def portfolio_delta_check(acct_val: float, intended_direction: str = "bull") -> bool:
    """Return False if adding a same-direction position would push |net delta|
    above MAX_NET_PORTFOLIO_DELTA_PCT × equity.

    Only blocks adds in the *same* direction as the current net exposure —
    hedging trades (opposite-direction) can always go through (they reduce risk).
    """
    if acct_val <= 0:
        return True
    net_d = net_portfolio_delta_dollars()
    cap = acct_val * MAX_NET_PORTFOLIO_DELTA_PCT
    # Check whether the intended trade is in the same direction as current net
    intended_sign = 1 if intended_direction == "bull" else -1
    current_sign = 1 if net_d >= 0 else -1
    if intended_sign != current_sign and abs(net_d) > 0:
        return True  # hedging — allowed
    if abs(net_d) >= cap:
        log.warning(
            f"  🧭 Net portfolio delta cap: |${net_d:,.0f}| ≥ ${cap:,.0f} "
            f"({MAX_NET_PORTFOLIO_DELTA_PCT*100:.1f}% of equity). "
            f"Skipping same-direction add."
        )
        return False
    return True


def _close_option_position(occ_symbol: str, qty: int, reason: str,
                           client_order_id: Optional[str] = None) -> bool:
    """Limit-sell at the current bid to close an option position quickly.

    Uses DAY time-in-force because Alpaca rejects IOC for options orders
    (error 42210000). client_order_id makes the submission idempotent —
    if Alpaca already saw this ID it returns the existing order instead of
    creating a duplicate sell. Caller should pass the same ID on retries
    (stored on the position dict).
    """
    if not OPTION_CLIENT or not TRADING_CLIENT:
        return False
    try:
        req   = OptionLatestQuoteRequest(symbol_or_symbols=[occ_symbol])
        res   = OPTION_CLIENT.get_option_latest_quote(req)
        # Stamp freshness so the UI's option_quote panel doesn't go red just
        # because no entry attempts have happened for this underlying recently.
        _m = re.match(r"^([A-Z]+)\d", occ_symbol)
        if _m:
            stamp_freshness(f"option_quote:{_m.group(1)}", source_tag="alpaca")
        quote = res.get(occ_symbol)
        bid   = float((quote.bid_price or 0)) if quote else 0.0
        ask   = float((quote.ask_price or 0)) if quote else 0.0
        if bid <= 0 and ask <= 0:
            log.warning(f"_close_option_position({occ_symbol}): bid=0 ask=0 — no market, skipping order")
            return False
        # Sell at bid to prioritise execution; fall back to mid if bid=0
        limit = round(max(bid, 0.01), 2) if bid > 0 else round(max((bid + ask) / 2, 0.01), 2)
        # Use close_position for full qty; fall back to limit sell for partials.
        # close_position avoids "uncovered option" rejection because Alpaca knows
        # it's closing an existing long, not opening a short.
        try:
            all_pos = TRADING_CLIENT.get_all_positions()
            held_qty = next(
                (int(float(p.qty)) for p in all_pos if str(p.symbol) == occ_symbol), 0
            )
        except Exception:
            held_qty = qty  # fallback: assume we hold what we're trying to close

        if qty >= held_qty:
            # Full close — use the dedicated endpoint
            order = TRADING_CLIENT.close_position(occ_symbol)
            log.info(f"CLOSE [{reason}]: {qty}x {occ_symbol} (full)  id={order.id}")
        else:
            # Partial close — sell limit with explicit qty
            order_kwargs = dict(
                symbol        = occ_symbol,
                qty           = qty,
                side          = OrderSide.SELL,
                type          = OrderType.LIMIT,
                time_in_force = TimeInForce.DAY,
                limit_price   = limit,
            )
            if client_order_id:
                order_kwargs["client_order_id"] = client_order_id
            order = TRADING_CLIENT.submit_order(LimitOrderRequest(**order_kwargs))
            log.info(f"CLOSE PARTIAL [{reason}]: {qty}x {occ_symbol} @ ${limit:.2f}  id={order.id}")
        return True
    except Exception as e:
        log.error(f"_close_option_position({occ_symbol}): {e}")
        return False


def _close_spread_short_leg(pos: dict) -> None:
    """BTC the short leg of a debit spread when the long leg is closed.

    Called alongside every _close_option_position() for spread positions.
    No-op for naked positions or dry-runs.
    """
    short_occ = pos.get("short_occ")
    if not short_occ or pos.get("is_dry_run"):
        return
    try:
        TRADING_CLIENT.close_position(short_occ)
        log.info(f"BTC spread short leg: {short_occ}")
    except Exception as e:
        log.warning(f"BTC short leg {short_occ} failed: {e}")


def _remove_position(pos: dict) -> None:
    # Record a PDT day-trade if this position opened AND fully closed on the
    # same trading day. Real positions only — dry-runs aren't real day-trades.
    if not pos.get("is_dry_run", False):
        _record_day_trade(pos.get("occ_symbol", "?"), pos.get("opened_at", ""))
    with _positions_lock:
        try:
            _open_positions.remove(pos)
        except ValueError:
            pass
    _save_positions()


# ── Kill switch ───────────────────────────────────────────────────────────────
_EMERGENCY_HALT = False   # When True: block all new entries indefinitely.


def emergency_halt_active() -> bool:
    return _EMERGENCY_HALT


def flatten_all_positions(reason: str = "user kill switch") -> dict:
    """Close every open position at the ask (worst case but immediate fill) and
    block new entries via the emergency halt flag.

    Returns a summary dict with counts attempted/succeeded/failed.
    """
    global _EMERGENCY_HALT
    _EMERGENCY_HALT = True
    log.warning(f"🛑 EMERGENCY FLATTEN-ALL: {reason}")

    summary = {"attempted": 0, "succeeded": 0, "failed": 0, "dry_run": 0}
    with _positions_lock:
        targets = [dict(p) for p in _open_positions if p.get("remaining", 0) > 0]

    for pos in targets:
        summary["attempted"] += 1
        qty = pos["remaining"]
        occ = pos["occ_symbol"]
        # Dry-run positions close locally — no broker call
        if pos.get("is_dry_run", False):
            with _positions_lock:
                for p in _open_positions:
                    if p["occ_symbol"] == occ:
                        p["remaining"] = 0
                        _open_positions.remove(p)
                        break
            log.info(f"[DRY RUN] Flattened {qty}x {occ}")
            summary["dry_run"] += 1
            summary["succeeded"] += 1
            continue
        cid = f"flatten_{occ}_{int(time.time())}"
        ok = _close_option_position(occ, qty, f"FLATTEN: {reason}", client_order_id=cid)
        if ok:
            _close_spread_short_leg(pos)
            with _positions_lock:
                for p in _open_positions:
                    if p["occ_symbol"] == occ:
                        p["remaining"] = 0
                        _open_positions.remove(p)
                        break
            summary["succeeded"] += 1
        else:
            summary["failed"] += 1
    _save_positions()
    log.warning(
        f"FLATTEN-ALL complete: {summary['succeeded']}/{summary['attempted']} closed "
        f"({summary['dry_run']} dry-run, {summary['failed']} failed). "
        f"Halt active — call clear_emergency_halt() to resume."
    )
    return summary


def clear_emergency_halt() -> None:
    global _EMERGENCY_HALT
    _EMERGENCY_HALT = False
    log.info("Emergency halt cleared — entries re-enabled.")


def check_positions() -> list[dict]:
    """Evaluate every open position and close at stop / target / hard-close.

    Called every POSITION_MONITOR_SEC (10s by default) by the position_monitor
    background task in app.py.
    Returns a list of close-event dicts for the UI log and trades_today.
    """
    if not _open_positions:
        return []

    now    = datetime.now(ET)
    hc     = now.replace(hour=POSITION_CLOSE_TIME[0], minute=POSITION_CLOSE_TIME[1],
                         second=0, microsecond=0)
    is_hc  = now >= hc
    events = []

    with _positions_lock:
        active = [p for p in _open_positions if p["remaining"] > 0]

    for pos in active:
        occ = pos["occ_symbol"]

        try:
            req   = OptionLatestQuoteRequest(symbol_or_symbols=[occ])
            res   = OPTION_CLIENT.get_option_latest_quote(req)
            stamp_freshness(f"option_quote:{pos.get('symbol', '?')}", source_tag="alpaca")
            quote = res.get(occ)
            if not quote:
                continue
            bid  = float(quote.bid_price or 0)
            ask  = float(quote.ask_price or 0)
            mid  = round((bid + ask) / 2, 2) if (bid > 0 and ask > 0) else 0.0
            if mid <= 0:
                log.warning(f"Monitor: zero mid for {occ} — skipping cycle")
                continue
        except Exception as e:
            log.warning(f"Monitor: quote error for {occ}: {e}")
            continue

        # Stop trigger uses BID (what we'd actually fill at), not mid (overly optimistic
        # when spread is wide). Targets stay on mid — we're selling into strength so the
        # mid is a fair representation of where the market is.
        stop_trigger = bid if bid > 0 else mid
        pnl_pct      = (mid - pos["entry_price"]) / pos["entry_price"] * 100
        pnl_frac     = mid / pos["entry_price"] - 1
        remaining    = pos["remaining"]
        log.info(
            f"  Monitor {occ}: bid=${bid:.2f} mid=${mid:.2f}  entry=${pos['entry_price']:.2f}  "
            f"P&L={pnl_pct:+.1f}%  remaining={remaining}"
        )

        # Reset stop-breach counter once bid recovers above stop_price — a brief
        # spread-induced dip below stop should not permanently arm the trigger.
        if stop_trigger > pos["stop_price"] and pos.get("stop_breach_count", 0) > 0:
            with _positions_lock:
                pos["stop_breach_count"] = 0

        # Breakeven move: once pnl_frac >= BREAKEVEN_TRIGGER_PCT, ratchet the stop
        # up to the entry price. Turns +30% winners into "free trades" — worst case
        # becomes a scratch instead of a -50% stop-out if the move reverses.
        if (not pos.get("breakeven_armed", False)
                and pnl_frac >= BREAKEVEN_TRIGGER_PCT
                and pos["stop_price"] < pos["entry_price"]):
            with _positions_lock:
                old_stop = pos["stop_price"]
                pos["stop_price"]      = pos["entry_price"]
                pos["breakeven_armed"] = True
                pos["stop_breach_count"] = 0  # reset — new stop level
            log.info(
                f"  ⚡ Breakeven armed for {occ}: pnl=+{pnl_frac*100:.0f}% — "
                f"stop moved ${old_stop:.2f} → ${pos['stop_price']:.2f} (entry)"
            )
            _save_positions()

        # Trailing stop after T1: once the partial has fired, track the highest
        # mid seen and trail the stop on the remainder at TRAIL_GIVE_BACK_PCT
        # below that peak. Lets winners run instead of riding back to entry.
        if pos.get("partial_done", False):
            peak = max(pos.get("peak_mid_after_t1", 0.0), mid)
            new_stop = round(peak * (1.0 - TRAIL_GIVE_BACK_PCT), 2)
            if TRAIL_MIN_STOP_AT_ENTRY:
                new_stop = max(new_stop, pos["entry_price"])
            with _positions_lock:
                pos["peak_mid_after_t1"] = peak
                if new_stop > pos["stop_price"]:
                    old_stop = pos["stop_price"]
                    pos["stop_price"] = new_stop
                    pos["stop_breach_count"] = 0
                    log.info(
                        f"  📈 Trail {occ}: peak=${peak:.2f}  stop ${old_stop:.2f} → ${new_stop:.2f}"
                    )
                    _save_positions()

        # Time-stop: exit stalled positions (pnl flat-ish) after TIME_STOP_MINS.
        # Range tightened to [-15%, +10%] — don't kill clear winners early; let
        # runners run to target. Range floor still -15% so near-stops resolve naturally.
        time_stop_triggered = False
        try:
            opened = datetime.fromisoformat(pos["opened_at"])
            age_min = (now - opened).total_seconds() / 60
            if age_min >= TIME_STOP_MINS and TIME_STOP_RANGE_LO <= pnl_frac <= TIME_STOP_RANGE_HI:
                time_stop_triggered = True
        except Exception:
            age_min = 0

        close_qty  = 0
        is_partial = False
        reason     = None

        if is_hc:
            with _positions_lock:
                if pos["close_attempted"]:
                    continue
                pos["close_attempted"] = True
            close_qty = remaining
            reason    = f"HARD CLOSE {POSITION_CLOSE_TIME[0]}:{POSITION_CLOSE_TIME[1]:02d} ET"
        elif stop_trigger <= pos["stop_price"]:
            # 2-cycle confirmation: a single wide-spread tick won't trigger.
            with _positions_lock:
                pos["stop_breach_count"] = pos.get("stop_breach_count", 0) + 1
                breach_count = pos["stop_breach_count"]
            if breach_count < STOP_CONFIRM_TICKS:
                log.info(
                    f"  Stop pending: bid=${stop_trigger:.2f} <= ${pos['stop_price']:.2f} "
                    f"(breach {breach_count}/{STOP_CONFIRM_TICKS}) — waiting for confirmation"
                )
                continue
            with _positions_lock:
                if pos["close_attempted"]:
                    continue
                pos["close_attempted"] = True
            close_qty = remaining
            reason    = f"STOP HIT bid=${stop_trigger:.2f} <= ${pos['stop_price']:.2f} ({pnl_pct:+.1f}%)"
            record_stop_hit(pos["symbol"], pos["direction"])
        elif time_stop_triggered:
            with _positions_lock:
                if pos["close_attempted"]:
                    continue
                pos["close_attempted"] = True
            close_qty = remaining
            reason    = f"TIME STOP {age_min:.0f}min @ {pnl_pct:+.1f}% (stalled)"
        elif mid >= pos["target_75"]:
            with _positions_lock:
                if pos["close_attempted"]:
                    continue
                pos["close_attempted"] = True
            close_qty = remaining
            reason    = f"TARGET 2 ${mid:.2f} >= ${pos['target_75']:.2f} ({pnl_pct:+.1f}%)"
        elif mid >= pos["target_50"]:
            # Atomic check-and-set inside the lock to prevent duplicate partial closes.
            # Close PARTIAL_QTY_FRAC of the original size (default 25%) — taking a
            # sliver off the table without amputating the right-tail upside.
            with _positions_lock:
                if pos["partial_done"]:
                    close_qty = 0  # another thread already triggered the partial
                else:
                    close_qty  = max(1, int(round(pos["contracts"] * PARTIAL_QTY_FRAC)))
                    close_qty  = min(close_qty, remaining)
                    is_partial = True
                    reason     = (f"TARGET 1 partial {int(PARTIAL_QTY_FRAC*100)}% "
                                  f"${mid:.2f} >= ${pos['target_50']:.2f} ({pnl_pct:+.1f}%)")
                    pos["partial_done"] = True  # claim it now — prevents race

        if close_qty <= 0:
            continue

        close_succeeded = False
        # Use the position's own dry-run flag (set at entry) — NOT the current
        # global DRY_RUN. A position entered as dry-run must always close as
        # dry-run, even if the global was toggled mid-session.
        if pos.get("is_dry_run", False):
            log.info(f"[DRY RUN] Would close {close_qty}x {occ}: {reason}")
            pos["remaining"] -= close_qty
            if pos["remaining"] <= 0:
                _remove_position(pos)
            close_succeeded = True
        else:
            # Reuse the same client_order_id across retries so Alpaca dedupes any
            # close that already landed (network timeout etc).
            with _positions_lock:
                if not pos.get("close_client_id"):
                    pos["close_client_id"] = f"close_{occ}_{int(time.time())}"
                cid = pos["close_client_id"]
            ok = _close_option_position(occ, close_qty, reason, client_order_id=cid)
            if ok:
                if pos["remaining"] - close_qty <= 0:
                    _close_spread_short_leg(pos)
                pos["remaining"] -= close_qty
                if pos["remaining"] <= 0:
                    _remove_position(pos)
                else:
                    # Partial close succeeded — clear ID so a *new* client_order_id
                    # is minted for the next close attempt on the remainder.
                    with _positions_lock:
                        pos["close_client_id"] = None
                close_succeeded = True
            else:
                # Order failed — roll back flags so the next monitor cycle can retry.
                # After 5 consecutive failures, accept that Alpaca can't close it and
                # check if Alpaca has already removed the position on their side.
                with _positions_lock:
                    fail_count = pos.get("close_fail_count", 0) + 1
                    pos["close_fail_count"] = fail_count
                    if fail_count >= 5:
                        log.warning(
                            f"  {occ}: {fail_count} consecutive close failures — "
                            f"checking Alpaca for position status"
                        )
                        # Check if Alpaca still holds it; if not, remove locally
                        try:
                            all_pos = TRADING_CLIENT.get_all_positions() if TRADING_CLIENT else []
                            still_held = any(str(p.symbol) == occ for p in all_pos)
                        except Exception:
                            still_held = True
                        if not still_held:
                            log.warning(f"  {occ}: not found in Alpaca — removing from local tracking")
                            _open_positions.remove(pos) if pos in _open_positions else None
                            _save_positions()
                        else:
                            pos["close_fail_count"] = 0  # reset and keep retrying
                            if is_partial:
                                pos["partial_done"] = False
                            else:
                                pos["close_attempted"] = False
                    else:
                        if is_partial:
                            pos["partial_done"] = False
                        else:
                            pos["close_attempted"] = False

        if close_succeeded:
            # Refresh UI account stats post-close (entry was already refreshed at fill).
            _notify_fill()
            # Persist after each close (covers partials where _remove_position
            # didn't fire). Full closes are already persisted by _remove_position.
            _save_positions()

        # Fees-adjusted P&L: subtract exchange/clearing fees on both entry + exit legs.
        # Per-contract %: fee_dollars / (entry_premium * 100) * 100  → 2*fee/entry per leg
        fees_pct = (2 * OPTION_FEE_PER_CONTRACT) / max(pos["entry_price"], 0.01)
        pnl_pct_net = round(pnl_pct - fees_pct, 2)

        events.append({
            "occ_symbol":  occ,
            "symbol":      pos["symbol"],
            "direction":   pos["direction"],
            "close_qty":   close_qty,
            "mid":         mid,
            "entry_price": pos["entry_price"],
            "pnl_pct":     round(pnl_pct, 1),
            "pnl_pct_net": pnl_pct_net,          # fees-adjusted
            "fees_pct":    round(fees_pct, 2),
            "reason":      reason,
            "is_partial":  is_partial,
            "order_id":    pos.get("order_id"),
            "opened_at":   pos.get("opened_at"),
            "slippage_bps": pos.get("entry_slippage_bps"),  # captured at entry, if real
            "signal_class": pos.get("signal_class", "unknown"),  # for per-strategy P&L attribution
        })

    return events


# ── Fill confirmation ─────────────────────────────────────────────────────────
def wait_for_fill(order_id: str, stop_event=None) -> int:
    """Poll order status until filled or FILL_TIMEOUT_MINS elapses.

    Returns the number of contracts actually filled (≥1 = success, 0 = failed).
    Handles partial fills: updates the registered position to the real fill qty.
    Cancels unfilled remainder automatically on timeout.
    """
    if not TRADING_CLIENT:
        return 0
    deadline = datetime.now(ET) + timedelta(minutes=FILL_TIMEOUT_MINS)
    while datetime.now(ET) < deadline:
        if stop_event and stop_event.is_set():
            break
        try:
            order  = TRADING_CLIENT.get_order_by_id(order_id)
            status = str(order.status).lower()
            if status == "filled":
                filled_qty = int(float(order.filled_qty or 0))
                log.info(f"Fill confirmed: order {order_id} filled_qty={filled_qty}")
                return filled_qty
            if status == "partially_filled":
                filled_qty = int(float(order.filled_qty or 0))
                log.warning(
                    f"Order {order_id} partially filled ({filled_qty} contracts) — "
                    f"cancelling remainder and adjusting position."
                )
                try:
                    TRADING_CLIENT.cancel_order_by_id(order_id)
                except Exception:
                    pass
                # Shrink the registered position to the actual filled qty
                if filled_qty > 0:
                    with _positions_lock:
                        for pos in _open_positions:
                            if pos.get("order_id") == order_id:
                                pos["contracts"] = filled_qty
                                pos["remaining"] = filled_qty
                                break
                return filled_qty
            if status in ("canceled", "expired", "replaced", "done_for_day"):
                log.warning(f"Order {order_id} ended without fill: status={status}")
                return 0
            log.info(f"  Waiting for fill: order {order_id} status={status}")
        except Exception as e:
            log.warning(f"wait_for_fill poll error: {e}")
        if stop_event:
            stop_event.wait(timeout=FILL_POLL_INTERVAL)
        else:
            time.sleep(FILL_POLL_INTERVAL)

    # Timeout — cancel the order
    log.warning(
        f"Order {order_id} not filled within {FILL_TIMEOUT_MINS} min — cancelling."
    )
    try:
        TRADING_CLIENT.cancel_order_by_id(order_id)
        log.info(f"Order {order_id} cancelled.")
    except Exception as e:
        log.warning(f"Could not cancel order {order_id}: {e}")
    return 0


# ── CLI entry (only used if run standalone, not via dashboard) ────────────────
def main():
    """Standalone CLI entry. The dashboard imports this module instead."""
    import os
    from getpass import getpass
    print("\n  SPY Auto Trader — Alpaca Edition\n")

    api_key    = os.environ.get("ALPACA_API_KEY")    or input("Alpaca API Key: ").strip()
    api_secret = os.environ.get("ALPACA_API_SECRET") or getpass("Alpaca API Secret: ").strip()
    paper_in   = (os.environ.get("ALPACA_PAPER", "yes") or input("Paper trading? (yes/no) [yes]: ")).strip().lower()
    paper      = paper_in != "no"

    account, ok, err = init_clients(api_key, api_secret, paper=paper)
    if not ok:
        print(f"Login failed: {err}")
        return
    print(f"Connected to Alpaca {'PAPER' if paper else 'LIVE'} — equity ${float(account.equity):,.2f}")

    # Run morning session immediately for testing
    prior = fetch_prior_day_levels()
    vix   = fetch_vix()
    if vix_check(vix):
        morning_session(prior, vix)


# ── End-of-day learning review ────────────────────────────────────────────────

_EOD_REVIEW_PATTERNS = {
    "signal":    r"SIGNAL \[(BULL|BEAR)\]",
    "order":     r"Order submitted",
    "dry_run":   r"\[DRY RUN\] User (ALLOWED|SKIPPED)",
    "iv_gate":   r"IV rank gate",
    "vol_gate":  r"vol_ratio.*below",
    "news_veto": r"News veto",
    "debate_ok": r"Debate.*PROCEED",
    "debate_no": r"Debate.*SUPPRESS",
    "stop":      r"STOP HIT",
    "target1":   r"TARGET 1 partial",
    "target2":   r"TARGET 2",
    "hard_close":r"HARD CLOSE",
}


def _parse_today_log(log_path: str) -> dict:
    """Scan today's lines from the log file and tally key events."""
    import re
    today = datetime.now(ET).strftime("%Y-%m-%d")
    counts = {k: 0 for k in _EOD_REVIEW_PATTERNS}
    try:
        with open(log_path, "r", errors="replace") as fh:
            for line in fh:
                if today not in line:
                    continue
                for key, pat in _EOD_REVIEW_PATTERNS.items():
                    if re.search(pat, line):
                        counts[key] += 1
    except FileNotFoundError:
        pass
    return counts


def generate_signal_narrative(details: dict, debate_summary: str = "") -> str:
    """Generate a 1-paragraph LLM rationale for a trade entry.

    Stored on the position dict under 'narrative'. Falls back to a plain
    rule-based sentence when ANTHROPIC_API_KEY is not set or LLM call fails.
    """
    sym   = details.get("symbol", "?")
    dir_  = details.get("direction", "?").upper()
    rsn   = details.get("reason", "")
    mid   = details.get("mid_price", 0)
    stop  = details.get("stop_price", 0)
    t1    = details.get("target_50", 0)
    t2    = details.get("target_75", 0)
    inds  = details.get("_indicators", {})

    def _key(k):
        return f"{inds.get(k, float('nan')):.2f}" if isinstance(inds.get(k), (int, float)) else "n/a"

    plain = (
        f"{sym} {dir_} | reason: {rsn} | entry ${mid:.2f} | "
        f"stop ${stop:.2f} | T1 ${t1:.2f} | T2 ${t2:.2f} | "
        f"RSI {_key('rsi')} | VWAP {_key('vwap')} | "
        f"EMA9 {_key('ema9')} | IVR {_key('iv_rank')} | "
        f"vol_ratio {_key('volume_ratio')}"
    )
    if debate_summary:
        plain += f" | debate: {debate_summary}"

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return (f"Entered {sym} {dir_} at ${mid:.2f} ({rsn}). "
                f"Stop ${stop:.2f} · T1 ${t1:.2f} · T2 ${t2:.2f}.")
    try:
        import anthropic
        import debate as _d; client = _d.get_anthropic_client()
        if client is None:
            raise RuntimeError('no anthropic client')
        prompt = (
            "You are a trading co-pilot trained on Natenberg, Passarelli, and Saliba. "
            "Write ONE sentence (max 45 words) explaining why this options trade was taken, "
            "referencing the specific edge (Greeks, IV, pattern), and what the key risk is. "
            "Be direct. No preamble.\n\n"
            f"Trade: {plain}"
        )
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=80,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text.strip()
    except Exception as e:
        log.warning(f"generate_signal_narrative LLM failed: {e}")
        return (f"Entered {sym} {dir_} at ${mid:.2f} ({rsn}). "
                f"Stop ${stop:.2f} · T1 ${t1:.2f} · T2 ${t2:.2f}.")


def eod_review(log_path: str, trades_today: list) -> str:
    """Parse today's log + closed trades and ask Claude Haiku for insights.

    Returns a formatted multi-line review string.
    Falls back to a plain-text summary when ANTHROPIC_API_KEY is not set.
    """
    counts = _parse_today_log(log_path)

    wins  = [t for t in trades_today if not t.get("is_partial") and t.get("pnl_pct", 0) > 0]
    loses = [t for t in trades_today if not t.get("is_partial") and t.get("pnl_pct", 0) < 0]
    flat  = [t for t in trades_today if not t.get("is_partial") and t.get("pnl_pct", 0) == 0]
    closed = wins + loses + flat
    avg_win  = round(sum(t["pnl_pct"] for t in wins)  / len(wins),  1) if wins  else 0
    avg_loss = round(sum(t["pnl_pct"] for t in loses) / len(loses), 1) if loses else 0

    # Pro metrics:
    # - Win rate: % of closed trades that profited
    # - Profit factor: |sum(wins) / sum(losses)| — >1.0 = profitable system
    # - Expectancy: average $ per trade if you repeated the day's setups
    # - R-multiple: P&L per trade as multiple of risk (using STOP_LOSS_PCT as 1R)
    # - Max consecutive losers: psychological + system-stress indicator
    n_closed   = len(closed)
    win_rate   = (len(wins) / n_closed * 100) if n_closed else 0.0
    gross_wins  = sum(t["pnl_pct"] for t in wins)
    gross_loss  = abs(sum(t["pnl_pct"] for t in loses))
    profit_factor = (gross_wins / gross_loss) if gross_loss > 0 else (float("inf") if gross_wins > 0 else 0.0)
    expectancy = ((win_rate / 100) * avg_win + (1 - win_rate / 100) * avg_loss) if n_closed else 0.0
    r_unit     = STOP_LOSS_PCT * 100  # 1R in %
    avg_r      = (sum(t["pnl_pct"] for t in closed) / n_closed / r_unit) if n_closed and r_unit else 0.0
    # Longest losing streak (chronological order — assumes trades_today is append-order)
    streak = max_streak = 0
    for t in trades_today:
        if t.get("is_partial"):
            continue
        if t.get("pnl_pct", 0) < 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0

    # Per-signal-class attribution (Cofnas §17c) — which strategies actually made money
    by_class: dict[str, list[float]] = {}
    for t in closed:
        cls = t.get("signal_class", "unknown")
        by_class.setdefault(cls, []).append(t.get("pnl_pct", 0))
    class_lines: list[str] = []
    for cls, pnls in sorted(by_class.items(), key=lambda kv: -sum(kv[1])):
        n = len(pnls)
        wins_n = sum(1 for p in pnls if p > 0)
        wr = (wins_n / n * 100) if n else 0
        total_pnl = sum(pnls)
        avg = total_pnl / n if n else 0
        class_lines.append(
            f"  {cls:15} n={n:2}  win={wr:4.0f}%  total={total_pnl:+6.1f}%  avg={avg:+5.1f}%"
        )

    # Per-symbol attribution (§P1-D) — which SYMBOLS make money (vs which
    # strategies). If vwap_momentum works on SPY but bleeds on NVDA, you
    # drop NVDA from the watchlist, not the strategy.
    by_sym: dict[str, list[float]] = {}
    for t in closed:
        by_sym.setdefault(t.get("symbol", "?"), []).append(t.get("pnl_pct", 0))
    sym_lines: list[str] = []
    for sym, pnls in sorted(by_sym.items(), key=lambda kv: -sum(kv[1])):
        n = len(pnls)
        wr = (sum(1 for p in pnls if p > 0) / n * 100) if n else 0
        tot = sum(pnls)
        sym_lines.append(
            f"  {sym:6} n={n:2}  win={wr:4.0f}%  total={tot:+6.1f}%  avg={tot/n if n else 0:+5.1f}%"
        )

    # 2-D cross-tab {symbol × signal_class} — surfaces e.g. "NVDA orb_breakout
    # = -8% over 4 trades" that both 1-D views hide.
    xtab: dict[tuple, list[float]] = {}
    for t in closed:
        xtab.setdefault((t.get("symbol", "?"), t.get("signal_class", "unknown")),
                        []).append(t.get("pnl_pct", 0))
    xtab_lines: list[str] = []
    for (sym, cls), pnls in sorted(xtab.items(), key=lambda kv: sum(kv[1])):
        if sum(pnls) < 0 and len(pnls) >= 2:   # only flag genuine losers
            xtab_lines.append(
                f"  ⚠ {sym} × {cls}: {sum(pnls):+.1f}% over {len(pnls)} trades — consider disabling"
            )

    pf_str = "∞" if profit_factor == float("inf") else f"{profit_factor:.2f}"

    # 3R-C.1 — split into MECHANICS scorecard (what the system DID) and
    # EDGE scorecard (did it make money). In paper mode, MECHANICS is the
    # valuable output; P&L just amplifies noise on an unvalidated edge.
    mechanics_lines = [
        "── MECHANICS SCORECARD (what the system did today) ──",
        f"  Signals fired:       {counts['signal']}",
        f"  Orders placed:       {counts['order']}  (dry-run skipped: {counts['dry_run']})",
        f"  IV rank gates:       {counts['iv_gate']}",
        f"  Vol gates:           {counts['vol_gate']}",
        f"  News vetoes:         {counts['news_veto']}",
        f"  Debate suppressed:   {counts['debate_no']}  |  Debate proceed: {counts['debate_ok']}",
        f"  Exits — stops: {counts['stop']}  T1-partial: {counts['target1']}  T2: {counts['target2']}  hard-close: {counts['hard_close']}",
        f"  Paper mode:          {'YES (P&L below is learning noise, not edge validation)' if PAPER_MODE else 'NO — real money'}",
    ]

    edge_lines = [
        "── EDGE SCORECARD (P&L — read carefully in paper mode) ──",
    ]
    if PAPER_MODE:
        edge_lines.append(
            "  ⚠ PAPER MODE: P&L below is informational only. "
            "Max-risk paper settings amplify noise. "
            "Do NOT read green paper days as edge validation."
        )
    edge_lines += [
        f"  Closed: {len(wins)}W / {len(loses)}L / {len(flat)} flat",
        f"  Win rate: {win_rate:.1f}%  |  PF: {pf_str}  |  Expectancy: {expectancy:+.2f}%/trade  |  Avg R: {avg_r:+.2f}R",
        f"  Max consecutive losses: {max_streak}",
    ]
    if class_lines:
        edge_lines.append("  Per-signal-class P&L (best → worst):")
        edge_lines.extend("  " + ln for ln in class_lines)
    if sym_lines:
        edge_lines.append("  Per-symbol P&L (best → worst):")
        edge_lines.extend("  " + ln for ln in sym_lines)
    if xtab_lines:
        edge_lines.append("  Losing symbol×strategy cells (≥2 trades):")
        edge_lines.extend("  " + ln for ln in xtab_lines)
    if trades_today:
        edge_lines.append("  Trade list:")
        for t in trades_today:
            if not t.get("is_partial"):
                edge_lines.append(
                    f"    {t.get('symbol','?')} {t.get('direction','?').upper()} "
                    f"{t.get('pnl_pct',0):+.1f}% — {t.get('reason','')}"
                )

    plain_summary = "\n".join(mechanics_lines + [""] + edge_lines)
    log.info(f"EOD summary:\n{plain_summary}")

    # Persist gate-fire stats for telemetry (3R-C.3)
    _record_gate_stats(counts, n_closed, win_rate, profit_factor, expectancy)

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return "── EOD Review (no API key — plain stats) ──\n" + plain_summary

    try:
        import debate as _d; client = _d.get_anthropic_client()
        if client is None:
            raise RuntimeError('no anthropic client')
        mode_note = ("NOTE: this is PAPER TRADING — P&L does NOT validate the edge. "
                     "Focus coaching on MECHANICS (gate behavior, execution, stops) "
                     "not on whether the day was 'profitable'.") if PAPER_MODE else ""
        prompt = (
            "You are a quantitative trading coach reviewing a day of automated options trading.\n"
            f"{mode_note}\n"
            "Given the stats below, provide:\n"
            "1. MECHANICS: did gates fire correctly? (2 bullets max)\n"
            "2. EDGE signal (paper only — treat as weak signal): what does P&L suggest? (1 bullet)\n"
            "3. One concrete improvement for tomorrow (name the constant and value)\n"
            "Be concise. No preamble.\n\n"
            f"Stats:\n{plain_summary}"
        )
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        insight = resp.content[0].text.strip()
        return "── EOD Review ──\n" + plain_summary + "\n\n── Insights ──\n" + insight
    except Exception as e:
        log.warning(f"eod_review: LLM call failed: {e}")
        return "── EOD Review (LLM unavailable) ──\n" + plain_summary


if __name__ == "__main__":
    main()
