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
Risk      : 0.5% account per trade, ATR-based stops, partial exits at +50%

Broker    : Alpaca (alpaca-py SDK)
Modes     : Paper trading (default) or Live trading

⚠️  DRY_RUN = True — set to False only when ready to trade real money.
"""

import os
import time
import threading
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import math

import pandas as pd
import numpy as np
import yfinance as yf

from alpaca.trading.client          import TradingClient
from alpaca.data.historical          import StockHistoricalDataClient
from alpaca.data.historical.option   import OptionHistoricalDataClient
from alpaca.data.requests            import (
    StockBarsRequest, StockLatestQuoteRequest, StockLatestTradeRequest,
    OptionLatestQuoteRequest,
)
from alpaca.data.timeframe           import TimeFrame, TimeFrameUnit
from alpaca.trading.requests         import (
    GetOptionContractsRequest, LimitOrderRequest,
)
from alpaca.trading.enums            import (
    OrderSide, TimeInForce, OrderType, ContractType, AssetStatus,
)


# ── Stop events & approval callback ───────────────────────────────────────────
# Legacy names kept for import compatibility; app.py now uses per-symbol events.
STOP_MORNING = threading.Event()
STOP_EVENING = threading.Event()
TRADE_CONFIRM_CALLBACK = None    # set by UI; signature: (details: dict) -> bool

# ── Alpaca clients (initialized via init_clients) ─────────────────────────────
TRADING_CLIENT = None
DATA_CLIENT    = None
OPTION_CLIENT  = None
PAPER_MODE     = True

# ── Trade memory (ChromaDB) ────────────────────────────────────────────────────
from trade_memory import TradeMemory
TRADE_MEMORY: TradeMemory = TradeMemory(enabled=False)  # enabled on login

# ── Bull/Bear debate ────────────────────────────────────────────────────────────
import debate as _debate_mod
DEBATE_ENABLED     = False   # enabled on login if ANTHROPIC_API_KEY present
DEBATE_MIN_CONFIDENCE = _debate_mod.DEBATE_MIN_CONFIDENCE


# ── Config ────────────────────────────────────────────────────────────────────
DRY_RUN         = True
MAX_RISK_PCT    = 0.005
STOP_LOSS_PCT   = 0.50
PROFIT_TARGET   = 0.75
MIN_VOL_RATIO   = 1.5
RSI_OVERBOUGHT  = 70
RSI_OVERSOLD    = 30
MAX_SPREAD      = 0.30
DTE_MIN         = 7
DTE_MAX         = 14
VIX_MAX         = 30
ATR_MULT_TREND  = 2.5
ATR_MULT_RANGE  = 1.5
MIN_ORB_WIDTH   = 0.002
PDT_REMAINING   = 3       # PDT does not apply to Alpaca margin accounts ≥$25K
ET              = ZoneInfo("America/New_York")

MORNING_START   = (9, 30)
MORNING_END     = (10, 0)
LUNCH_START     = (11, 30)
LUNCH_END       = (13, 30)
EVENING_START   = (15, 0)
EVENING_END     = (15, 30)
HARD_CLOSE           = (15, 0)
TIME_STOP_MINS       = 60
POSITION_CLOSE_TIME  = (15, 50)   # hard-close all open option positions at 3:50 ET
FILL_POLL_INTERVAL   = 15         # seconds between fill-status checks
FILL_TIMEOUT_MINS    = 3          # cancel unfilled order after this many minutes
MAX_PORTFOLIO_RISK   = 0.03       # 3% max total deployed risk across all symbols
MIN_OPTION_OI        = 100        # minimum open interest at the selected strike
MIN_OPTION_VOLUME    = 10         # minimum contracts traded today at the strike
IV_RANK_MAX          = 50         # skip buying options when IVR > 50% (premium too expensive)
IV_RANK_WARN         = 35         # log a caution when IVR is in the 35–50% zone
DELTA_TARGET_MIN     = 0.40       # prefer contracts with delta in [0.40, 0.65]
DELTA_TARGET_MAX     = 0.65       # outside this range we still trade but log a warning


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
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.FileHandler("spy_trader.log"), logging.StreamHandler()],
)
log = logging.getLogger(__name__)


# ── Client init ───────────────────────────────────────────────────────────────
def init_clients(api_key: str, api_secret: str, paper: bool = True):
    """
    Initialize Alpaca clients. Called by app.py after the user enters credentials.
    Returns (account, success_bool, error_msg_or_None).
    """
    global TRADING_CLIENT, DATA_CLIENT, OPTION_CLIENT, PAPER_MODE
    try:
        PAPER_MODE      = paper
        TRADING_CLIENT  = TradingClient(api_key, api_secret, paper=paper)
        DATA_CLIENT     = StockHistoricalDataClient(api_key, api_secret)
        OPTION_CLIENT   = OptionHistoricalDataClient(api_key, api_secret)
        # Verify by fetching account
        account = TRADING_CLIENT.get_account()
        return account, True, None
    except Exception as e:
        TRADING_CLIENT = DATA_CLIENT = OPTION_CLIENT = None
        return None, False, str(e)


def is_authenticated() -> bool:
    return TRADING_CLIENT is not None


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


# ── Market data ───────────────────────────────────────────────────────────────
def fetch_bars(symbol: str = "SPY", interval_min: int = 5):
    """Fetch intraday bars for `symbol` (today's session) with the indicator stack.

    Tries Alpaca feeds in order (iex → sip → default) then falls back to yfinance
    so sessions don't silently skip when IEX has no data for a symbol (e.g. SPY
    is NYSE Arca-listed, not IEX-listed).
    """
    symbol = symbol.upper()

    # Fetch from market open today through now
    now_et      = datetime.now(ET)
    market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    if now_et < market_open:
        market_open -= timedelta(days=1)

    sym_bars = []
    if DATA_CLIENT:
        tf    = TimeFrame(interval_min, TimeFrameUnit.Minute)
        start = market_open.astimezone(timezone.utc)
        for feed_attempt in ("iex", "sip", None):
            try:
                kwargs = dict(
                    symbol_or_symbols=[symbol],
                    timeframe=tf,
                    start=start,
                )
                if feed_attempt is not None:
                    kwargs["feed"] = feed_attempt
                bars = DATA_CLIENT.get_stock_bars(StockBarsRequest(**kwargs))
                sym_bars = bars[symbol] if symbol in bars else []
                if sym_bars:
                    break
                log.info(
                    f"fetch_bars({symbol}): feed={feed_attempt!r} returned 0 bars "
                    f"— trying next feed"
                )
            except Exception as e:
                log.info(
                    f"fetch_bars({symbol}): feed={feed_attempt!r} "
                    f"raised {type(e).__name__}: {e}"
                )

    # yfinance fallback
    if not sym_bars:
        log.info(f"fetch_bars({symbol}): Alpaca returned 0 bars — falling back to yfinance")
        try:
            ticker = yf.Ticker(symbol)
            yf_df  = ticker.history(period="1d", interval=f"{interval_min}m")
            if yf_df.empty:
                log.warning(f"fetch_bars({symbol}): yfinance also returned 0 bars")
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
            log.info(f"fetch_bars({symbol}): yfinance fallback — {len(yf_df)} bars")
            return _add_indicators(yf_df)
        except Exception as e:
            log.warning(f"fetch_bars({symbol}): yfinance fallback failed: {e}")
            return None

    rows = []
    for bar in sym_bars:
        rows.append({
            "begins_at":   bar.timestamp,
            "open_price":  float(bar.open),
            "high_price":  float(bar.high),
            "low_price":   float(bar.low),
            "close_price": float(bar.close),
            "volume":      float(bar.volume),
        })

    df = pd.DataFrame(rows)
    df["begins_at"] = pd.to_datetime(df["begins_at"], utc=True).dt.tz_convert(ET)
    df = df.sort_values("begins_at").reset_index(drop=True)
    return _add_indicators(df)


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


def _fetch_chart_bars_yfinance(symbol: str, tf_str: str, one_day_mode: bool) -> list:
    """Fallback chart data source using yfinance (free, no auth required)."""
    try:
        # Map timeframe to yfinance period + interval
        yf_config = {
            "1D": ("5d",  "5m"),    # 5-min bars for full extended-hours day
            "5D": ("10d", "15m"),
            "1M": ("1mo", "1h"),
            "3M": ("3mo", "1h"),
            "1Y": ("1y",  "1d"),
            "5Y": ("5y",  "1d"),
        }
        period, interval = yf_config.get(tf_str, yf_config["5D"])

        # 1D: include pre-market (4 AM) + after-hours (8 PM) so the full session
        # timeline is visible on the chart.
        use_prepost = one_day_mode
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval=interval, prepost=use_prepost)

        if df.empty:
            log.warning(f"yfinance fallback({symbol}, {tf_str}): returned empty DataFrame")
            return []

        # 1D mode: keep only the most recent date (pre+regular+after for that date)
        if one_day_mode:
            df.index = pd.to_datetime(df.index)
            if df.index.tz is None:
                df.index = df.index.tz_localize("UTC")
            df.index = df.index.tz_convert(ET)
            last_date = df.index.max().date()
            df = df[df.index.date == last_date]

        out = []
        for ts, row in df.iterrows():
            out.append({
                "time":   int(pd.Timestamp(ts).timestamp()),
                "open":   round(float(row["Open"]),   2),
                "high":   round(float(row["High"]),   2),
                "low":    round(float(row["Low"]),    2),
                "close":  round(float(row["Close"]),  2),
                "volume": int(row["Volume"]),
            })

        log.info(f"yfinance fallback({symbol}, {tf_str}): {len(out)} bars")
        return out
    except Exception as e:
        log.warning(f"yfinance fallback({symbol}, {tf_str}) failed: {e}")
        return []


def fetch_chart_bars(timeframe: str = "1D", symbol: str = "SPY"):
    """Fetch bars for any symbol. Supports 1D / 5D / 1M / 3M / 1Y / 5Y.

    1D returns 15-min bars for the **most recent trading session that has data**.
    During regular hours that's today; on weekends/holidays/pre-open it rolls back
    to the last day with bars (last Friday on a Sunday, the day before a holiday,
    etc.). Implemented by requesting a 10-day window and keeping only the most
    recent ET date present — one API call, no calendar lookup needed.

    Other timeframes use a rolling lookback. 5D requests 10 calendar days so the
    chart consistently shows ~5 trading days even after a weekend.
    """
    if not DATA_CLIENT:
        log.info(f"fetch_chart_bars({symbol}, {timeframe}): no DATA_CLIENT — login required")
        return []

    symbol = symbol.upper()
    tf_str = timeframe.upper()

    # Determine timeframe + start
    one_day_mode = (tf_str == "1D")
    if one_day_mode:
        tf = TimeFrame(15, TimeFrameUnit.Minute)
        # 10 calendar days back covers the longest typical US-market gap
        # (Christmas/New-Year combo can span 4–5 closed days).
        start = datetime.now(timezone.utc) - timedelta(days=10)
    else:
        config = {
            "5D": (TimeFrame(15, TimeFrameUnit.Minute), timedelta(days=10)),
            "1M": (TimeFrame(1,  TimeFrameUnit.Hour),   timedelta(days=30)),
            "3M": (TimeFrame(4,  TimeFrameUnit.Hour),   timedelta(days=90)),
            "1Y": (TimeFrame.Day,                       timedelta(days=365)),
            "5Y": (TimeFrame.Day,                       timedelta(days=365 * 5)),
        }
        tf, lookback = config.get(tf_str, config["5D"])
        start = datetime.now(timezone.utc) - lookback

    sym_bars = []
    used_feed = None
    last_error = None

    # Try IEX first (free tier), then SIP as fallback (paid). Then try
    # WITHOUT a feed parameter (lets the SDK pick a default the account has).
    # Many free-tier "0 bars" issues are silent feed-mismatch problems.
    for feed_attempt in ("iex", "sip", None):
        try:
            kwargs = dict(
                symbol_or_symbols=[symbol],
                timeframe=tf,
                start=start,
            )
            if feed_attempt is not None:
                kwargs["feed"] = feed_attempt
            request = StockBarsRequest(**kwargs)
            bars = DATA_CLIENT.get_stock_bars(request)
            sym_bars = bars[symbol] if symbol in bars else []
            if sym_bars:
                used_feed = feed_attempt or "default"
                break
            else:
                log.info(
                    f"fetch_chart_bars({symbol}, {timeframe}): feed={feed_attempt!r} "
                    f"returned 0 bars from start={start.isoformat()} — trying next feed"
                )
        except Exception as e:
            last_error = e
            log.info(
                f"fetch_chart_bars({symbol}, {timeframe}): feed={feed_attempt!r} "
                f"raised {type(e).__name__}: {e}"
            )
            continue

    try:
        if not sym_bars:
            log.info(
                f"fetch_chart_bars({symbol}, {timeframe}): Alpaca returned 0 bars — "
                f"falling back to yfinance"
            )
            return _fetch_chart_bars_yfinance(symbol, tf_str, one_day_mode)

        # 1D mode: keep only the most recent ET date that has bars.
        # This naturally handles weekends, holidays, half-days, and pre-open
        # without any calendar dependency.
        if one_day_mode and sym_bars:
            last_et_date = max(b.timestamp.astimezone(ET).date() for b in sym_bars)
            sym_bars = [b for b in sym_bars
                        if b.timestamp.astimezone(ET).date() == last_et_date]
            log.info(
                f"fetch_chart_bars({symbol}, 1D): feed={used_feed} → "
                f"showing session for {last_et_date.isoformat()} ({len(sym_bars)} bars)"
            )

        out = []
        for b in sym_bars:
            out.append({
                "time":   int(b.timestamp.timestamp()),
                "open":   round(float(b.open),   2),
                "high":   round(float(b.high),   2),
                "low":    round(float(b.low),    2),
                "close":  round(float(b.close),  2),
                "volume": int(b.volume),
            })
        if not out:
            log.info(
                f"fetch_chart_bars({symbol}, {timeframe}): 0 bars in last "
                f"{(datetime.now(timezone.utc) - start).days} days "
                f"(symbol may have no IEX activity)"
            )
        else:
            log.debug(f"fetch_chart_bars({symbol}, {timeframe}): {len(out)} bars")
        return out
    except Exception as e:
        log.warning(f"Could not fetch chart bars {symbol} ({timeframe}): {e}")
        return []


def fetch_prior_day_levels(symbol: str = "SPY"):
    """Daily bars for prior trading day. Returns dict with H/L/C and pivot levels."""
    if not DATA_CLIENT:
        return {}
    symbol = symbol.upper()
    try:
        now_et = datetime.now(ET)
        request = StockBarsRequest(
            symbol_or_symbols = [symbol],
            timeframe         = TimeFrame.Day,
            start             = (now_et - timedelta(days=10)).astimezone(timezone.utc),
            feed              = "iex",
        )
        bars = DATA_CLIENT.get_stock_bars(request)
        sym_bars = bars[symbol] if symbol in bars else []
        if len(sym_bars) < 2:
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
            f"  {symbol} key levels — PrevH={ph:.2f}  PrevL={pl:.2f}  PrevC={pc:.2f}  "
            f"Pivot={pp:.2f}  R1={levels['r1']:.2f}  S1={levels['s1']:.2f}"
        )
        return levels
    except Exception as e:
        log.warning(f"Could not fetch prior day levels for {symbol}: {e}")
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
        if calendar is None or calendar.empty:
            return False, ""
        # calendar index contains "Earnings Date" row
        if "Earnings Date" not in calendar.index:
            return False, ""
        earnings_dates = calendar.loc["Earnings Date"]
        today = datetime.now(ET).date()
        for ed in (earnings_dates if hasattr(earnings_dates, "__iter__") else [earnings_dates]):
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


def fetch_vix():
    """Fetch VIX via yfinance (Alpaca's free IEX feed doesn't support index symbols)."""
    try:
        ticker = yf.Ticker("^VIX")
        hist = ticker.history(period="1d", interval="1m", prepost=False)
        if not hist.empty:
            return round(float(hist["Close"].iloc[-1]), 2)
    except Exception as e:
        log.warning(f"fetch_vix yfinance failed: {e}")
    log.warning("Could not fetch VIX — proceeding without VIX filter")
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


def fetch_daily_ema200(symbol: str) -> float | None:
    """Compute EMA200 from the last 300 daily closes.

    Intraday 5-min bars only accumulate ~78 bars/day, so the rolling EMA200
    needs 13+ trading days to have any data and is distorted noise until then.
    A single daily EMA200 value is far more meaningful as a macro trend filter.
    Returns None if insufficient history is available.
    """
    try:
        ticker = yf.Ticker(symbol.upper())
        df = ticker.history(period="400d", interval="1d")
        if len(df) < 201:
            log.warning(f"fetch_daily_ema200({symbol}): only {len(df)} daily bars — need 201+")
            return None
        ema200 = float(df["Close"].ewm(span=200, adjust=False).mean().iloc[-1])
        log.info(f"  Daily EMA200 ({symbol}): ${ema200:.2f}")
        return round(ema200, 2)
    except Exception as e:
        log.warning(f"fetch_daily_ema200({symbol}): {e}")
        return None


def inject_daily_ema200(df: pd.DataFrame, ema200_val: float | None) -> pd.DataFrame:
    """Broadcast the daily EMA200 scalar into every row of the intraday df."""
    if ema200_val is not None:
        df = df.copy()
        df["ema200"] = ema200_val
    return df


def fetch_iv_rank(symbol: str) -> tuple[float | None, float | None]:
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


def get_symbol_price(symbol: str = "SPY"):
    """Latest trade price for any symbol + day change %.

    Latest trade: fetched live every call (fast single-item endpoint).
    Prev close  : cached per trading day — refreshed once at market open.
    """
    if not DATA_CLIENT:
        return None, None
    symbol = symbol.upper()
    try:
        trade_req  = StockLatestTradeRequest(symbol_or_symbols=[symbol], feed="iex")
        trade_data = DATA_CLIENT.get_stock_latest_trade(trade_req)
        if symbol not in trade_data:
            return None, None
        price = float(trade_data[symbol].price)

        # Use cached prev_close if we already have today's value
        today  = datetime.now(ET).date()
        cached = _prev_close_cache.get(symbol)
        if cached and cached[1] == today:
            prev_close = cached[0]
        else:
            request = StockBarsRequest(
                symbol_or_symbols = [symbol],
                timeframe         = TimeFrame.Day,
                start             = (datetime.now(timezone.utc) - timedelta(days=5)),
                feed              = "iex",
            )
            bars     = DATA_CLIENT.get_stock_bars(request)
            sym_bars = bars[symbol]
            prev_close = float(sym_bars[-2].close) if len(sym_bars) >= 2 else price
            _prev_close_cache[symbol] = (prev_close, today)

        chg_pct = round((price - prev_close) / prev_close * 100, 2) if prev_close else 0
        return round(price, 2), chg_pct
    except Exception as e:
        log.warning(f"Could not fetch {symbol} price: {e}")
    return None, None


# Backward-compatible alias
def get_spy_price():
    return get_symbol_price("SPY")


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


def find_atm_option(direction, expiry_str, current_price, symbol: str = "SPY"):
    """Find ATM call (bull) or put (bear) for `symbol` at given expiry."""
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

        # Filter by open interest and today's volume — low OI means illiquid exit.
        liquid = []
        for c in contracts:
            oi  = int(c.open_interest  or 0)
            vol = int(c.close_price    or 0)  # Alpaca uses close_price for daily volume in contract object
            # open_interest is the reliable field; volume_today may not be populated
            if oi >= MIN_OPTION_OI:
                liquid.append(c)
            else:
                log.info(
                    f"  Skipping {c.symbol} strike=${c.strike_price} "
                    f"OI={oi} (min {MIN_OPTION_OI}) — too illiquid"
                )

        if not liquid:
            # Fall back to full list with a warning so we don't block trading on
            # symbols that simply have low OI reported (data can lag by a day)
            log.warning(
                f"find_atm_option({symbol}): no contracts pass OI≥{MIN_OPTION_OI} — "
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

        def _score(c):
            strike = float(c.strike_price)
            # Use a rough IV estimate (25% annualised) when live IV unavailable
            delta = bs_delta(current_price, strike, tte_days, iv=0.25, option_type=opt_type_str)
            return abs(abs(delta) - 0.50)   # 0 = perfect ATM delta

        contracts_sorted = sorted(liquid, key=_score)
        c = contracts_sorted[0]
        oi_val = int(c.open_interest or 0)

        # Log the chosen delta for transparency
        chosen_delta = bs_delta(
            current_price, float(c.strike_price), tte_days,
            iv=0.25, option_type=opt_type_str
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


def option_mid_and_spread(option):
    """Return (mid, spread) for an option using its OCC symbol."""
    if not OPTION_CLIENT:
        return 0.0, 999.0
    try:
        request = OptionLatestQuoteRequest(symbol_or_symbols=[option["symbol"]])
        result  = OPTION_CLIENT.get_option_latest_quote(request)
        quote   = result.get(option["symbol"])
        if quote:
            bid    = float(quote.bid_price or 0)
            ask    = float(quote.ask_price or 0)
            spread = round(ask - bid, 2)
            mid    = round((bid + ask) / 2, 2) if (bid > 0 and ask > 0) else 0
            return mid, spread
    except Exception as e:
        log.warning(f"Could not fetch option quote: {e}")
    return 0.0, 999.0


def size_contracts(acct_val, mid_price):
    if mid_price <= 0:
        return 0
    max_risk          = acct_val * MAX_RISK_PCT
    cost_per_contract = mid_price * 100
    n = int(max_risk / cost_per_contract)
    if n == 0:
        log.warning(
            f"size_contracts: option costs ${cost_per_contract:.0f} but risk budget is "
            f"${max_risk:.0f} — skipping (would exceed {MAX_RISK_PCT*100:.1f}% risk rule)"
        )
    return n


# ── Filters ───────────────────────────────────────────────────────────────────
def is_lunch_hour():
    now = datetime.now(ET)
    s   = now.replace(hour=LUNCH_START[0], minute=LUNCH_START[1], second=0)
    e   = now.replace(hour=LUNCH_END[0],   minute=LUNCH_END[1],   second=0)
    return s <= now < e


def pdt_check():
    if PDT_REMAINING <= 0:
        log.warning("PDT limit reached. No new day trades.")
        return False
    log.info(f"PDT day trades remaining: {PDT_REMAINING}")
    return True


def vix_check(vix):
    if vix is None:
        return True
    if vix > VIX_MAX:
        log.warning(f"VIX={vix:.1f} > {VIX_MAX} — too volatile. Skipping session.")
        return False
    regime = "Calm" if vix < 14 else "Normal" if vix < 20 else "Elevated" if vix < 28 else "High"
    log.info(f"VIX={vix:.1f} [{regime}]")
    return True


# ── Trade execution ───────────────────────────────────────────────────────────
def place_trade(option, contracts, mid_price, direction, reason, atr=None, symbol: str = "SPY", indicators: dict = None):
    symbol     = symbol.upper()
    opt_type   = option.get("type", "?")
    strike     = option.get("strike_price", "?")
    expiry     = option.get("expiration_date", "?")
    occ_symbol = option.get("symbol", "?")
    limit      = round(mid_price + 0.02, 2)
    stop_opt   = round(mid_price * (1 - STOP_LOSS_PCT), 2)
    target_50  = round(mid_price * 1.50, 2)
    target_75  = round(mid_price * (1 + PROFIT_TARGET), 2)
    max_loss   = round(mid_price * 100 * contracts, 2)

    atr_stop_und = None
    if atr:
        atr_stop_und = round(mid_price - (atr * ATR_MULT_TREND), 2) if direction == "bull" \
                       else round(mid_price + (atr * ATR_MULT_TREND), 2)

    log.info("─" * 60)
    log.info(f"SIGNAL [{direction.upper()}]  {reason}")
    log.info(f"  Option   : {symbol} {expiry} ${strike} {opt_type.upper()} ({occ_symbol})")
    log.info(f"  Size     : {contracts} contract(s)  entry ${mid_price:.2f}  limit ${limit:.2f}")
    log.info(f"  Max loss : ${max_loss:,.2f}")
    log.info(f"  Stop     : ${stop_opt:.2f}  (-{int(STOP_LOSS_PCT*100)}%)")
    log.info(f"  Target 1 : ${target_50:.2f}  (+50% → close 50%)")
    log.info(f"  Target 2 : ${target_75:.2f}  (+{int(PROFIT_TARGET*100)}% → trail rest)")
    if atr_stop_und:
        log.info(f"  ATR stop : ${atr_stop_und:.2f} (ATR={atr:.2f} × {ATR_MULT_TREND})")
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
            # Register simulated position so the monitor can test stop/target logic
            register_trade(occ_symbol, mid_price, contracts, direction, symbol, "DRY_RUN")
        return None

    if not approved:
        log.info("Trade skipped by user.")
        return None

    if not pdt_check():
        return None

    # Submit option order via Alpaca
    try:
        order_req = LimitOrderRequest(
            symbol         = occ_symbol,
            qty            = contracts,
            side           = OrderSide.BUY,
            type           = OrderType.LIMIT,
            time_in_force  = TimeInForce.DAY,
            limit_price    = limit,
        )
        order = TRADING_CLIENT.submit_order(order_req)
        log.info(f"Order submitted — ID: {order.id}  Status: {order.status}")
        TRADE_MEMORY.record(
            symbol=symbol, direction=direction,
            indicators=details.get("_indicators", {}),
            entry_price=mid_price, trade_id=str(order.id),
        )
        register_trade(occ_symbol, mid_price, contracts, direction, symbol, str(order.id))
        return order
    except Exception as e:
        log.error(f"Order failed: {e}")
        return None


# ── Setup evaluation (unchanged from previous version) ────────────────────────
def evaluate_orb(bar, prev_bar, or_high, or_low, df):
    current   = float(bar["close_price"])
    rsi       = float(bar["rsi"])       if not np.isnan(bar["rsi"])       else 50
    vol_ratio = float(bar["vol_ratio"]) if not np.isnan(bar["vol_ratio"]) else 1
    vwap      = float(bar["vwap"])
    ema9      = float(bar["ema9"])
    ema21     = float(bar["ema21"])
    ema200    = float(bar["ema200"])    if not np.isnan(bar["ema200"])    else current
    macd_hist = float(bar["macd_hist"]) if not np.isnan(bar["macd_hist"]) else 0

    if (current > or_high and vol_ratio >= MIN_VOL_RATIO and current > vwap
            and ema9 > ema21 and current > ema200 and 50 < rsi < RSI_OVERBOUGHT and macd_hist > 0):
        return "bull", (f"ORB bull: ${current:.2f} > OR high ${or_high:.2f} | "
                        f"vol {vol_ratio:.1f}x | above VWAP & EMA200 | RSI={rsi:.0f}")

    if (current < or_low and vol_ratio >= MIN_VOL_RATIO and current < vwap
            and ema9 < ema21 and current < ema200 and RSI_OVERSOLD < rsi < 50 and macd_hist < 0):
        return "bear", (f"ORB bear: ${current:.2f} < OR low ${or_low:.2f} | "
                        f"vol {vol_ratio:.1f}x | below VWAP & EMA200 | RSI={rsi:.0f}")

    return None, None


def evaluate_gap_fade(bar, gap_pct, gap_direction, df):
    current   = float(bar["close_price"])
    rsi       = float(bar["rsi"])       if not np.isnan(bar["rsi"])       else 50
    vwap      = float(bar["vwap"])
    macd_hist = float(bar["macd_hist"]) if not np.isnan(bar["macd_hist"]) else 0
    abs_gap   = abs(gap_pct)

    if not (0.20 <= abs_gap <= 2.50):
        return None, None

    if gap_direction == "up" and current < vwap and rsi < 55 and macd_hist < 0:
        return "bear", (f"Gap fade: gapped up {gap_pct:+.2f}% but rolling over | "
                        f"below VWAP | RSI={rsi:.0f}")

    if gap_direction == "down" and current > vwap and rsi > 45 and macd_hist > 0:
        return "bull", (f"Gap fade: gapped down {gap_pct:+.2f}% but recovering | "
                        f"above VWAP | RSI={rsi:.0f}")

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
    above_vwap_pct = float((df["close_price"] > df["vwap"]).mean())

    if (current > vwap and above_vwap_pct > 0.50 and ema9 > ema21
            and 50 < rsi < RSI_OVERBOUGHT and vol_ratio >= 1.2
            and macd_hist > 0 and closing_up):
        return "bull", (f"VWAP momentum: above VWAP {above_vwap_pct:.0%} of day | "
                        f"RSI={rsi:.0f} | MACD green | {vol_ratio:.1f}x vol")

    if (current < vwap and above_vwap_pct < 0.50 and ema9 < ema21
            and RSI_OVERSOLD < rsi < 50 and vol_ratio >= 1.2
            and macd_hist < 0 and not closing_up):
        return "bear", (f"VWAP momentum: below VWAP {above_vwap_pct:.0%} of day above | "
                        f"RSI={rsi:.0f} | MACD red | {vol_ratio:.1f}x vol")

    return None, None


# ── Session runner ────────────────────────────────────────────────────────────
def run_session(session_name, session_end_hour, session_end_min,
                evaluate_fn, prior_levels, gap_info=None, stop_event=None,
                symbol: str = "SPY", daily_ema200: float | None = None,
                iv_rank: float | None = None):
    symbol = symbol.upper()
    session_end = datetime.now(ET).replace(
        hour=session_end_hour, minute=session_end_min, second=0, microsecond=0
    )
    acct_val = account_value()
    traded   = False

    log.info(f"Account: ${acct_val:,.2f}  |  Max risk: ${acct_val * MAX_RISK_PCT:,.2f}  |  Trading: {symbol}")
    if prior_levels:
        log.info(
            f"Levels — Pivot={prior_levels.get('pivot')}  "
            f"R1={prior_levels.get('r1')}  S1={prior_levels.get('s1')}"
        )

    while datetime.now(ET) < session_end and not traded:
        if stop_event and stop_event.is_set():
            log.info(f"{session_name}: stopped by user.")
            break
        if is_lunch_hour():
            log.info("Lunch-hour block (11:30–13:30 ET). Waiting...")
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
            indicators_snapshot = bar.to_dict()
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

            expiry = target_expiry(symbol)
            if not expiry:
                log.warning(f"No {symbol} expiry in DTE range. Skipping.")
            else:
                option, strike = find_atm_option(direction, expiry, current, symbol)
                if option:
                    mid, spread = option_mid_and_spread(option)
                    log.info(f"  Found: ${strike} {expiry}  mid=${mid:.2f}  spread=${spread:.2f}")
                    if mid > 0 and spread <= MAX_SPREAD:
                        contracts = size_contracts(acct_val, mid)
                        if contracts > 0:
                            place_trade(option, contracts, mid, direction, reason, atr, symbol,
                                        indicators=indicators_snapshot)
                            traded = True
                    else:
                        log.warning(f"Spread ${spread:.2f} > max ${MAX_SPREAD:.2f}. Skipping.")
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

    or_width_pct = (or_high - or_low) / or_low
    log.info(f"Opening range: ${or_low:.2f}–${or_high:.2f} (width {or_width_pct:.2%})")

    if or_width_pct < MIN_ORB_WIDTH:
        log.info(f"OR width too tight — ORB skipped, trying gap fade.")
        def gap_only(bar, prev_bar, df):
            return evaluate_gap_fade(bar, gap_pct, gap_dir, df)
        run_session("Morning (gap fade)", eh, em, gap_only, prior_levels,
                    stop_event=stop_event, symbol=symbol, daily_ema200=daily_ema200,
                    iv_rank=iv_rank)
        return

    def morning_eval(bar, prev_bar, df):
        d, r = evaluate_orb(bar, prev_bar, or_high, or_low, df)
        if d: return d, r
        return evaluate_gap_fade(bar, gap_pct, gap_dir, df)

    run_session("Morning", eh, em, morning_eval, prior_levels,
                stop_event=stop_event, symbol=symbol, daily_ema200=daily_ema200,
                iv_rank=iv_rank)


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
                iv_rank=iv_rank)


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

    if not vix_check(vix):
        log.warning(f"VIX too high — {symbol} all-day session blocked.")
        return

    earnings_risky, earnings_msg = check_earnings_risk(symbol)
    if earnings_risky:
        log.warning(earnings_msg)

    futures_ctx    = fetch_futures_context()
    breadth_ctx    = fetch_market_breadth()

    acct_val = account_value()
    log.info(f"Account: ${acct_val:,.2f}  |  Max risk: ${acct_val * MAX_RISK_PCT:,.2f}  |  {symbol}")
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

    # IV Rank — computed once at session start from nearest-expiry ATM call.
    _current_iv, iv_rank = fetch_iv_rank(symbol)
    if iv_rank is not None:
        if iv_rank > IV_RANK_MAX:
            log.warning(
                f"  ⚠️  IVR={iv_rank:.0f}% — options EXPENSIVE. "
                f"Entries will be skipped until IV normalises below {IV_RANK_MAX}%."
            )
        elif iv_rank > IV_RANK_WARN:
            log.warning(f"  ⚠️  IVR={iv_rank:.0f}% — elevated. Proceeding with caution.")

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

    session_end   = datetime.now(ET).replace(
        hour=end_hour, minute=end_minute, second=0, microsecond=0
    )
    last_trade_ts = None  # 5-minute cool-down guard

    while datetime.now(ET) < session_end:
        if stop_event and stop_event.is_set():
            log.info(f"All-day session ({symbol}): stopped by user.")
            break

        now = datetime.now(ET)

        if is_lunch_hour():
            log.info("Lunch-hour block (11:30–13:30 ET). Waiting 5 min…")
            if stop_event:
                if stop_event.wait(timeout=300):
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

        df       = _apply_vol_baseline(df)
        df       = inject_daily_ema200(df, daily_ema200)
        bar      = df.iloc[-1]
        prev_bar = df.iloc[-2] if len(df) > 1 else bar
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

        # Phase-based evaluator selection
        is_opening_phase = (now.hour == 9) or (now.hour == 10 and now.minute < 30)
        direction = reason = None

        if is_opening_phase and or_high and or_low:
            or_width = (or_high - or_low) / or_low
            if or_width >= MIN_ORB_WIDTH:
                direction, reason = evaluate_orb(bar, prev_bar, or_high, or_low, df)

        if not direction and gap_pct and gap_dir:
            direction, reason = evaluate_gap_fade(bar, gap_pct, gap_dir, df)

        if not direction:
            direction, reason = evaluate_vwap_momentum(bar, prev_bar, df)

        if direction:
            # Cool-down: suppress re-entry within 5 minutes
            if last_trade_ts and (now - last_trade_ts).total_seconds() < 300:
                log.info("  Cool-down active (< 5 min since last entry). Waiting.")
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

            indicators_snapshot = bar.to_dict()
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

            expiry = target_expiry(symbol)
            if not expiry:
                log.warning(f"No {symbol} expiry in DTE range. Skipping.")
            else:
                option, strike = find_atm_option(direction, expiry, current, symbol)
                if option:
                    mid, spread = option_mid_and_spread(option)
                    log.info(f"  Found: ${strike} {expiry}  mid=${mid:.2f}  spread=${spread:.2f}")
                    if mid > 0 and spread <= MAX_SPREAD:
                        contracts = size_contracts(acct_val, mid)
                        if contracts > 0:
                            order = place_trade(
                                option, contracts, mid, direction, reason, atr, symbol,
                                indicators=indicators_snapshot,
                            )
                        last_trade_ts = now  # always update — prevents flood in DRY_RUN
                        if order and not DRY_RUN:
                            filled = wait_for_fill(str(order.id), stop_event=stop_event)
                            if filled:
                                acct_val = account_value()
                            else:
                                log.warning(
                                    f"Entry order {order.id} not filled — position NOT registered."
                                )
                                # Remove the speculatively registered position
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
                        log.warning(
                            f"  Spread ${spread:.2f} > max ${MAX_SPREAD:.2f} — skipping. "
                            f"Consider raising MAX_SPREAD for {symbol}."
                        )

        if stop_event:
            stop_event.wait(timeout=60)
        else:
            time.sleep(60)

    log.info(f"All-day session ({symbol}) complete.")


# ── Position registry ─────────────────────────────────────────────────────────
_open_positions: list[dict] = []
_positions_lock = threading.Lock()


def register_trade(occ_symbol: str, entry_price: float, contracts: int,
                   direction: str, symbol: str, order_id: str | None = None) -> None:
    """Register a new position for the monitor after an order is submitted."""
    stop_price = round(entry_price * (1 - STOP_LOSS_PCT), 2)
    tgt_50     = round(entry_price * 1.50, 2)
    tgt_75     = round(entry_price * (1 + PROFIT_TARGET), 2)
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
        "partial_done": False,
        "opened_at":    datetime.now(ET).isoformat(),
    }
    with _positions_lock:
        _open_positions.append(pos)
    log.info(
        f"Position registered: {occ_symbol} {contracts}x  "
        f"entry=${entry_price:.2f}  stop=${stop_price:.2f}  "
        f"T1=${tgt_50:.2f}  T2=${tgt_75:.2f}"
    )


def open_positions_snapshot() -> list[dict]:
    """Thread-safe copy of the open positions list for the UI."""
    with _positions_lock:
        return [dict(p) for p in _open_positions]


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


def _close_option_position(occ_symbol: str, qty: int, reason: str) -> bool:
    """Limit-sell at the current bid to close an option position quickly.
    Returns True if the order was submitted without error."""
    if not OPTION_CLIENT or not TRADING_CLIENT:
        return False
    try:
        req   = OptionLatestQuoteRequest(symbol_or_symbols=[occ_symbol])
        res   = OPTION_CLIENT.get_option_latest_quote(req)
        quote = res.get(occ_symbol)
        bid   = float((quote.bid_price or 0)) if quote else 0.0
        ask   = float((quote.ask_price or 0)) if quote else 0.0
        # Sell at bid to prioritise execution; floor at $0.01 so Alpaca doesn't reject
        limit = round(max(bid, 0.01), 2) if bid > 0 else round(max((bid + ask) / 2, 0.01), 2)
        order_req = LimitOrderRequest(
            symbol        = occ_symbol,
            qty           = qty,
            side          = OrderSide.SELL,
            type          = OrderType.LIMIT,
            time_in_force = TimeInForce.DAY,
            limit_price   = limit,
        )
        order = TRADING_CLIENT.submit_order(order_req)
        log.info(f"CLOSE [{reason}]: {qty}x {occ_symbol} @ ${limit:.2f}  id={order.id}")
        return True
    except Exception as e:
        log.error(f"_close_option_position({occ_symbol}): {e}")
        return False


def _remove_position(pos: dict) -> None:
    with _positions_lock:
        try:
            _open_positions.remove(pos)
        except ValueError:
            pass


def check_positions() -> list[dict]:
    """Evaluate every open position and close at stop / target / hard-close.

    Called every 30 s by the position_monitor background task in app.py.
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

        pnl_pct    = (mid - pos["entry_price"]) / pos["entry_price"] * 100
        remaining  = pos["remaining"]
        log.info(
            f"  Monitor {occ}: mid=${mid:.2f}  entry=${pos['entry_price']:.2f}  "
            f"P&L={pnl_pct:+.1f}%  remaining={remaining}"
        )

        close_qty  = 0
        is_partial = False
        reason     = None

        if is_hc:
            close_qty = remaining
            reason    = f"HARD CLOSE {POSITION_CLOSE_TIME[0]}:{POSITION_CLOSE_TIME[1]:02d} ET"
        elif mid <= pos["stop_price"]:
            close_qty = remaining
            reason    = f"STOP HIT ${mid:.2f} <= ${pos['stop_price']:.2f} ({pnl_pct:+.1f}%)"
        elif mid >= pos["target_75"]:
            close_qty = remaining
            reason    = f"TARGET 2 ${mid:.2f} >= ${pos['target_75']:.2f} ({pnl_pct:+.1f}%)"
        elif mid >= pos["target_50"] and not pos["partial_done"]:
            close_qty  = max(1, remaining // 2)
            is_partial = True
            reason     = f"TARGET 1 partial ${mid:.2f} >= ${pos['target_50']:.2f} ({pnl_pct:+.1f}%)"

        if close_qty <= 0:
            continue

        if DRY_RUN:
            log.info(f"[DRY RUN] Would close {close_qty}x {occ}: {reason}")
            pos["remaining"] -= close_qty
            if is_partial:
                pos["partial_done"] = True
            if pos["remaining"] <= 0:
                _remove_position(pos)
        else:
            ok = _close_option_position(occ, close_qty, reason)
            if ok:
                pos["remaining"] -= close_qty
                if is_partial:
                    pos["partial_done"] = True
                if pos["remaining"] <= 0:
                    _remove_position(pos)

        events.append({
            "occ_symbol":  occ,
            "symbol":      pos["symbol"],
            "direction":   pos["direction"],
            "close_qty":   close_qty,
            "mid":         mid,
            "entry_price": pos["entry_price"],
            "pnl_pct":     round(pnl_pct, 1),
            "reason":      reason,
            "is_partial":  is_partial,
        })

    return events


# ── Fill confirmation ─────────────────────────────────────────────────────────
def wait_for_fill(order_id: str, stop_event=None) -> bool:
    """Poll order status until filled or FILL_TIMEOUT_MINS elapses.

    Returns True if filled, False if cancelled/expired/timed-out.
    Cancels the order automatically on timeout.
    """
    if not TRADING_CLIENT:
        return False
    deadline = datetime.now(ET) + timedelta(minutes=FILL_TIMEOUT_MINS)
    while datetime.now(ET) < deadline:
        if stop_event and stop_event.is_set():
            break
        try:
            order = TRADING_CLIENT.get_order_by_id(order_id)
            status = str(order.status).lower()
            if status in ("filled", "partially_filled"):
                log.info(f"Fill confirmed: order {order_id} status={status}")
                return True
            if status in ("canceled", "expired", "replaced", "done_for_day"):
                log.warning(f"Order {order_id} ended without fill: status={status}")
                return False
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
    return False


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


if __name__ == "__main__":
    main()
