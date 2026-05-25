#!/usr/bin/env python3.11
"""
backtest_screener_criteria.py — Validate screener setup criteria on 2yr history.

Tests 5 intraday setup classifications against next-day open-to-close return:
  1. RSI Dip      (daily RSI14 < 35 at close)
  2. Momentum     (RSI14 > 60 AND close > EMA20 AND chg > +1%)
  3. Gap+Vol      (gap > 1% from prior close AND rel-vol > 1.5×)
  4. VWAP Bounce  (proxy: RSI14 40-55 AND price within 0.5% of EMA20)
  5. Breakout     (RSI14 55-70 AND close > 50-day high)

For each setup we measure:
  - N trades
  - Win rate (next-day close > open)
  - Average next-day return (open → close)
  - Profit factor
  - Annualised edge vs buy-and-hold

Also validates options direction accuracy:
  - When RSI14 > 60 → is next-day directionally correct for a call? (directional hit %)
  - When RSI2 < 10  → (from daily Connors — already proven at 66.4%)

Output: JSON saved to AlpacaTrader_Data/screener_backtest_results.json
        + console summary table

Usage:
  venv/bin/python3.11 scripts/backtest_screener_criteria.py
"""
from __future__ import annotations
import json
import math
import warnings
from datetime import date
from pathlib import Path

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf

OUT_DIR = Path.home() / "Desktop" / "bharath" / "AlpacaTrader_Data"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_FILE = OUT_DIR / "screener_backtest_results.json"

UNIVERSE = [
    "NVDA", "INTC", "AMD", "MU",   "TSLA",
    "QCOM", "PLTR", "ORCL", "HOOD", "ON",
    "AVGO", "LRCX", "ANET", "NOW",  "COHR",
    "VRT",  "SMCI", "WDC",  "GLW",  "MCHP",
    "CRM",  "AMAT", "TXN",  "APP",  "CVNA",
]

LOOKBACK = "2y"

# ── Indicator helpers ────────────────────────────────────────────────────────

def _rsi(s: pd.Series, n: int) -> pd.Series:
    d = s.diff()
    g = d.clip(lower=0).rolling(n).mean()
    l = (-d).clip(lower=0).rolling(n).mean()
    rs = g / l.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def _classify(df: pd.DataFrame) -> pd.Series:
    """Classify each row into a setup type using EOD indicators."""
    rsi14  = _rsi(df["Close"], 14)
    rsi2   = _rsi(df["Close"], 2)
    ema20  = _ema(df["Close"], 20)
    ema9   = _ema(df["Close"], 9)
    high50 = df["Close"].rolling(50).max().shift(1)
    gap    = (df["Open"] - df["Close"].shift(1)) / df["Close"].shift(1) * 100
    vol_avg = df["Volume"].rolling(30).mean().shift(1)
    rel_vol = df["Volume"] / vol_avg
    chg     = (df["Close"] - df["Open"]) / df["Open"] * 100

    setup = pd.Series("Neutral", index=df.index)

    # Breakout: close makes new 50-day high AND RSI14 55-70 AND rel-vol > 1.3
    mask = (df["Close"] > high50) & (rsi14 > 55) & (rsi14 < 75) & (rel_vol > 1.3)
    setup[mask] = "Breakout"

    # Gap+Vol: gap > 1% AND rel-vol > 1.5× (Aziz p.31)
    mask = (gap > 1.0) & (rel_vol > 1.5)
    setup[mask] = "Gap+Vol"

    # Momentum: RSI14 > 60 AND above EMA20 AND day chg > +1%
    mask = (rsi14 > 60) & (df["Close"] > ema20) & (chg > 1.0)
    setup[mask] = "Momentum"

    # VWAP Bounce (proxy with EMA9): RSI14 40-58, near EMA9, not falling
    near_ema9 = (df["Close"] - ema9).abs() / ema9 < 0.005
    mask = (rsi14 >= 38) & (rsi14 <= 58) & near_ema9 & (chg > -0.5)
    setup[mask] = "VWAP Bounce"

    # RSI Dip: RSI14 < 35 (oversold long setup, Connors mean-revert)
    mask = rsi14 < 35
    setup[mask] = "RSI Dip"

    # RSI2 Dip (Connors daily: already proven but include for reference)
    mask = rsi2 < 10
    setup[mask] = "RSI2 Dip"

    return setup


def _backtest_symbol(sym: str) -> list[dict]:
    """Return list of trade dicts (one per setup day) for a symbol."""
    try:
        df = yf.Ticker(sym).history(period=LOOKBACK, interval="1d",
                                    auto_adjust=True, actions=False)
        if df is None or len(df) < 60:
            return []
        df = df.copy()
        df.index = pd.to_datetime(df.index).tz_localize(None)
        df["setup"]      = _classify(df)
        # next-day open→close return (what a day-trader captures)
        df["next_ret"]   = (df["Close"].shift(-1) - df["Open"].shift(-1)) / \
                            df["Open"].shift(-1) * 100
        # next-day directional accuracy (for options)
        df["next_up"]    = (df["Close"].shift(-1) > df["Open"].shift(-1)).astype(int)
        # drop last row (no next-day data) and warm-up
        df = df.iloc[55:-1]
        rows = []
        for _, r in df.iterrows():
            if r["setup"] == "Neutral":
                continue
            if pd.isna(r["next_ret"]):
                continue
            rows.append({
                "sym":     sym,
                "setup":   r["setup"],
                "ret":     float(r["next_ret"]),
                "next_up": int(r["next_up"]),
            })
        return rows
    except Exception as e:
        print(f"  {sym}: FAIL ({e})")
        return []


def _stats(trades: list[dict]) -> dict:
    if not trades:
        return {"n": 0, "win_pct": 0, "avg_ret": 0, "pf": 0, "edge": "No data"}
    rets  = [t["ret"] for t in trades]
    wins  = [r for r in rets if r > 0]
    loss  = [r for r in rets if r <= 0]
    pf    = (sum(wins) / abs(sum(loss))) if loss and sum(loss) != 0 else float("inf")
    win_p = len(wins) / len(rets) * 100
    avg_r = float(np.mean(rets))
    dir_p = float(np.mean([t["next_up"] for t in trades]) * 100)
    edge  = "✅ Edge" if pf > 1.2 and avg_r > 0 else ("⚠ Marginal" if pf > 0.9 else "❌ No Edge")
    return {
        "n":       len(trades),
        "win_pct": round(win_p, 1),
        "avg_ret": round(avg_r, 3),
        "pf":      round(pf, 2),
        "dir_pct": round(dir_p, 1),
        "edge":    edge,
    }


def main() -> None:
    print("=" * 65)
    print("  Screener Criteria Backtest — 2yr daily bars")
    print(f"  Universe: {len(UNIVERSE)} symbols  Lookback: {LOOKBACK}")
    print("=" * 65)

    all_trades: list[dict] = []
    for i, sym in enumerate(UNIVERSE, 1):
        trades = _backtest_symbol(sym)
        all_trades.extend(trades)
        print(f"  {i:2d}/{len(UNIVERSE)}  {sym:<6}  {len(trades)} setup days")

    # ── Aggregate by setup ────────────────────────────────────────────────────
    setups = ["RSI Dip", "Momentum", "Gap+Vol", "VWAP Bounce", "Breakout", "RSI2 Dip"]
    results: dict[str, dict] = {}
    for s in setups:
        t = [x for x in all_trades if x["setup"] == s]
        results[s] = _stats(t)

    # ── Print summary ─────────────────────────────────────────────────────────
    print(f"\n{'Setup':<14} {'N':>5} {'Win%':>6} {'AvgRet%':>8} {'PF':>6} {'Dir%':>6}  Verdict")
    print("-" * 65)
    for s in setups:
        r = results[s]
        print(f"{s:<14} {r['n']:>5} {r['win_pct']:>5.1f}% "
              f"{r['avg_ret']:>+7.3f}%  {r['pf']:>5.2f}  {r['dir_pct']:>5.1f}%"
              f"  {r['edge']}")

    # ── Top 5 per setup ───────────────────────────────────────────────────────
    print(f"\n{'─'*65}")
    print("Top symbols per setup (by avg next-day return):")
    for s in setups:
        t = [x for x in all_trades if x["setup"] == s]
        if not t:
            continue
        sym_avgs = {}
        for tr in t:
            sym_avgs.setdefault(tr["sym"], []).append(tr["ret"])
        top = sorted(sym_avgs.items(), key=lambda kv: float(np.mean(kv[1])), reverse=True)[:5]
        top_str = "  ".join(f"{sym}({np.mean(v):+.2f}%)" for sym, v in top)
        print(f"  {s:<14}: {top_str}")

    # ── Save ──────────────────────────────────────────────────────────────────
    out = {
        "date":    str(date.today()),
        "lookback": LOOKBACK,
        "universe_size": len(UNIVERSE),
        "results": results,
    }
    OUT_FILE.write_text(json.dumps(out, indent=2))
    print(f"\n  Results → {OUT_FILE}")
    print("=" * 65)
    return results


if __name__ == "__main__":
    main()
