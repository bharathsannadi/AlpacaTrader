#!/usr/bin/env python3.11
"""
backtest_regime_overlay.py — does a regime overlay + non-equity sleeve fix the
2022 tail risk? (Phase 4, REQ-205/611.2)

The 4 validated strategies are ALL long-only equity, so they all crater together
in a broad bear (2022 PF 0.85/0.62/0.68/0.03). Diversifying across long-equity
strategies fixes signal risk, NOT market-beta/tail risk. The real fix needs a
component that ISN'T long equity beta. We test:

  A baseline       — combined 4-strategy portfolio, full size always
  B regime-skip    — skip new entries when SPY < its 200-SMA (risk-off)
  C regime-half    — half size when risk-off
  D TLT sleeve     — when risk-off, hold TLT (bonds) instead of equity (rotation)

Metric that matters: 2022 P&L and MAX DRAWDOWN (the tail), not just PF.

Usage: venv/bin/python3.11 scripts/backtest_regime_overlay.py
"""
from __future__ import annotations
import sys, warnings
from pathlib import Path
from datetime import datetime
from collections import defaultdict

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent))
import logging; logging.disable(logging.CRITICAL)

import numpy as np
import pandas as pd
from daily_data import fetch_daily
from backtest_connors_daily import pnl, stats, portfolio_cap, SMA_WIN, ATR_STOP_M, RISK_BUDGET, MAX_CONCURRENT
from backtest_multi_strategy import (gen_connors, gen_bollinger,
                                    gen_trend_pullback, gen_breakout, _prep)

OUT_DIR = Path(__file__).parent.parent / "backtest_results"
STRATS = [gen_connors, gen_bollinger, gen_trend_pullback, gen_breakout]


def spy_regime() -> dict[str, bool]:
    spy = fetch_daily("SPY").sort_values("date").reset_index(drop=True)
    spy["sma200"] = spy["close"].rolling(SMA_WIN).mean()
    return {str(r["date"].date()): bool(r["close"] > r["sma200"])
            for _, r in spy.iterrows() if not np.isnan(r["sma200"])}


def combined_trades() -> list[dict]:
    tr = []
    for gen in STRATS:
        for sym in __import__("universe").ALL:
            tr.extend(gen(sym))
    return portfolio_cap(tr, MAX_CONCURRENT)


def tlt_sleeve_trades(regime: dict[str, bool]) -> list[dict]:
    """Hold TLT while SPY is risk-off: enter when regime flips off, exit when on."""
    df = _prep("TLT")
    if df is None:
        return []
    df = df.sort_values("date").reset_index(drop=True)
    out, in_pos, ei = [], False, None
    for i in range(SMA_WIN, len(df) - 1):
        d = str(df["date"].iloc[i].date())
        ro = regime.get(d, True) is False    # risk-off
        if ro and not in_pos:
            in_pos, ei = True, i + 1
        elif not ro and in_pos:
            xi = i + 1
            atr = df["atr14"].iloc[ei] if "atr14" in df else 1.0
            out.append({"sym": "TLT", "date": str(df["date"].iloc[ei].date()),
                        "exit_date": str(df["date"].iloc[xi].date()),
                        "year": str(df["date"].iloc[ei].year), "dir": "bull",
                        "entry": float(df["open"].iloc[ei]), "exit": float(df["open"].iloc[xi]),
                        "shares": max(1.0, RISK_BUDGET / (ATR_STOP_M * max(atr, 0.1))),
                        "sgn": 1.0, "why": "regime_on"})
            in_pos = False
    return out


def maxdd(trades, slip=3):
    ps = [pnl(t, slip) for t in sorted(trades, key=lambda x: x["date"])]
    cum = np.cumsum(ps); peak = np.maximum.accumulate(np.concatenate([[0], cum]))[1:]
    return float((peak - cum).max()) if len(cum) else 0.0


def summarize(trades, label):
    by_year = defaultdict(list)
    for t in trades:
        by_year[t["year"]].append(t)
    s = stats(trades, 3)
    return {"label": label, "n": s["n"], "pf": s["pf"], "tot": s["tot"],
            "maxdd": round(maxdd(trades), 0),
            "y2022": stats(by_year.get("2022", []), 3)["pf"],
            "y2022_tot": round(stats(by_year.get("2022", []), 3)["tot"], 0)}


def apply_overlay(base, regime, mode):
    out = []
    for t in base:
        ro = regime.get(t["date"], True) is False
        if mode == "skip" and ro:
            continue
        if mode == "half" and ro:
            t = dict(t); t["shares"] = t["shares"] * 0.5
        out.append(t)
    return out


def main():
    print("Regime/hedge overlay — does it cut the 2022 tail? (Phase 4)\n", flush=True)
    reg = spy_regime()
    base = combined_trades()
    variants = [
        summarize(base, "A baseline (long-equity only)"),
        summarize(apply_overlay(base, reg, "skip"), "B regime-skip (no risk-off entries)"),
        summarize(apply_overlay(base, reg, "half"), "C regime-half (half size risk-off)"),
        summarize(base + tlt_sleeve_trades(reg), "D + TLT sleeve (bonds when risk-off)"),
    ]
    hdr = f"{'variant':<38} {'n':>5} {'PF':>5} {'total$':>9} {'maxDD$':>8} {'2022PF':>7} {'2022$':>8}"
    print(hdr); print("-" * len(hdr))
    for v in variants:
        print(f"{v['label']:<38} {v['n']:>5} {v['pf']:>5} {v['tot']:>9.0f} "
              f"{v['maxdd']:>8.0f} {v['y2022']:>7} {v['y2022_tot']:>8.0f}", flush=True)

    OUT_DIR.mkdir(exist_ok=True)
    lines = [f"# Regime/Hedge Overlay Backtest — {datetime.now():%Y-%m-%d %H:%M}",
             "_Combined 4-strategy portfolio. Metric that matters: 2022 + max drawdown._", "",
             "| variant | n | PF | total$ | maxDD$ | 2022 PF | 2022 $ |",
             "|---|---|---|---|---|---|---|"]
    for v in variants:
        lines.append(f"| {v['label']} | {v['n']} | {v['pf']} | {v['tot']:.0f} | "
                     f"{v['maxdd']:.0f} | {v['y2022']} | {v['y2022_tot']:.0f} |")
    fn = OUT_DIR / f"regime_overlay_{datetime.now():%Y-%m-%d}.md"
    fn.write_text("\n".join(lines) + "\n")
    print(f"\n✓ Report → {fn}")


if __name__ == "__main__":
    main()
