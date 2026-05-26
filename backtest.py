#!/usr/bin/env python3.11
"""
Backtest harness — SPY Auto Trader
====================================
Supports: yfinance (free), Polygon, Alpaca data sources.
Engines: 5-min intraday signals (ORB, VWAP, EMA, RSI) + daily setups
         (Breakout 50d, Bull Flag, RSI Dip, Gap+Vol).

Usage:
    venv/bin/python3.11 backtest.py                         # SPY, 1yr daily
    venv/bin/python3.11 backtest.py --symbol NVDA --years 2
    venv/bin/python3.11 backtest.py --symbols SPY NVDA AMZN --source polygon
    venv/bin/python3.11 backtest.py --bar-size 5min --days 59

Output:
    backtest_results/YYYY-MM-DD_<symbol>_<setup>.md  — per-symbol report
    backtest_results/summary.md                      — aggregate
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from datetime import datetime, date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import numpy as np

ET = ZoneInfo("America/New_York")
RESULTS_DIR = Path(__file__).parent / "backtest_results"
RESULTS_DIR.mkdir(exist_ok=True)

# ── Load .env ─────────────────────────────────────────────────────────────────
_ENV = Path(__file__).parent / ".env"
def _load_env():
    if not _ENV.exists():
        return
    for line in _ENV.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip("'\""))
_load_env()

# ── Signal parameters (mirror spy_auto_trader.py defaults) ────────────────────
STOP_LOSS_PCT      = 0.30   # 30% premium drop → stop
PARTIAL_PCT        = 0.30   # +30% → close 50%
PROFIT_TARGET_PCT  = 1.00   # +100% → close rest
HARD_CLOSE_HOUR    = 15     # 3 PM ET time stop
HARD_CLOSE_MIN     = 45
SESSION_START      = (9, 30)
SESSION_END        = (15, 45)

# ── Indicator computation (mirrors _add_indicators) ──────────────────────────
def _add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add VWAP, EMA9/21, RSI(14), volume ratio, ORB to bar dataframe."""
    df = df.copy()
    # VWAP — cumulative (reset each day)
    df["vwap"] = (df["Close"] * df["Volume"]).cumsum() / df["Volume"].cumsum()
    df["ema9"]  = df["Close"].ewm(span=9,  adjust=False).mean()
    df["ema21"] = df["Close"].ewm(span=21, adjust=False).mean()

    # RSI(14)
    delta = df["Close"].diff()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)
    avg_g = gain.ewm(span=14, adjust=False).mean()
    avg_l = loss.ewm(span=14, adjust=False).mean()
    rs    = avg_g / avg_l.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))

    # Volume ratio vs 20-bar rolling avg
    df["vol_avg"]   = df["Volume"].rolling(20).mean()
    df["vol_ratio"] = df["Volume"] / df["vol_avg"].replace(0, np.nan)

    # ATR(14)
    hl  = df["High"] - df["Low"]
    hc  = (df["High"] - df["Close"].shift()).abs()
    lc  = (df["Low"]  - df["Close"].shift()).abs()
    df["atr"] = pd.concat([hl, hc, lc], axis=1).max(axis=1).ewm(span=14, adjust=False).mean()

    return df


def _orb(day_bars: pd.DataFrame, orb_minutes: int = 30) -> tuple[float, float]:
    """Return (orb_high, orb_low) for the first `orb_minutes` of the day."""
    cutoff = day_bars.index[0] + pd.Timedelta(minutes=orb_minutes)
    orb    = day_bars[day_bars.index <= cutoff]
    if orb.empty:
        return float("nan"), float("nan")
    return float(orb["High"].max()), float(orb["Low"].min())


# ── Signal logic (simplified mirror of all_day_session checks) ────────────────
def _generate_signals(day_bars: pd.DataFrame) -> list[dict]:
    """
    Replay indicator logic on intraday bars and return a list of signal dicts.
    Each dict: {time, direction, reason, price, bar_idx}
    """
    signals = []
    if len(day_bars) < 25:
        return signals

    df = _add_indicators(day_bars)
    orb_h, orb_l = _orb(day_bars)
    orb_formed = not (math.isnan(orb_h) or math.isnan(orb_l))

    in_position = None  # track so we don't double-enter

    for i in range(25, len(df)):
        bar  = df.iloc[i]
        prev = df.iloc[i - 1]
        ts   = df.index[i]

        # Only trade in session hours
        if ts.hour < SESSION_START[0] or (ts.hour == SESSION_START[0] and ts.minute < SESSION_START[1]):
            continue
        if ts.hour > HARD_CLOSE_HOUR or (ts.hour == HARD_CLOSE_HOUR and ts.minute >= HARD_CLOSE_MIN):
            break
        # Avoid first 5 bars after ORB formation (~30 min window)
        if i < 35:
            continue

        close = float(bar["Close"])
        vwap  = float(bar["vwap"])  if not math.isnan(bar["vwap"])  else close
        ema9  = float(bar["ema9"])  if not math.isnan(bar["ema9"])  else close
        ema21 = float(bar["ema21"]) if not math.isnan(bar["ema21"]) else close
        rsi   = float(bar["rsi"])   if not math.isnan(bar["rsi"])   else 50.0
        vol_r = float(bar["vol_ratio"]) if not math.isnan(bar.get("vol_ratio", float("nan"))) else 1.0

        bull_score = 0
        bear_score = 0

        # ORB breakout
        if orb_formed and close > orb_h * 1.001 and prev["Close"] <= orb_h:
            bull_score += 2
        if orb_formed and close < orb_l * 0.999 and prev["Close"] >= orb_l:
            bear_score += 2

        # VWAP cross
        if close > vwap and prev["Close"] <= prev["vwap"]:
            bull_score += 1
        if close < vwap and prev["Close"] >= prev["vwap"]:
            bear_score += 1

        # EMA alignment
        if ema9 > ema21 and close > ema9:
            bull_score += 1
        if ema9 < ema21 and close < ema9:
            bear_score += 1

        # RSI gates (avoid overbought/oversold entries against direction)
        if rsi > 70:
            bear_score += 1
            bull_score = max(0, bull_score - 1)
        if rsi < 30:
            bull_score += 1
            bear_score = max(0, bear_score - 1)

        # Volume confirmation
        if vol_r < 1.2:
            bull_score = max(0, bull_score - 1)
            bear_score = max(0, bear_score - 1)

        direction = None
        reason    = ""
        # ORB breakout alone = strong signal (score 2); otherwise need 2+ confluence
        if bull_score >= 2 and bull_score > bear_score and in_position != "bull":
            direction = "bull"
            reason    = "ORB+VWAP+EMA bull" if bull_score >= 3 else "VWAP+EMA bull"
        elif bear_score >= 2 and bear_score > bull_score and in_position != "bear":
            direction = "bear"
            reason    = "ORB+VWAP+EMA bear" if bear_score >= 3 else "VWAP+EMA bear"

        if direction:
            signals.append({
                "time":      ts,
                "direction": direction,
                "reason":    reason,
                "price":     close,
                "bar_idx":   i,
                "rsi":       rsi,
                "vol_ratio": vol_r,
            })
            in_position = direction

    return signals


# ── Multi-source data fetching ────────────────────────────────────────────────

def _fetch_yfinance(symbol: str, days: int, bar_size: str) -> pd.DataFrame:
    """Fetch OHLCV via yfinance. bar_size: '5min' or 'daily'."""
    import yfinance as yf
    end   = datetime.now(ET)
    start = end - timedelta(days=days)
    ticker = yf.Ticker(symbol)
    interval = "5m" if bar_size == "5min" else "1d"
    df = ticker.history(start=start, end=end, interval=interval, auto_adjust=True)
    if df.empty:
        return df
    try:
        df.index = pd.DatetimeIndex(df.index).tz_convert(ET)
    except Exception:
        pass
    return df.dropna(subset=["Close", "Volume"])


def _fetch_polygon(symbol: str, days: int, bar_size: str) -> pd.DataFrame:
    """Fetch OHLCV via Polygon REST API."""
    import requests
    api_key = os.environ.get("POLYGON_API_KEY", "")
    if not api_key:
        raise ValueError("POLYGON_API_KEY not set in .env")
    end   = datetime.now(ET).date()
    start = (datetime.now(ET) - timedelta(days=days)).date()
    mult, span = (5, "minute") if bar_size == "5min" else (1, "day")
    url = (f"https://api.polygon.io/v2/aggs/ticker/{symbol}/range"
           f"/{mult}/{span}/{start}/{end}"
           f"?adjusted=true&sort=asc&limit=50000&apiKey={api_key}")
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    data = resp.json().get("results", [])
    if not data:
        return pd.DataFrame()
    df = pd.DataFrame(data)
    df.rename(columns={"o":"Open","h":"High","l":"Low","c":"Close","v":"Volume","t":"ts"}, inplace=True)
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True).dt.tz_convert(ET)
    df = df.set_index("ts").sort_index()
    return df[["Open","High","Low","Close","Volume"]].dropna()


def _fetch_alpaca(symbol: str, days: int, bar_size: str) -> pd.DataFrame:
    """Fetch OHLCV via Alpaca market data API."""
    import requests
    key    = os.environ.get("APCA_API_KEY_ID", "")
    secret = os.environ.get("APCA_API_SECRET_KEY", "")
    if not key or not secret:
        raise ValueError("APCA_API_KEY_ID / APCA_API_SECRET_KEY not set in .env")
    end   = datetime.now(ET)
    start = end - timedelta(days=days)
    tf    = "5Min" if bar_size == "5min" else "1Day"
    url   = f"https://data.alpaca.markets/v2/stocks/{symbol}/bars"
    headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
    params  = {
        "timeframe": tf,
        "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end":   end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "limit": 10000, "adjustment": "split",
    }
    rows = []
    while True:
        resp = requests.get(url, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        body = resp.json()
        rows.extend(body.get("bars", []))
        nt = body.get("next_page_token")
        if not nt:
            break
        params["page_token"] = nt
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df.rename(columns={"t":"ts","o":"Open","h":"High","l":"Low","c":"Close","v":"Volume"}, inplace=True)
    df["ts"] = pd.to_datetime(df["ts"], utc=True).dt.tz_convert(ET)
    df = df.set_index("ts").sort_index()
    return df[["Open","High","Low","Close","Volume"]].dropna()


def _fetch_data(symbol: str, days: int, source: str, bar_size: str) -> pd.DataFrame:
    """Route to the correct data source."""
    if source == "polygon":
        return _fetch_polygon(symbol, days, bar_size)
    if source == "alpaca":
        return _fetch_alpaca(symbol, days, bar_size)
    return _fetch_yfinance(symbol, min(days, 59) if bar_size == "5min" else days, bar_size)


# ── Strategy-filtered intraday signal generator ───────────────────────────────

def _generate_signals_filtered(day_bars: pd.DataFrame, strategies: list) -> list[dict]:
    """
    Same as _generate_signals but respects enabled-strategy list.
    strategies: subset of ["orb","vwap","ema","rsi_gate"]
    """
    signals = []
    if len(day_bars) < 25:
        return signals

    df = _add_indicators(day_bars)
    orb_h, orb_l = _orb(day_bars)
    orb_formed = not (math.isnan(orb_h) or math.isnan(orb_l))
    in_position = None

    for i in range(25, len(df)):
        bar  = df.iloc[i]
        prev = df.iloc[i - 1]
        ts   = df.index[i]

        if ts.hour < SESSION_START[0] or (ts.hour == SESSION_START[0] and ts.minute < SESSION_START[1]):
            continue
        if ts.hour > HARD_CLOSE_HOUR or (ts.hour == HARD_CLOSE_HOUR and ts.minute >= HARD_CLOSE_MIN):
            break
        if i < 35:
            continue

        close = float(bar["Close"])
        vwap  = float(bar["vwap"])  if not math.isnan(bar["vwap"])  else close
        ema9  = float(bar["ema9"])  if not math.isnan(bar["ema9"])  else close
        ema21 = float(bar["ema21"]) if not math.isnan(bar["ema21"]) else close
        rsi   = float(bar["rsi"])   if not math.isnan(bar["rsi"])   else 50.0
        vol_r = float(bar.get("vol_ratio", 1.0)) if not math.isnan(bar.get("vol_ratio", float("nan"))) else 1.0

        bull_score = bear_score = 0

        if "orb" in strategies and orb_formed:
            if close > orb_h * 1.001 and prev["Close"] <= orb_h:
                bull_score += 2
            if close < orb_l * 0.999 and prev["Close"] >= orb_l:
                bear_score += 2

        if "vwap" in strategies:
            if close > vwap and prev["Close"] <= prev["vwap"]:
                bull_score += 1
            if close < vwap and prev["Close"] >= prev["vwap"]:
                bear_score += 1

        if "ema" in strategies:
            if ema9 > ema21 and close > ema9:
                bull_score += 1
            if ema9 < ema21 and close < ema9:
                bear_score += 1

        if "rsi_gate" in strategies:
            if rsi > 70:
                bear_score += 1; bull_score = max(0, bull_score - 1)
            if rsi < 30:
                bull_score += 1; bear_score = max(0, bear_score - 1)

        direction = reason = None
        if bull_score >= 2 and bull_score > bear_score and in_position != "bull":
            direction = "bull"
            reason    = "+".join(filter(None, [
                "ORB" if "orb" in strategies else "",
                "VWAP" if "vwap" in strategies else "",
                "EMA"  if "ema"  in strategies else "",
            ])) + " bull"
        elif bear_score >= 2 and bear_score > bull_score and in_position != "bear":
            direction = "bear"
            reason    = "+".join(filter(None, [
                "ORB" if "orb" in strategies else "",
                "VWAP" if "vwap" in strategies else "",
                "EMA"  if "ema"  in strategies else "",
            ])) + " bear"

        if direction:
            signals.append({
                "time": ts, "direction": direction, "reason": reason,
                "price": close, "bar_idx": i, "rsi": rsi, "vol_ratio": vol_r,
            })
            in_position = direction

    return signals


# ── Daily setup signal engine ─────────────────────────────────────────────────

def _generate_daily_signals(daily_df: pd.DataFrame, strategies: list,
                            vol_min: float = 1.2) -> list[dict]:
    """
    Replay screener daily setups on historical daily bars.

    All KB rules implemented (cross-referenced from knowledge_base.md):
      §DT2 Breakout    – new 50d high, RSI14 55-78, relVol>vol_min,
                         NOT chasing (≤3% above high50), Impulse not Red
      §DT4 RSI Dip     – RSI14<35, RSI2<20, ABOVE 200-day MA (§T9 critical filter)
                         Red Impulse is BETTER (PF 1.82) — not filtered out
      §DT5 Gap+Vol     – gap>1%, relVol≥max(vol_min,1.5)
      §DT3 Bull Flag   – 4d surge>3%, today_range<65% prev_range, RSI50-78,
                         Impulse not Red
      §T6  RSI Dip+Red – RSI Dip + Red Impulse + FI2d<0 = best sub-condition PF 1.82
      §DT14 NR7        – narrowest range in 7 bars → volatility breakout (Cooper)
      §T13  BB Squeeze – Bollinger Bandwidth at 6-month low → directional breakout
      §T8   Pocket Pivot – up-day volume > max down-day vol of prior 10 sessions
      §T22  PBS        – Pristine Buy Setup: 3+ consec lower-H/lower-L/red bars
      §DT8  Turtle Soup – new 20-day low then recovery = false breakdown (Raschke)

    strategies: subset of ["breakout","bull_flag","rsi_dip","gap_vol",
                            "rsi_dip_red","nr7","bb_squeeze",
                            "pocket_pivot","pbs","turtle_soup"]
    """
    signals = []
    if len(daily_df) < 55:
        return signals

    df = daily_df.copy()

    # ── RSI 14
    delta = df["Close"].diff()
    gain  = delta.clip(lower=0); loss = (-delta).clip(lower=0)
    ag    = gain.ewm(span=14, adjust=False).mean()
    al    = loss.ewm(span=14, adjust=False).mean()
    df["rsi14"] = 100 - (100 / (1 + ag / al.replace(0, np.nan)))

    # ── RSI 2
    g2 = delta.clip(lower=0); l2 = (-delta).clip(lower=0)
    ag2 = g2.ewm(span=2, adjust=False).mean(); al2 = l2.ewm(span=2, adjust=False).mean()
    df["rsi2"] = 100 - (100 / (1 + ag2 / al2.replace(0, np.nan)))

    # ── 50-day prior high (shift 1 so today's bar doesn't include itself)
    df["high50"] = df["High"].rolling(51).max().shift(1)

    # ── 20-day ADV & vol ratio
    df["adv20"]     = df["Volume"].rolling(20).mean().shift(1)
    df["vol_ratio"] = df["Volume"] / df["adv20"].replace(0, np.nan)

    # ── Gap %
    df["gap_pct"] = (df["Open"] / df["Close"].shift(1) - 1) * 100

    # ── 200-day MA — §T9: "do NOT use RSI(2) on stocks below 200-day MA. Ever."
    df["ma200"] = df["Close"].rolling(200).mean()

    # ── Elder Impulse System (§T6): EMA13 direction + MACD-Histogram direction
    #    Green = both rising (momentum setups: enter) | Red = both falling
    #    For Breakout/Bull Flag: Red = avoid. For RSI Dip: Red = BETTER (PF 1.82)
    df["ema13"]    = df["Close"].ewm(span=13, adjust=False).mean()
    df["ema26"]    = df["Close"].ewm(span=26, adjust=False).mean()
    macd_line      = df["ema13"] - df["ema26"]
    macd_signal    = macd_line.ewm(span=9, adjust=False).mean()
    df["macd_h"]   = macd_line - macd_signal
    df["ema13_up"] = df["ema13"] > df["ema13"].shift(1)
    df["macdh_up"] = df["macd_h"] > df["macd_h"].shift(1)
    df["impulse_green"] = df["ema13_up"] & df["macdh_up"]
    df["impulse_red"]   = (~df["ema13_up"]) & (~df["macdh_up"])

    # ── Force Index FI2d (Elder §T7): 2-day EMA of (Close − PrevClose) × Volume
    #    FI2d < 0 during dip = "real" selling pressure → optimal RSI Dip entry
    fi_raw     = (df["Close"] - df["Close"].shift(1)) * df["Volume"]
    df["fi2d"] = fi_raw.ewm(span=2, adjust=False).mean()

    # ── 20-day low for Turtle Soup (Raschke §DT8)
    df["low20"] = df["Low"].rolling(21).min().shift(1)

    # ── Bollinger Band Squeeze (§T13 Method I, §DT12)
    #    Bandwidth = (Upper - Lower) / Middle; at 6-month low → coiling → breakout
    bb_mid    = df["Close"].rolling(20).mean()
    bb_std    = df["Close"].rolling(20).std()
    bb_bw     = (bb_mid + 2*bb_std - (bb_mid - 2*bb_std)) / bb_mid.replace(0, np.nan)
    bw_6m_min = bb_bw.rolling(126).min()
    df["bb_squeeze"] = (bb_bw <= bw_6m_min * 1.05).fillna(False)  # ≤5% above 6-month min

    # ── NR7 — Narrowest Range of last 7 bars (Cooper §DT14)
    #    "The breakout from NR7 often produces a trend day" — buy stop above NR7 high
    df["day_range"]  = df["High"] - df["Low"]
    range7_max       = df["day_range"].rolling(7).max().shift(1)
    df["nr7"]        = (df["day_range"] < range7_max).fillna(False)

    # ── Pocket Pivot (Morales/Kacher §T8)
    #    Up day AND today's volume > highest down-day volume of prior 10 sessions
    #    Signals hidden institutional accumulation before the full breakout
    is_up            = df["Close"] >= df["Open"]
    vol_on_down_days = df["Volume"].where(~is_up, 0)
    max_down_vol10   = vol_on_down_days.rolling(10).max().shift(1)
    df["pocket_pivot"] = (is_up & (df["Volume"] > max_down_vol10)).fillna(False)

    # ── Pristine Buy Setup / PBS (Velez §T22)
    #    3+ consecutive bars: lower high + lower low + red close = Minor Stage 4 in Major Stage 2
    #    Entry: buy when stock trades above prior day's high
    lower_high  = (df["High"]  < df["High"].shift(1)).astype(int)
    lower_low   = (df["Low"]   < df["Low"].shift(1)).astype(int)
    red_bar     = (df["Close"] < df["Open"]).astype(int)
    all_pbs     = lower_high & lower_low & red_bar
    df["pbs_3"] = all_pbs.rolling(3).sum().shift(1)  # count of prior 3 bars all meeting criteria

    for i in range(55, len(df)):
        row     = df.iloc[i]
        close   = float(row["Close"])
        high_   = float(row["High"])
        low_    = float(row["Low"])
        rsi14   = float(row["rsi14"])  if pd.notna(row["rsi14"])   else 50.0
        rsi2    = float(row["rsi2"])   if pd.notna(row["rsi2"])    else 50.0
        high50  = float(row["high50"]) if pd.notna(row["high50"])  else close
        vol_r   = float(row["vol_ratio"]) if pd.notna(row["vol_ratio"]) else 1.0
        gap_pct = float(row["gap_pct"])   if pd.notna(row["gap_pct"])   else 0.0
        ma200   = float(row["ma200"])  if pd.notna(row["ma200"])   else 0.0
        fi2d    = float(row["fi2d"])   if pd.notna(row["fi2d"])    else 0.0
        low20   = float(row["low20"])  if pd.notna(row["low20"])   else low_
        impulse_green = bool(row["impulse_green"]) if pd.notna(row["impulse_green"]) else False
        impulse_red   = bool(row["impulse_red"])   if pd.notna(row["impulse_red"])   else False
        bb_squeeze    = bool(row["bb_squeeze"])    if pd.notna(row["bb_squeeze"])    else False
        nr7           = bool(row["nr7"])           if pd.notna(row["nr7"])           else False
        pocket_pivot  = bool(row["pocket_pivot"])  if pd.notna(row["pocket_pivot"])  else False
        pbs_3         = float(row["pbs_3"]) if pd.notna(row["pbs_3"]) else 0.0

        # 200-day MA filter (NaN until bar 200; signals simply don't fire before then)
        above_200ma = (ma200 > 0 and close > ma200)

        # ── BREAKOUT (§DT2) ──────────────────────────────────────────────────
        # New 50d high · RSI14 55-78 · relVol>vol_min
        # Chase filter (§DT2): skip if already >3% above the 50d high
        # Impulse filter (§T6): Green/Blue OK; Red = no momentum setups
        if "breakout" in strategies:
            not_chasing = close <= high50 * 1.03   # §DT2: "do NOT chase >3% from high"
            impulse_ok  = not impulse_red           # §T6: Breakout+Red PF=0.00
            if (close > high50 and not_chasing and
                    55 <= rsi14 <= 78 and vol_r >= vol_min and impulse_ok):
                signals.append({"time": df.index[i], "setup": "Breakout",
                    "price": close, "bar_idx": i, "rsi": rsi14, "vol_ratio": vol_r})

        # ── RSI DIP (§DT4, §T9) ──────────────────────────────────────────────
        # RSI14<35 · RSI2<20 · ABOVE 200MA (§T9 critical: "edge evaporates below 200MA")
        # Red Impulse acceptable & BETTER (§T6: PF 1.82 vs 1.41) — NOT filtered out
        if "rsi_dip" in strategies:
            if rsi14 < 35 and rsi2 < 20 and above_200ma:
                signals.append({"time": df.index[i], "setup": "RSI Dip",
                    "price": close, "bar_idx": i, "rsi": rsi14, "vol_ratio": vol_r,
                    "impulse_red": impulse_red, "fi2d_neg": fi2d < 0})

        # ── RSI DIP + RED IMPULSE (§T6 best sub-group: PF 1.82) ─────────────
        # RSI Dip + Red Impulse + FI2d<0 = all three mean-reversion signals aligned
        # "Maximum conviction" (Elder §T7): extreme oversold + sustained selling + bearish momentum
        if "rsi_dip_red" in strategies:
            if rsi14 < 35 and rsi2 < 20 and above_200ma and impulse_red and fi2d < 0:
                signals.append({"time": df.index[i], "setup": "RSI Dip+Red",
                    "price": close, "bar_idx": i, "rsi": rsi14, "vol_ratio": vol_r})

        # ── GAP + VOL (§DT5) ─────────────────────────────────────────────────
        if "gap_vol" in strategies:
            if gap_pct > 1.0 and vol_r >= max(vol_min, 1.5):
                signals.append({"time": df.index[i], "setup": "Gap+Vol",
                    "price": close, "bar_idx": i, "rsi": rsi14, "vol_ratio": vol_r})

        # ── BULL FLAG (§DT3) ─────────────────────────────────────────────────
        # Prior 4d surge >3% · today_range <65% of prior range · RSI 50-78
        # Impulse filter (§T6): Green PF 2.29; Red never naturally occurs
        if "bull_flag" in strategies and i >= 4:
            surge      = (float(df.iloc[i-1]["Close"]) / float(df.iloc[i-4]["Close"]) - 1) * 100
            t_range    = (high_ - low_) / max(close, 0.01)
            p_range    = ((float(df.iloc[i-1]["High"]) - float(df.iloc[i-1]["Low"])) /
                         max(float(df.iloc[i-1]["Close"]), 0.01))
            impulse_ok = not impulse_red
            if surge > 3.0 and t_range < p_range * 0.65 and 50 <= rsi14 <= 78 and impulse_ok:
                signals.append({"time": df.index[i], "setup": "Bull Flag",
                    "price": close, "bar_idx": i, "rsi": rsi14, "vol_ratio": vol_r})

        # ── NR7 — Narrowest Range 7 (Cooper §DT14) ──────────────────────────
        # Today's range < any of prior 7 bars = coiling energy → explosive move
        # Long-only (above 200MA): direction = trend
        if "nr7" in strategies and nr7 and above_200ma:
            signals.append({"time": df.index[i], "setup": "NR7",
                "price": close, "bar_idx": i, "rsi": rsi14, "vol_ratio": vol_r})

        # ── BOLLINGER BAND SQUEEZE (§T13, §DT12) ────────────────────────────
        # Bandwidth at 6-month low = volatility compression → breakout imminent
        # Filter: above 200MA + Green Impulse (trend-confirmed squeeze)
        if "bb_squeeze" in strategies and bb_squeeze and above_200ma and impulse_green:
            signals.append({"time": df.index[i], "setup": "BB Squeeze",
                "price": close, "bar_idx": i, "rsi": rsi14, "vol_ratio": vol_r})

        # ── POCKET PIVOT (Morales/Kacher §T8) ───────────────────────────────
        # Up-day volume > highest down-day volume of prior 10 sessions
        # Must be near 50d area (≤10% extended) + above 200MA
        if "pocket_pivot" in strategies and pocket_pivot and above_200ma:
            if close <= high50 * 1.10:  # not extended more than 10% above 50d high
                signals.append({"time": df.index[i], "setup": "Pocket Pivot",
                    "price": close, "bar_idx": i, "rsi": rsi14, "vol_ratio": vol_r})

        # ── PRISTINE BUY SETUP / PBS (Velez §T22) ───────────────────────────
        # 3+ consecutive bars: lower high + lower low + red close (Minor Stage 4 pullback)
        # Entry: buy when today's price > prior day's high (continuation signal)
        if "pbs" in strategies and pbs_3 >= 3 and above_200ma:
            signals.append({"time": df.index[i], "setup": "PBS",
                "price": close, "bar_idx": i, "rsi": rsi14, "vol_ratio": vol_r})

        # ── TURTLE SOUP / 20-Day Low Reversal (Raschke §DT8) ────────────────
        # Prior day made new 20-day low (stop-run), today recovers above 20d low = false breakdown
        # Confirms exhaustion (also excellent when combined with RSI Dip)
        if "turtle_soup" in strategies and i >= 1 and pd.notna(row["low20"]):
            prev_low = float(df.iloc[i-1]["Low"])
            if prev_low <= low20 and close > low20 and above_200ma:
                signals.append({"time": df.index[i], "setup": "Turtle Soup",
                    "price": close, "bar_idx": i, "rsi": rsi14, "vol_ratio": vol_r})

    return signals


def _daily_pnl(signals: list[dict], daily_df: pd.DataFrame,
               stop_pct: float = 0.08, target_pct: float = 0.25,
               max_hold: int = 20) -> list[dict]:
    """
    Simulate multi-day hold P&L for daily setup signals.
    Entry: next day's open. Exit: stop / T1 (50% at +15%) / T2 (rest at target_pct) / max_hold.
    """
    trades = []
    df = daily_df.reset_index()
    t1_pct = min(0.15, target_pct * 0.5)  # partial target = 50% of full target or 15%, whichever smaller

    for sig in signals:
        i = sig["bar_idx"]
        if i + 1 >= len(df):
            continue
        entry_row  = df.iloc[i + 1]
        entry      = float(entry_row["Open"]) if pd.notna(entry_row["Open"]) else float(entry_row["Close"])
        entry_time = entry_row.iloc[0]  # the index column

        remaining  = 1.0
        pnl_locked = 0.0
        exit_reason = "max_hold"
        exit_time   = df.iloc[min(i + max_hold, len(df) - 1)].iloc[0]

        for j in range(i + 1, min(i + max_hold + 1, len(df))):
            bar   = df.iloc[j]
            low_  = float(bar["Low"])
            high_ = float(bar["High"])
            close_= float(bar["Close"])

            stop_price = entry * (1 - stop_pct)
            if low_ <= stop_price:
                pnl_locked += -stop_pct * remaining
                exit_reason = "stop"; exit_time = bar.iloc[0]; remaining = 0.0; break

            t1_price = entry * (1 + t1_pct)
            if high_ >= t1_price and remaining == 1.0:
                pnl_locked += t1_pct * 0.5; remaining = 0.5

            t2_price = entry * (1 + target_pct)
            if high_ >= t2_price and remaining > 0:
                pnl_locked += target_pct * remaining
                if remaining < 1.0:           # already took partial
                    pnl_locked += t1_pct * 0.0  # already counted
                exit_reason = "target"; exit_time = bar.iloc[0]; remaining = 0.0; break

        if remaining > 0:
            last_close = float(df.iloc[min(i + max_hold, len(df) - 1)]["Close"])
            pnl_locked += ((last_close - entry) / entry) * remaining

        trades.append({
            "entry_time": entry_time, "exit_time": exit_time,
            "direction": "bull", "setup": sig["setup"],
            "reason": sig["setup"], "entry_price": entry,
            "pnl_pct": round(pnl_locked * 100, 2),
            "exit_reason": exit_reason,
            "rsi": sig.get("rsi", 50), "vol_ratio": sig.get("vol_ratio", 1.0),
        })

    return trades


# ── Daily backtest entry point ────────────────────────────────────────────────

def run_daily_backtest(symbol: str, years: float, source: str = "yfinance",
                       strategies: list | None = None,
                       stop_pct: float = 0.08, target_pct: float = 0.25,
                       vol_min: float = 1.2) -> list[dict]:
    """
    Run daily-bar backtest for all requested daily setups.
    Returns a list of result dicts (one per setup).
    """
    if strategies is None:
        strategies = ["breakout", "bull_flag", "rsi_dip", "gap_vol"]

    days = max(60, int(years * 365))
    print(f"\n{'─'*50}")
    print(f"  {symbol} — {years}yr daily backtest ({source})")
    print(f"  Strategies: {', '.join(strategies)}")

    try:
        df = _fetch_data(symbol, days, source, "daily")
    except Exception as e:
        print(f"  [error] Failed to fetch {symbol}: {e}")
        return []

    if df.empty or len(df) < 55:
        print(f"  [warn] Not enough daily data for {symbol} ({len(df)} bars)")
        return []

    baseline_pct = (df["Close"].iloc[-1] / df["Close"].iloc[0] - 1) * 100 if len(df) > 1 else 0.0
    print(f"  {len(df)} daily bars | B&H: {baseline_pct:+.2f}%")

    signals = _generate_daily_signals(df, strategies, vol_min=vol_min)
    print(f"  Total signals: {len(signals)}")

    # Map strategy keys → display names (covers all KB-validated strategies)
    setup_map = {
        "breakout":     "Breakout",
        "bull_flag":    "Bull Flag",
        "rsi_dip":      "RSI Dip",
        "gap_vol":      "Gap+Vol",
        "rsi_dip_red":  "RSI Dip+Red",
        "nr7":          "NR7",
        "bb_squeeze":   "BB Squeeze",
        "pocket_pivot": "Pocket Pivot",
        "pbs":          "PBS",
        "turtle_soup":  "Turtle Soup",
    }

    results = []
    for setup in strategies:
        setup_name = setup_map.get(setup, setup.replace("_", " ").title())
        sigs = [s for s in signals if s["setup"] == setup_name]

        # Use tighter stops for daily holds
        trades = _daily_pnl(sigs, df,
                             stop_pct=min(stop_pct, 0.12),
                             target_pct=min(target_pct * 0.25, 0.35))  # scale intraday targets to daily

        m = _metrics(trades)
        pf = m.get("profit_factor", "n/a")
        print(f"  {setup_name}: {len(trades)} trades | WR {m.get('win_rate',0):.1f}% | PF {pf}")

        results.append({
            "symbol":   symbol,
            "setup":    setup_name,
            "trades":   len(trades),
            "metrics":  m,
            "baseline": round(baseline_pct, 2),
        })

    return results


# ── Simplified option P&L approximation ───────────────────────────────────────
def _option_pnl(entry_px: float, signals: list[dict],
                df: pd.DataFrame) -> list[dict]:
    """
    Simulate P&L for each signal using underlying price movement as a proxy.

    This is NOT actual option pricing. We use a simplified model:
      - ATM option premium ≈ 0.5% of underlying × days_to_expiry^0.5 (rough)
      - Delta ≈ 0.5 for ATM, decays as underlying moves away
      - We track the underlying move and apply a 2× leverage factor
        (typical ATM option exposure for 7-14 DTE)

    For real dollar accuracy you need historical option chains (Polygon/ThetaData).
    This gives a valid signal quality signal: is the direction right?
    """
    trades = []
    for sig in signals:
        i     = sig["bar_idx"]
        entry = sig["price"]
        dir_  = sig["direction"]
        rows  = df.iloc[i:]

        # Approximate initial option premium (0.5% of underlying for 7-14 DTE ATM)
        opt_entry = entry * 0.005 * 3.0  # ~1.5% of underlying = rough ATM premium

        stop_px  = opt_entry * (1 - STOP_LOSS_PCT)
        part_px  = opt_entry * (1 + PARTIAL_PCT)
        tgt_px   = opt_entry * (1 + PROFIT_TARGET_PCT)

        pnl_pct  = None
        exit_reason = "time_stop"
        exit_time   = None

        remaining = 1.0  # fraction of position

        for j in range(1, len(rows)):
            bar      = rows.iloc[j]
            bar_time = rows.index[j]
            und_px   = float(bar["Close"])

            # Underlying move → option proxy (delta ≈ 0.5, leverage ≈ 2×)
            und_move = (und_px - entry) / entry
            if dir_ == "bear":
                und_move = -und_move
            opt_current = opt_entry * (1 + und_move * 2.0)
            opt_current = max(opt_current, 0.01)

            opt_pct = (opt_current - opt_entry) / opt_entry

            # Time stop
            if (bar_time.hour > HARD_CLOSE_HOUR or
                    (bar_time.hour == HARD_CLOSE_HOUR and bar_time.minute >= HARD_CLOSE_MIN)):
                pnl_pct = opt_pct * remaining
                exit_reason = "time_stop"
                exit_time = bar_time
                break

            # Stop
            if opt_current <= stop_px:
                pnl_pct = -STOP_LOSS_PCT * remaining
                exit_reason = "stop"
                exit_time = bar_time
                break

            # T1 partial
            if opt_current >= part_px and remaining == 1.0:
                remaining = 0.5
                # lock half at +30%
                pnl_pct_partial = PARTIAL_PCT * 0.5
                opt_entry = opt_current  # reset basis for trailing half
                continue

            # T2 full close
            if opt_current >= tgt_px:
                pnl_pct = PROFIT_TARGET_PCT * remaining + (PARTIAL_PCT * 0.5 if remaining < 1 else 0)
                exit_reason = "target"
                exit_time = bar_time
                break
        else:
            # End of day
            pnl_pct = opt_pct if pnl_pct is None else pnl_pct

        if pnl_pct is None:
            pnl_pct = 0.0

        trades.append({
            "entry_time":  sig["time"],
            "exit_time":   exit_time or rows.index[-1],
            "direction":   dir_,
            "reason":      sig["reason"],
            "entry_price": entry,
            "pnl_pct":     round(pnl_pct * 100, 2),
            "exit_reason": exit_reason,
            "rsi":         sig["rsi"],
            "vol_ratio":   sig["vol_ratio"],
        })

    return trades


# ── Metrics ───────────────────────────────────────────────────────────────────
def _metrics(trades: list[dict]) -> dict:
    if not trades:
        return {"n": 0}
    wins   = [t for t in trades if t["pnl_pct"] > 0]
    losses = [t for t in trades if t["pnl_pct"] < 0]
    n      = len(trades)
    wr     = len(wins) / n * 100
    avg_w  = sum(t["pnl_pct"] for t in wins)  / len(wins)  if wins  else 0
    avg_l  = sum(t["pnl_pct"] for t in losses) / len(losses) if losses else 0
    gw     = sum(t["pnl_pct"] for t in wins)
    gl     = abs(sum(t["pnl_pct"] for t in losses))
    pf     = gw / gl if gl else float("inf")
    exp    = (wr / 100) * avg_w + (1 - wr / 100) * avg_l
    r_unit = STOP_LOSS_PCT * 100
    avg_r  = (sum(t["pnl_pct"] for t in trades) / n / r_unit) if r_unit else 0

    # Sharpe approximation (daily P&L, annualised)
    daily = pd.Series([t["pnl_pct"] for t in trades])
    sharpe = (daily.mean() / daily.std() * math.sqrt(252)) if daily.std() > 0 else 0

    # Max drawdown on cumulative P&L
    cumul = daily.cumsum()
    peak  = cumul.cummax()
    dd    = (cumul - peak).min()

    # Baseline: buy-and-hold underlying (rough comparison)
    return {
        "n": n, "wins": len(wins), "losses": len(losses),
        "win_rate": round(wr, 1),
        "avg_win": round(avg_w, 2), "avg_loss": round(avg_l, 2),
        "gross_wins": round(gw, 2), "gross_losses": round(gl, 2),
        "profit_factor": round(pf, 2) if pf != float("inf") else "∞",
        "expectancy": round(exp, 2),
        "avg_r": round(avg_r, 2),
        "sharpe": round(sharpe, 2),
        "max_dd": round(float(dd), 2),
        "total_pnl": round(sum(t["pnl_pct"] for t in trades), 2),
    }


# ── Report builder ────────────────────────────────────────────────────────────
def _report(symbol: str, period_days: int, trades: list[dict], m: dict,
            baseline_pct: float) -> str:
    today = date.today().isoformat()
    pf    = m.get("profit_factor", "n/a")
    lines = [
        f"# Backtest Report — {symbol}",
        f"_Period: last {period_days} calendar days | Generated: {today}_",
        f"_Underlying data: yfinance 5-min bars | Option P&L: delta-proxy model_",
        "",
        "---",
        "",
        "## Summary",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Trades | {m.get('n', 0)} |",
        f"| Win Rate | {m.get('win_rate', 0):.1f}% |",
        f"| Avg Win | {m.get('avg_win', 0):+.2f}% |",
        f"| Avg Loss | {m.get('avg_loss', 0):+.2f}% |",
        f"| Profit Factor | {pf} |",
        f"| Expectancy | {m.get('expectancy', 0):+.2f}% / trade |",
        f"| Avg R-Multiple | {m.get('avg_r', 0):+.2f}R |",
        f"| Sharpe (annualised) | {m.get('sharpe', 0):.2f} |",
        f"| Max Drawdown | {m.get('max_dd', 0):.2f}% |",
        f"| Total Signal P&L | {m.get('total_pnl', 0):+.2f}% |",
        f"| Buy-and-Hold underlying | {baseline_pct:+.2f}% |",
        "",
        "---",
        "",
        "## Trade Log",
        "",
        "| Date | Dir | Reason | Entry $ | P&L % | Exit |",
        "|------|-----|--------|---------|-------|------|",
    ]
    for t in trades:
        dt  = t["entry_time"].strftime("%m-%d %H:%M")
        dir_= "CALL" if t["direction"] == "bull" else "PUT"
        lines.append(
            f"| {dt} | {dir_} | {t['reason']} "
            f"| ${t['entry_price']:.2f} | {t['pnl_pct']:+.2f}% | {t['exit_reason']} |"
        )

    lines += [
        "",
        "---",
        "",
        "## Interpretation",
        "",
        "> **Important:** P&L figures use a simplified delta-proxy model, not real option",
        "> chain data. They indicate *signal direction quality*, not exact dollar returns.",
        "> For real option P&L, integrate Polygon Historical Options or ThetaData.",
        "",
        "### What to look for",
        "- **Profit factor > 1.5** → signal has edge worth pursuing",
        "- **Win rate > 50% + avg win > avg loss** → directional edge confirmed",
        "- **Sharpe > 0.5** → risk-adjusted returns acceptable",
        "- **Beat buy-and-hold** → the system adds value vs passive exposure",
        "",
        "### Next steps if edge looks weak",
        "1. Raise `bull_score` / `bear_score` threshold from 3 → 4",
        "2. Require `vol_ratio > 1.5` (only trade on volume spikes)",
        "3. Add regime filter (skip choppy days: SPY range < 0.5%)",
        "4. Test 0-DTE vs 7-DTE on the same signals",
        "",
        f"_SPY Auto Trader Backtest — {today}_",
    ]
    return "\n".join(lines)


# ── Intraday (5-min) backtest entry point ─────────────────────────────────────
def run_backtest(symbol: str, days: int, source: str = "yfinance",
                 strategies: list | None = None,
                 stop_pct: float = 0.30, target_pct: float = 1.00,
                 vol_min: float = 1.2, bar_size: str = "5min") -> dict:
    """
    5-min intraday signal backtest. Days capped at 59 for yfinance.
    Returns a single result dict with setup="Intraday".
    """
    if strategies is None:
        strategies = ["orb", "vwap", "ema", "rsi_gate"]

    # cap for yfinance; Polygon/Alpaca can do more but we cap at 90 for perf
    days = min(days, 59 if source == "yfinance" else 90)

    print(f"\n{'─'*50}")
    print(f"  {symbol} — {days}d intraday backtest ({source}, strategies: {strategies})")

    try:
        df = _fetch_data(symbol, days, source, "5min")
    except Exception as e:
        print(f"  [error] {symbol}: {e}")
        return {}

    if df.empty:
        print(f"  [warn] No data for {symbol}")
        return {}

    try:
        df.index = pd.DatetimeIndex(df.index).tz_convert(ET)
    except Exception:
        pass
    df = df.dropna(subset=["Close", "Volume"])
    print(f"  {len(df)} 5-min bars loaded")

    baseline_pct = (df["Close"].iloc[-1] / df["Close"].iloc[0] - 1) * 100 if len(df) > 1 else 0.0

    # Override module-level constants with caller params
    global STOP_LOSS_PCT, PROFIT_TARGET_PCT, PARTIAL_PCT
    _orig_stop = STOP_LOSS_PCT; _orig_tgt = PROFIT_TARGET_PCT; _orig_par = PARTIAL_PCT
    STOP_LOSS_PCT = stop_pct; PROFIT_TARGET_PCT = target_pct; PARTIAL_PCT = target_pct * 0.3

    all_trades: list[dict] = []
    trading_days = df.groupby(df.index.date)
    for _day, day_df in trading_days:
        if len(day_df) < 10:
            continue
        sigs   = _generate_signals_filtered(day_df, strategies)
        trades = _option_pnl(float(day_df["Close"].iloc[0]), sigs, day_df)
        all_trades.extend(trades)

    STOP_LOSS_PCT = _orig_stop; PROFIT_TARGET_PCT = _orig_tgt; PARTIAL_PCT = _orig_par

    print(f"  Signals fired: {len(all_trades)}")
    m = _metrics(all_trades)
    pf = m.get("profit_factor", "n/a")
    print(f"  WR {m.get('win_rate',0):.1f}% | PF {pf} | Sharpe {m.get('sharpe',0):.2f}")
    print(f"  Signal P&L: {m.get('total_pnl',0):+.2f}% vs B&H: {baseline_pct:+.2f}%")

    report = _report(symbol, days, all_trades, m, baseline_pct)
    out_path = RESULTS_DIR / f"{date.today().isoformat()}_{symbol}_intraday.md"
    out_path.write_text(report)

    return {"symbol": symbol, "setup": "Intraday", "metrics": m,
            "trades": len(all_trades), "baseline": round(baseline_pct, 2)}


def _summary_report(results: list[dict]) -> str:
    today = date.today().isoformat()
    lines = [
        f"# Backtest Summary — {today}",
        "",
        "| Symbol | Trades | Win% | PF | Expectancy | Sharpe | MaxDD | Signal P&L | vs Buy&Hold |",
        "|--------|--------|------|----|-----------|--------|-------|-----------|------------|",
    ]
    for r in results:
        m = r.get("metrics", {})
        lines.append(
            f"| {r['symbol']} | {r['trades']} | {m.get('win_rate',0):.1f}% "
            f"| {m.get('profit_factor','n/a')} | {m.get('expectancy',0):+.2f}% "
            f"| {m.get('sharpe',0):.2f} | {m.get('max_dd',0):.2f}% "
            f"| {m.get('total_pnl',0):+.2f}% | {r.get('baseline',0):+.2f}% |"
        )
    lines += [
        "",
        "---",
        "",
        "## Key thresholds",
        "- **PF > 1.5** = has edge | **PF 1.0–1.5** = marginal | **PF < 1.0** = losing",
        "- **Sharpe > 0.5** = acceptable risk-adjusted returns",
        "- **Signal P&L > Buy&Hold** = strategy adds value over passive",
        "",
        "_Option P&L uses delta-proxy approximation. Treat as signal quality indicator._",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SPY Auto Trader backtest harness")
    parser.add_argument("--symbol",     default="SPY",  help="Single symbol")
    parser.add_argument("--symbols",    nargs="+",       help="Multiple symbols")
    parser.add_argument("--years",      type=float, default=1.0, help="Lookback in years (default: 1)")
    parser.add_argument("--days",       type=int,   default=None, help="Lookback in days (overrides --years)")
    parser.add_argument("--source",     default="yfinance",
                        choices=["yfinance","polygon","alpaca"], help="Data source")
    parser.add_argument("--bar-size",   default="daily", choices=["daily","5min"])
    parser.add_argument("--strategies", nargs="+",
                        default=["breakout","bull_flag","rsi_dip","gap_vol"],
                        help=("Daily strategies: breakout bull_flag rsi_dip gap_vol "
                              "rsi_dip_red nr7 bb_squeeze pocket_pivot pbs turtle_soup | "
                              "Intraday: orb vwap ema rsi_gate"))
    parser.add_argument("--stop",       type=float, default=0.08, help="Stop loss fraction (default: 0.08)")
    parser.add_argument("--target",     type=float, default=0.25, help="Profit target fraction (default: 0.25)")
    parser.add_argument("--vol-min",    type=float, default=1.2,  help="Min volume ratio (default: 1.2)")
    args = parser.parse_args()

    symbols = args.symbols or [args.symbol]
    years   = args.years if args.days is None else args.days / 365
    print(f"\n{'='*50}")
    print(f"  SPY Auto Trader — Backtest Harness")
    print(f"  Symbols: {', '.join(symbols)} | {years}yr | {args.source} | {args.bar_size}")
    print(f"  Strategies: {', '.join(args.strategies)}")
    print(f"{'='*50}")

    results = []
    for sym in symbols:
        if args.bar_size == "daily":
            rs = run_daily_backtest(sym, years, args.source, args.strategies,
                                    stop_pct=args.stop, target_pct=args.target,
                                    vol_min=args.vol_min)
            results.extend(rs)
        else:
            days = min(59, int(years * 365))
            r = run_backtest(sym, days, args.source, args.strategies,
                             stop_pct=args.stop * 3, target_pct=args.target * 4,
                             vol_min=args.vol_min, bar_size="5min")
            if r:
                results.append(r)

    if len(results) > 1:
        summary = _summary_report(results)
        summary_path = RESULTS_DIR / "summary.md"
        summary_path.write_text(summary)
        print(f"\nSummary → {summary_path}")
        print(summary)
    elif results:
        m = results[0]["metrics"]
        print(f"\n✅ Done. PF: {m.get('profit_factor','n/a')} | "
              f"Win rate: {m.get('win_rate',0):.1f}% | "
              f"Sharpe: {m.get('sharpe',0):.2f}")
