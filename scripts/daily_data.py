#!/usr/bin/env python3.11
"""
daily_data.py — yfinance daily OHLC fetcher with on-disk parquet cache.

Replaces the Polygon 5-min dependency for the daily-bar frame-shift (Path A).
yfinance gives 5+ years of daily OHLC free; cache is permanent (re-run is $0).

Cache location: ~/Desktop/bharath/AlpacaTrader_Data/daily_cache/{SYMBOL}.parquet
Columns: date (datetime64, tz-naive), open, high, low, close, volume (float64)

Usage:
    from daily_data import fetch_daily
    df = fetch_daily("NVDA")         # returns DataFrame or None

    # Or run standalone to pre-cache all 39 symbols:
    venv/bin/python3.11 scripts/daily_data.py [SYM ...]
"""
from __future__ import annotations
import sys, warnings
from pathlib import Path
from datetime import date

warnings.filterwarnings("ignore")

import pandas as pd

CACHE_DIR = Path.home() / "Desktop" / "bharath" / "AlpacaTrader_Data" / "daily_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# CSV is the cache format — no extra deps (no pyarrow/fastparquet required)

# Pull 5 full calendar years so the 200-day SMA has plenty of warmup
YEARS_BACK = 5
START_DATE = f"{date.today().year - YEARS_BACK}-01-01"


def _cache_path(symbol: str) -> Path:
    return CACHE_DIR / f"{symbol.upper()}.csv"


def fetch_daily(symbol: str, force_refresh: bool = False) -> pd.DataFrame | None:
    """
    Return a daily OHLC DataFrame for *symbol* (all available history in cache).

    Columns: date, open, high, low, close, volume
    date is a timezone-naive datetime64[ns] at midnight.

    Cache-first: if the parquet exists and force_refresh=False, return it.
    Otherwise pull from yfinance and write the cache.
    Returns None if yfinance returns empty data.
    """
    sym = symbol.upper()
    cp = _cache_path(sym)
    if cp.exists() and not force_refresh:
        df = pd.read_csv(cp, parse_dates=["date"])
        if not df.empty:
            return df

    try:
        import yfinance as yf
    except ImportError:
        raise RuntimeError("yfinance not installed — run: pip install yfinance")

    ticker = yf.Ticker(sym)
    raw = ticker.history(start=START_DATE, interval="1d", auto_adjust=True,
                         actions=False)
    if raw is None or raw.empty:
        return None

    df = raw.reset_index()
    # yfinance column names vary slightly across versions — normalise
    col_map = {}
    for c in df.columns:
        cl = c.lower()
        if cl in ("date", "datetime"):
            col_map[c] = "date"
        elif cl == "open":
            col_map[c] = "open"
        elif cl == "high":
            col_map[c] = "high"
        elif cl == "low":
            col_map[c] = "low"
        elif cl in ("close", "adj close", "adj_close"):
            col_map[c] = "close"
        elif cl == "volume":
            col_map[c] = "volume"
    df = df.rename(columns=col_map)
    keep = [c for c in ("date", "open", "high", "low", "close", "volume")
            if c in df.columns]
    df = df[keep].copy()

    # Ensure date is timezone-naive datetime64
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    df = df.sort_values("date").reset_index(drop=True)

    # Cast OHLCV to float64 (yfinance sometimes returns object)
    for c in ("open", "high", "low", "close", "volume"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df.dropna(subset=["close"])
    if df.empty:
        return None

    df.to_csv(cp, index=False)
    return df


# ── standalone pre-cache runner ──────────────────────────────────────────────
def main() -> None:
    from universe import ALL
    syms = [s.upper() for s in sys.argv[1:]] if sys.argv[1:] else list(ALL)
    print(f"daily_data — caching {len(syms)} symbol(s) via yfinance ({START_DATE} → today)",
          flush=True)
    ok = fail = 0
    for s in syms:
        df = fetch_daily(s, force_refresh=True)
        if df is not None:
            print(f"  {s:<6} {len(df)} days  {df['date'].iloc[0].date()} → {df['date'].iloc[-1].date()}")
            ok += 1
        else:
            print(f"  {s:<6} FAIL (no data)")
            fail += 1
    print(f"\n✓ done  {ok} OK / {fail} failed  cache → {CACHE_DIR}")


if __name__ == "__main__":
    main()
