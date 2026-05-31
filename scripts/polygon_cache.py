#!/usr/bin/env python3.11
"""
polygon_cache.py — Download and cache 5yr Polygon data locally.

Downloads daily + 1-minute OHLCV bars for all 25 universe symbols
and saves them as Parquet files for fast local access.

Cache location:
  ~/Desktop/bharath/AlpacaTrader_Data/polygon_cache/
    {SYM}_daily.parquet   — 5yr daily bars  (~1,260 rows/sym)
    {SYM}_minute.parquet  — 5yr 1-min bars  (~490,000 rows/sym, ~30MB/sym)
    _manifest.json        — download timestamps

Usage:
  venv/bin/python3.11 scripts/polygon_cache.py            # download all missing
  venv/bin/python3.11 scripts/polygon_cache.py --refresh  # force re-download all
"""
from __future__ import annotations
import argparse
import json
import os
import time
from datetime import datetime, date
from pathlib import Path

import pandas as pd
import requests

# ── Config ────────────────────────────────────────────────────────────────────
POLY_KEY    = os.environ.get("POLYGON_API_KEY", "fCJpwXDqn7wa7sBdQIfDCxfLHmpnmA0S")
CACHE_DIR   = Path.home() / "Desktop" / "bharath" / "AlpacaTrader_Data" / "polygon_cache"
START_DATE  = "2021-01-01"
END_DATE    = date.today().strftime("%Y-%m-%d")
SLEEP_BETWEEN = 0.12   # ~8 calls/sec — polite with paid tier

UNIVERSE_1 = [
    "NVDA", "INTC", "AMD",  "MU",   "TSLA",
    "QCOM", "PLTR", "ORCL", "HOOD", "ON",
    "AVGO", "LRCX", "ANET", "NOW",  "COHR",
    "VRT",  "SMCI", "WDC",  "GLW",  "MCHP",
    "CRM",  "AMAT", "TXN",  "APP",  "CVNA",
]

# Batch 2 — mega-cap tech + cybersecurity + crypto + cloud + fintech + EV
UNIVERSE_2 = [
    "AAPL", "MSFT", "AMZN", "META", "GOOGL",   # mega-cap
    "NFLX", "CRWD", "PANW", "COIN", "MSTR",    # streaming / cyber / crypto
    "SNOW", "DDOG", "ARM",  "RBLX", "SPOT",    # cloud / semis / consumer
    "SOFI", "UPST", "AFRM", "SQ",   "MARA",    # fintech / crypto-mining
    "RIVN", "LCID", "OKTA", "TEAM", "RIOT",    # EV / cyber / crypto-mining
]

# Combined for full 50-symbol runs
UNIVERSE = UNIVERSE_1 + UNIVERSE_2


# ── Polygon helpers ───────────────────────────────────────────────────────────
def _poly_get(url: str) -> dict:
    """GET with apiKey appended; raises on non-200."""
    sep = "&" if "?" in url else "?"
    r   = requests.get(f"{url}{sep}apiKey={POLY_KEY}", timeout=30)
    r.raise_for_status()
    return r.json()


def _fetch_aggs(ticker: str, multiplier: int, span: str,
                start: str, end: str) -> list[dict]:
    """
    Fetch all aggregate bars (with auto-pagination via next_url).
    Returns list of raw Polygon result dicts.
    """
    url = (f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/"
           f"{multiplier}/{span}/{start}/{end}"
           f"?adjusted=true&sort=asc&limit=50000")
    results: list[dict] = []
    while url:
        d = _poly_get(url)
        if d.get("status") not in ("OK", "DELAYED"):
            break
        results.extend(d.get("results", []))
        next_url = d.get("next_url")
        if next_url:
            url = next_url   # next_url already has apiKey appended by Polygon
            time.sleep(SLEEP_BETWEEN)
        else:
            url = None
    return results


def _to_df(results: list[dict], freq: str) -> pd.DataFrame:
    """Convert raw Polygon results to a clean DataFrame with ET DatetimeIndex."""
    df = pd.DataFrame(results)
    df["ts"] = pd.to_datetime(df["t"], unit="ms", utc=True).dt.tz_convert("America/New_York")
    df = df.rename(columns={"o": "open", "h": "high", "l": "low",
                             "c": "close", "v": "volume", "vw": "vwap"})
    df = df[["ts", "open", "high", "low", "close", "volume", "vwap"]].copy()
    df = df.sort_values("ts").reset_index(drop=True)
    return df


# ── Download daily bars ────────────────────────────────────────────────────────
def download_daily(sym: str, force: bool = False) -> pd.DataFrame | None:
    out = CACHE_DIR / f"{sym}_daily.parquet"
    if out.exists() and not force:
        return None   # already cached

    print(f"  {sym}: downloading daily bars {START_DATE}→{END_DATE} ...", end=" ", flush=True)
    t0 = time.time()
    try:
        rows = _fetch_aggs(sym, 1, "day", START_DATE, END_DATE)
        if not rows:
            print("NO DATA")
            return None
        df = _to_df(rows, "1D")
        df.to_parquet(out, index=False, compression="snappy")
        print(f"{len(df)} bars  [{time.time()-t0:.1f}s]")
        return df
    except Exception as e:
        print(f"ERROR: {e}")
        return None


# ── Download minute bars (with pagination) ────────────────────────────────────
def download_minute(sym: str, force: bool = False) -> pd.DataFrame | None:
    out = CACHE_DIR / f"{sym}_minute.parquet"
    if out.exists() and not force:
        return None   # already cached

    print(f"  {sym}: downloading 1-min bars {START_DATE}→{END_DATE} ...", end=" ", flush=True)
    t0 = time.time()
    try:
        rows = _fetch_aggs(sym, 1, "minute", START_DATE, END_DATE)
        if not rows:
            print("NO DATA")
            return None
        df = _to_df(rows, "1m")

        # Keep only regular market hours (9:30–16:00 ET) to save space
        df = df[(df["ts"].dt.hour >= 9) &
                ((df["ts"].dt.hour < 16) |
                 ((df["ts"].dt.hour == 9) & (df["ts"].dt.minute >= 30)))].copy()

        df.to_parquet(out, index=False, compression="snappy")
        mb = out.stat().st_size / 1024 / 1024
        print(f"{len(df):,} bars  {mb:.1f} MB  [{time.time()-t0:.1f}s]")
        return df
    except Exception as e:
        print(f"ERROR: {e}")
        return None


# ── Load helpers (used by backtest) ──────────────────────────────────────────
def load_daily(sym: str) -> pd.DataFrame:
    """Load cached daily bars. Raises if not cached."""
    f = CACHE_DIR / f"{sym}_daily.parquet"
    if not f.exists():
        raise FileNotFoundError(f"Daily cache missing for {sym} — run polygon_cache.py first")
    return pd.read_parquet(f)


def load_minute(sym: str) -> pd.DataFrame:
    """Load cached 1-min bars. Raises if not cached."""
    f = CACHE_DIR / f"{sym}_minute.parquet"
    if not f.exists():
        raise FileNotFoundError(f"Minute cache missing for {sym} — run polygon_cache.py first")
    df = pd.read_parquet(f)
    df["ts"] = pd.to_datetime(df["ts"])
    if df["ts"].dt.tz is None:
        df["ts"] = df["ts"].dt.tz_localize("America/New_York")
    return df


# ── Main ──────────────────────────────────────────────────────────────────────
def _load_sp500() -> list[str]:
    """Full S&P 500 symbol list from scripts/sp500.json (503 names)."""
    p = Path(__file__).parent / "sp500.json"
    return json.loads(p.read_text())


def main(force: bool = False, symbols: list[str] | None = None,
         phase: str = "both") -> None:
    """
    Download daily and/or minute bars for `symbols`.

    phase: "daily" | "minute" | "both" — lets us grab all daily bars first
           (cheap, fast, foundational) before the long minute pull.
    Resumable: existing parquet files are skipped unless force=True.
    """
    target = symbols if symbols is not None else UNIVERSE
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = CACHE_DIR / "_manifest.json"
    manifest: dict = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text())
        except Exception:
            pass

    print("=" * 65)
    print(f"  Polygon Cache Builder — {START_DATE} → {END_DATE}")
    print(f"  Symbols: {len(target)}  |  Phase: {phase}  |  Cache: {CACHE_DIR}")
    print("=" * 65, flush=True)

    # ── Daily bars ────────────────────────────────────────────────────────────
    if phase in ("daily", "both"):
        print("\n── Daily bars ──", flush=True)
        done = 0
        for i, sym in enumerate(target, 1):
            df = download_daily(sym, force=force)
            if df is None and (CACHE_DIR / f"{sym}_daily.parquet").exists():
                if i % 25 == 0 or i == len(target):
                    print(f"  [{i}/{len(target)}] {sym}: cached", flush=True)
            if df is not None:
                manifest[f"{sym}_daily"] = datetime.now().isoformat()
                done += 1
            time.sleep(SLEEP_BETWEEN)
        manifest["updated"] = datetime.now().isoformat()
        manifest_path.write_text(json.dumps(manifest, indent=2))
        print(f"  daily phase: {done} newly downloaded", flush=True)

    # ── Minute bars ───────────────────────────────────────────────────────────
    if phase in ("minute", "both"):
        print("\n── 1-minute bars (RTH only: 9:30–16:00 ET) ──", flush=True)
        total_mb = 0.0
        for i, sym in enumerate(target, 1):
            out = CACHE_DIR / f"{sym}_minute.parquet"
            print(f"  [{i}/{len(target)}]", end=" ", flush=True)
            df = download_minute(sym, force=force)
            if df is None and out.exists():
                mb = out.stat().st_size / 1024 / 1024
                total_mb += mb
                print(f"  {sym}: cached  ({mb:.1f} MB)", flush=True)
            elif df is not None:
                mb = out.stat().st_size / 1024 / 1024
                total_mb += mb
                manifest[f"{sym}_minute"] = datetime.now().isoformat()
                manifest["updated"] = datetime.now().isoformat()
                manifest_path.write_text(json.dumps(manifest, indent=2))

    # ── Summary ───────────────────────────────────────────────────────────────
    daily_ok  = sum(1 for s in target if (CACHE_DIR / f"{s}_daily.parquet").exists())
    minute_ok = sum(1 for s in target if (CACHE_DIR / f"{s}_minute.parquet").exists())
    print(f"\n  ✅ Daily:  {daily_ok}/{len(target)} symbols cached")
    print(f"  ✅ Minute: {minute_ok}/{len(target)} symbols cached")

    manifest["updated"] = datetime.now().isoformat()
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"\n  Manifest → {manifest_path}")
    print("=" * 65, flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true",
                    help="Force re-download even if cached")
    ap.add_argument("--batch", choices=["1", "2", "all", "sp500"], default="all",
                    help="1=first 25, 2=second 25, all=50, sp500=full 503 (default all)")
    ap.add_argument("--phase", choices=["daily", "minute", "both"], default="both",
                    help="Which bars to pull: daily (fast), minute (large), or both")
    args = ap.parse_args()

    batch_map = {"1": UNIVERSE_1, "2": UNIVERSE_2, "all": UNIVERSE,
                 "sp500": _load_sp500()}
    main(force=args.refresh, symbols=batch_map[args.batch], phase=args.phase)
