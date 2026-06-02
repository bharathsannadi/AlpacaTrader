#!/usr/bin/env python3.11
"""
polygon_options.py — pull 5yr of daily OPTION OHLC before the Polygon
subscription lapses (2026-06-16).

No bulk/grouped options endpoint on this tier, so we go per-contract:
  1. Enumerate each underlying's contracts via the reference API (incl. expired).
  2. Keep MONTHLY expiries (3rd Friday) only, strikes within ±BAND of ATM
     (ATM taken from the cached daily close ~30 days before each expiry),
     CALLS and PUTS.
  3. Pull daily aggregate bars for each kept contract.
  4. Write one parquet per underlying: {underlying}_options_daily.parquet
     columns: contract, underlying, type, strike, expiry, ts, open, high, low,
              close, volume, vwap

Resumable: an underlying whose parquet already exists is skipped (unless --force).

Scope (operator decision 2026-05-31): the ~100 most-liquid S&P 500 optionable
names, ranked by average dollar-volume from the cached daily bars.

Usage:
  venv/bin/python3.11 scripts/polygon_options.py --top 100
  venv/bin/python3.11 scripts/polygon_options.py --symbols AAPL NVDA
"""
from __future__ import annotations
import argparse, json, time
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

from polygon_cache import POLY_KEY, CACHE_DIR, START_DATE, END_DATE, SLEEP_BETWEEN

OPT_DIR  = CACHE_DIR / "options"
BAND     = 0.15          # ±15% of ATM strike band
EXP_LO   = "2021-01-01"
EXP_HI   = "2026-12-31"


# Resilient HTTP session: retry on 429/5xx with backoff, pooled connections, and a
# (connect, read) timeout tuple so a stuck request can't wedge the whole pull.
_SESSION = requests.Session()
try:
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    _retry = Retry(total=4, connect=4, read=4, backoff_factor=1.5,
                   status_forcelist=(429, 500, 502, 503, 504),
                   allowed_methods=frozenset(["GET"]), raise_on_status=False)
    _SESSION.mount("https://", HTTPAdapter(max_retries=_retry, pool_maxsize=8))
except Exception:
    pass


def _poly_get(url: str) -> dict:
    sep = "&" if "?" in url else "?"
    # (connect=10s, read=30s); the Retry adapter handles 429/5xx + transient drops.
    r = _SESSION.get(f"{url}{sep}apiKey={POLY_KEY}", timeout=(10, 30))
    r.raise_for_status()
    return r.json()


def _third_friday(y: int, m: int) -> date:
    """3rd Friday of month m, year y (standard monthly option expiry)."""
    d = date(y, m, 1)
    # weekday(): Mon=0..Sun=6; Friday=4
    first_fri = d + timedelta(days=(4 - d.weekday()) % 7)
    return first_fri + timedelta(days=14)


def _monthly_expiries(lo: str, hi: str) -> set[str]:
    lo_d, hi_d = date.fromisoformat(lo), date.fromisoformat(hi)
    out: set[str] = set()
    y, m = lo_d.year, lo_d.month
    while date(y, m, 1) <= hi_d:
        out.add(_third_friday(y, m).isoformat())
        m += 1
        if m > 12:
            m = 1; y += 1
    return out


def _list_contracts(underlying: str) -> list[dict]:
    """All contracts for `underlying` over the expiry window (paginated, incl. expired)."""
    url = (f"https://api.polygon.io/v3/reference/options/contracts"
           f"?underlying_ticker={underlying}&expired=true"
           f"&expiration_date.gte={EXP_LO}&expiration_date.lte={EXP_HI}"
           f"&limit=1000&sort=expiration_date")
    out: list[dict] = []
    while url:
        d = _poly_get(url)
        out.extend(d.get("results", []))
        url = d.get("next_url")
        if url:
            time.sleep(SLEEP_BETWEEN)
    return out


def _atm_close(daily: pd.DataFrame, expiry: str) -> float | None:
    """Underlying close ~30 calendar days before `expiry` (entry-window ATM)."""
    if daily is None or daily.empty:
        return None
    target = pd.Timestamp(expiry) - pd.Timedelta(days=30)
    ts = daily["ts"]
    ts = ts.dt.tz_localize(None) if ts.dt.tz is not None else ts
    prior = daily[ts <= target]
    if prior.empty:
        return float(daily["close"].iloc[0])
    return float(prior["close"].iloc[-1])


def _agg_contract(ticker: str) -> list[dict]:
    url = (f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day/"
           f"{START_DATE}/{END_DATE}?adjusted=true&sort=asc&limit=50000")
    rows: list[dict] = []
    while url:
        d = _poly_get(url)
        if d.get("status") not in ("OK", "DELAYED"):
            break
        rows.extend(d.get("results", []))
        url = d.get("next_url")
        if url:
            time.sleep(SLEEP_BETWEEN)
    return rows


def pull_underlying(underlying: str, force: bool = False) -> int:
    """Pull all in-band monthly call+put daily bars for one underlying.
    Returns number of contracts with data written."""
    out_path = OPT_DIR / f"{underlying}_options_daily.parquet"
    if out_path.exists() and not force:
        print(f"  {underlying}: cached — skip", flush=True)
        return -1

    # underlying daily bars for ATM reference
    daily_path = CACHE_DIR / f"{underlying}_daily.parquet"
    daily = pd.read_parquet(daily_path) if daily_path.exists() else None
    if daily is not None:
        daily["ts"] = pd.to_datetime(daily["ts"])

    try:
        contracts = _list_contracts(underlying)
    except Exception as e:
        print(f"  {underlying}: contract list ERROR {e}", flush=True)
        return 0

    monthly = _monthly_expiries(EXP_LO, EXP_HI)
    # filter: monthly expiry + strike within ±BAND of ATM-at-entry
    keep: list[dict] = []
    atm_cache: dict[str, float | None] = {}
    for c in contracts:
        exp = c.get("expiration_date")
        if exp not in monthly:
            continue
        strike = c.get("strike_price")
        if strike is None:
            continue
        if exp not in atm_cache:
            atm_cache[exp] = _atm_close(daily, exp) if daily is not None else None
        atm = atm_cache[exp]
        if atm and atm > 0 and abs(strike / atm - 1.0) > BAND:
            continue
        keep.append(c)

    print(f"  {underlying}: {len(contracts)} contracts → {len(keep)} in-band monthly "
          f"({len(monthly)} expiries)", flush=True)

    all_rows: list[dict] = []
    got = 0
    for j, c in enumerate(keep, 1):
        tk = c["ticker"]
        try:
            bars = _agg_contract(tk)
        except Exception:
            bars = []
        time.sleep(SLEEP_BETWEEN)
        if j % 200 == 0:
            print(f"    {underlying}: {j}/{len(keep)} scanned, {got} with data…", flush=True)
        if not bars:
            continue
        got += 1
        for b in bars:
            all_rows.append({
                "contract":   tk,
                "underlying": underlying,
                "type":       c.get("contract_type"),
                "strike":     c.get("strike_price"),
                "expiry":     c.get("expiration_date"),
                "ts":         b["t"],
                "open": b.get("o"), "high": b.get("h"), "low": b.get("l"),
                "close": b.get("c"), "volume": b.get("v"), "vwap": b.get("vw"),
            })

    if all_rows:
        df = pd.DataFrame(all_rows)
        df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True).dt.tz_convert("America/New_York")
        df = df.sort_values(["expiry", "strike", "ts"]).reset_index(drop=True)
        OPT_DIR.mkdir(parents=True, exist_ok=True)
        df.to_parquet(out_path, index=False, compression="snappy")
        mb = out_path.stat().st_size / 1024 / 1024
        print(f"  {underlying}: ✅ {got} contracts, {len(df):,} bars, {mb:.1f} MB", flush=True)
    else:
        # write an empty marker so we don't re-attempt a no-data name forever
        OPT_DIR.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(columns=["contract"]).to_parquet(out_path, index=False)
        print(f"  {underlying}: no option data", flush=True)
    return got


def _liquidity_rank(symbols: list[str]) -> list[str]:
    """Order `symbols` by mean dollar-volume (last ~250 daily bars), desc.
    Symbols without a cached daily file go last (in original order)."""
    scored, unscored = [], []
    for sym in symbols:
        f = CACHE_DIR / f"{sym}_daily.parquet"
        if not f.exists():
            unscored.append(sym); continue
        try:
            df = pd.read_parquet(f, columns=["close", "volume"]).tail(250)
            scored.append((float((df["close"] * df["volume"]).mean()), sym))
        except Exception:
            unscored.append(sym)
    scored.sort(reverse=True)
    return [s for _, s in scored] + unscored


def liquid_top(n: int) -> list[str]:
    """Top-n most-liquid S&P 500 names by dollar-volume."""
    sp = list(json.loads((Path(__file__).parent / "sp500.json").read_text()))
    return _liquidity_rank(sp)[:n]


def prioritized_universe() -> list[str]:
    """Full options-pull order (operator: 'priority etfs then stocks').

    1. ALL ETFs (trade + hedge), liquidity-ranked  — pulled FIRST
    2. ALL S&P 500 stocks, liquidity-ranked        — pulled after
    De-duped, preserving the ETF-first priority.
    """
    from universe import ETFS_TRADE, ETFS_HEDGE
    etfs = _liquidity_rank(list(dict.fromkeys(ETFS_TRADE + ETFS_HEDGE)))
    sp   = _liquidity_rank(list(json.loads((Path(__file__).parent / "sp500.json").read_text())))
    seen, out = set(), []
    for s in etfs + sp:
        if s not in seen:
            seen.add(s); out.append(s)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=100, help="top-N most-liquid S&P names")
    ap.add_argument("--symbols", nargs="*", help="explicit symbol list (overrides others)")
    ap.add_argument("--scope", choices=["top", "etfs", "full"], default="top",
                    help="top=liquid --top · etfs=all ETFs · full=ETFs first then all S&P500")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    if args.symbols:
        syms = [s.upper() for s in args.symbols]
    elif args.scope == "etfs":
        from universe import ETFS_TRADE, ETFS_HEDGE
        syms = _liquidity_rank(list(dict.fromkeys(ETFS_TRADE + ETFS_HEDGE)))
    elif args.scope == "full":
        syms = prioritized_universe()
    else:
        syms = liquid_top(args.top)
    OPT_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 65)
    print(f"  Polygon OPTIONS pull — {len(syms)} underlyings, ±{int(BAND*100)}% band, "
          f"monthly, calls+puts")
    print(f"  Cache: {OPT_DIR}")
    print("=" * 65, flush=True)

    t0 = time.time()
    for i, sym in enumerate(syms, 1):
        print(f"[{i}/{len(syms)}] {sym}  (elapsed {(time.time()-t0)/60:.0f}m)", flush=True)
        pull_underlying(sym, force=args.force)

    done = len(list(OPT_DIR.glob("*_options_daily.parquet")))
    print(f"\n  ✅ {done} underlyings have option parquet files in {OPT_DIR}")


if __name__ == "__main__":
    main()
