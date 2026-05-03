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

import time
import threading
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

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


# ── Config ────────────────────────────────────────────────────────────────────
DRY_RUN         = True
MAX_RISK_PCT    = 0.005
STOP_LOSS_PCT   = 0.50
PROFIT_TARGET   = 0.75
MIN_VOL_RATIO   = 1.5
RSI_OVERBOUGHT  = 70
RSI_OVERSOLD    = 30
MAX_SPREAD      = 0.15
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
HARD_CLOSE      = (15, 0)
TIME_STOP_MINS  = 60


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
    """Enable/disable ChromaDB trade memory. Called from app.py on login/logout."""
    global TRADE_MEMORY
    TRADE_MEMORY = TradeMemory(enabled=enabled)


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
    df["ema200"] = c.ewm(span=200, adjust=False).mean()

    delta = c.diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = (-delta.clip(upper=0)).rolling(14).mean()
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
            "1D": ("5d",  "15m"),   # request 5 days, filter to latest
            "5D": ("10d", "15m"),
            "1M": ("1mo", "1h"),
            "3M": ("3mo", "1h"),
            "1Y": ("1y",  "1d"),
            "5Y": ("5y",  "1d"),
        }
        period, interval = yf_config.get(tf_str, yf_config["5D"])

        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval=interval)

        if df.empty:
            log.warning(f"yfinance fallback({symbol}, {tf_str}): returned empty DataFrame")
            return []

        # 1D mode: keep only the most recent trading date
        if one_day_mode:
            df.index = pd.to_datetime(df.index)
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


def fetch_vix():
    """Try to fetch VIX. Alpaca's free IEX feed doesn't include indices, so this often fails."""
    if not DATA_CLIENT:
        return None
    try:
        request = StockLatestTradeRequest(symbol_or_symbols=["^VIX"], feed="iex")
        result  = DATA_CLIENT.get_stock_latest_trade(request)
        if "^VIX" in result:
            return float(result["^VIX"].price)
    except Exception:
        pass
    log.warning("Could not fetch VIX — proceeding without VIX filter")
    return None


def detect_gap(df, prior_close):
    if not prior_close or df is None or df.empty:
        return 0.0, None
    today_open = float(df.iloc[0]["open_price"])
    gap_pct    = (today_open - prior_close) / prior_close * 100
    direction  = "up" if gap_pct > 0 else "down" if gap_pct < 0 else None
    return round(gap_pct, 3), direction


def opening_range(df):
    first_time = df["begins_at"].iloc[0].replace(hour=9, minute=30, second=0)
    or_end     = first_time + timedelta(minutes=5)
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


def get_symbol_price(symbol: str = "SPY"):
    """Latest trade price for any symbol + day change %."""
    if not DATA_CLIENT:
        return None, None
    symbol = symbol.upper()
    try:
        trade_req = StockLatestTradeRequest(symbol_or_symbols=[symbol], feed="iex")
        trade_data = DATA_CLIENT.get_stock_latest_trade(trade_req)
        if symbol in trade_data:
            price = float(trade_data[symbol].price)
            request = StockBarsRequest(
                symbol_or_symbols = [symbol],
                timeframe         = TimeFrame.Day,
                start             = (datetime.now(timezone.utc) - timedelta(days=5)),
                feed              = "iex",
            )
            bars = DATA_CLIENT.get_stock_bars(request)
            sym_bars = bars[symbol]
            prev_close = float(sym_bars[-2].close) if len(sym_bars) >= 2 else price
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

        # Pick the contract closest to ATM
        contracts_sorted = sorted(contracts, key=lambda c: abs(float(c.strike_price) - current_price))
        c = contracts_sorted[0]

        return {
            "symbol":           c.symbol,        # OCC symbol (used for orders)
            "id":               c.id,
            "strike_price":     str(c.strike_price),
            "expiration_date":  c.expiration_date.isoformat(),
            "type":             "call" if contract_type == ContractType.CALL else "put",
            "underlying":       symbol,
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
    return max(1, int(max_risk / cost_per_contract))


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

    if not (0.40 <= abs_gap <= 1.50):
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

    if (current > vwap and above_vwap_pct > 0.65 and ema9 > ema21
            and 50 < rsi < RSI_OVERBOUGHT and vol_ratio >= 1.2
            and macd_hist > 0 and closing_up):
        return "bull", (f"VWAP momentum: above VWAP {above_vwap_pct:.0%} of day | "
                        f"RSI={rsi:.0f} | MACD green | {vol_ratio:.1f}x vol")

    if (current < vwap and above_vwap_pct < 0.35 and ema9 < ema21
            and RSI_OVERSOLD < rsi < 50 and vol_ratio >= 1.2
            and macd_hist < 0 and not closing_up):
        return "bear", (f"VWAP momentum: above VWAP only {above_vwap_pct:.0%} of day | "
                        f"RSI={rsi:.0f} | MACD red | {vol_ratio:.1f}x vol")

    return None, None


# ── Session runner ────────────────────────────────────────────────────────────
def run_session(session_name, session_end_hour, session_end_min,
                evaluate_fn, prior_levels, gap_info=None, stop_event=None,
                symbol: str = "SPY"):
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

        bar      = df.iloc[-1]
        prev_bar = df.iloc[-2] if len(df) > 1 else bar
        current  = float(bar["close_price"])
        atr      = float(bar["atr"]) if not np.isnan(bar["atr"]) else None

        atr_str = f"{atr:.2f}" if atr else "—"
        log.info(
            f"  {bar['begins_at'].strftime('%H:%M')}  "
            f"{symbol}=${current:.2f}  VWAP={bar['vwap']:.2f}  "
            f"EMA9={bar['ema9']:.2f}  EMA21={bar['ema21']:.2f}  "
            f"RSI={bar['rsi']:.1f}  MACD={bar['macd_hist']:.3f}  "
            f"ATR={atr_str}  Vol={bar['vol_ratio']:.2f}x  "
            f"BB[{bar['bb_lower']:.2f}–{bar['bb_upper']:.2f}]"
        )

        direction, reason = evaluate_fn(bar, prev_bar, df)

        if direction:
            # Surface similar past setups from memory before proceeding
            indicators_snapshot = bar.to_dict()
            memory_context = TRADE_MEMORY.retrieve_similar(symbol, direction, indicators_snapshot)
            if memory_context:
                log.info(memory_context)

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

    df = fetch_bars(symbol)
    if df is None:
        log.warning(f"Could not fetch {symbol} data. Skipping morning session.")
        return

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
                    stop_event=stop_event, symbol=symbol)
        return

    def morning_eval(bar, prev_bar, df):
        d, r = evaluate_orb(bar, prev_bar, or_high, or_low, df)
        if d: return d, r
        return evaluate_gap_fade(bar, gap_pct, gap_dir, df)

    run_session("Morning", eh, em, morning_eval, prior_levels,
                stop_event=stop_event, symbol=symbol)


def evening_session(prior_levels, stop_event=None, end_hour=None, end_minute=None,
                    symbol: str = "SPY"):
    symbol = symbol.upper()
    eh = end_hour   if end_hour   is not None else EVENING_END[0]
    em = end_minute if end_minute is not None else EVENING_END[1]
    log.info("=" * 60)
    log.info(f"EVENING SESSION ({symbol})  —  ends at {eh:02d}:{em:02d} ET")
    log.info("=" * 60)

    def evening_eval(bar, prev_bar, df):
        return evaluate_vwap_momentum(bar, prev_bar, df)

    run_session("Evening", eh, em, evening_eval, prior_levels,
                stop_event=stop_event, symbol=symbol)


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
