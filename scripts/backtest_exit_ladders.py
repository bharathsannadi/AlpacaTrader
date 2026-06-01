#!/usr/bin/env python3.11
"""
backtest_exit_ladders.py — does dynamic profit-protection (REQ-608) beat the
fixed-stop baseline? (Phase 3)

For each of the 4 validated strategies we take the SAME entries and re-simulate
exits under different exit engines:
  • baseline   — current fixed exit (signal exit | 2×ATR stop | time cap)
  • ladder cfgs — escalating profit FLOOR: once gain ≥ tier, ratchet the stop up
                  (breakeven, then a locked floor) + trail off the high-water mark.
                  Monotonic (floor only rises). Loss side keeps the 2×ATR backstop.

Honest question (REQ-608.4 / 603.3): does protecting profits improve OOS
PF / expectancy / max-DD, or does whipsaw (stopped on noise, miss the recovery)
eat it? Same 50/50 walk-forward + cost gate. Pre-specified small config set
(multiple-comparisons aware); survivors → incubation, not live.

Usage: venv/bin/python3.11 scripts/backtest_exit_ladders.py
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
from daily_data import fetch_daily
from universe import ALL
from backtest_connors_daily import (_rsi, _atr, pnl, stats, portfolio_cap,
                                    SMA_WIN, RSI_N, RSI_LO, RSI_EXIT_BULL,
                                    ATR_WIN, ATR_STOP_M, RISK_BUDGET, MAX_CONCURRENT)
from backtest_multi_strategy import _prep

OUT_DIR = Path(__file__).parent.parent / "backtest_results"


# ── entry generators: yield (df, ei, atr, signal_exit, max_hold) per strategy ──
def entries_connors(df):
    n = len(df)
    for i in range(SMA_WIN, n - 2):
        r = df.iloc[i]
        if np.isnan(r.sma200) or np.isnan(r.atr14) or r.atr14 <= 0: continue
        if r.rsi2 < RSI_LO and r.close > r.sma200:
            yield i + 1, r.atr14, (lambda p: p.rsi2 >= RSI_EXIT_BULL), 10

def entries_trend(df):
    n = len(df)
    for i in range(SMA_WIN, n - 2):
        r, p = df.iloc[i], df.iloc[i - 1]
        if np.isnan(r.sma50) or np.isnan(r.sma200) or np.isnan(r.atr14) or r.atr14 <= 0: continue
        if (r.close > r.sma50 > r.sma200) and (p.close < p.sma20) and (r.close > r.sma20):
            yield i + 1, r.atr14, (lambda q: q.close < q.sma50), 20

def entries_breakout(df):
    n = len(df); last = -1
    for i in range(SMA_WIN, n - 2):
        if i <= last: continue
        r = df.iloc[i]
        if np.isnan(r.hi252) or np.isnan(r.sma200) or np.isnan(r.atr14) or r.atr14 <= 0: continue
        if r.close >= df["hi252"].iloc[i - 1] and r.close > r.sma200:
            last = i + 25
            yield i + 1, r.atr14, (lambda q: q.close < q.sma50), 40

STRATS = {"connors": entries_connors, "trend": entries_trend, "breakout": entries_breakout}


# ── exit engines ──────────────────────────────────────────────────────────────
def _trade(df, ei, exit_idx, exit_price, why, atr, sym):
    eo = float(df["open"].iloc[ei])
    return {"sym": sym, "date": str(df["date"].iloc[ei].date()),
            "exit_date": str(df["date"].iloc[exit_idx].date()),
            "year": str(df["date"].iloc[ei].year), "dir": "bull",
            "entry": eo, "exit": float(exit_price),
            "shares": max(1.0, RISK_BUDGET / (ATR_STOP_M * atr)), "sgn": 1.0, "why": why}


def simulate(df, ei, atr, signal_exit, max_hold, ladder, sym):
    """ladder=None → fixed baseline. else dict(tier1, floor2_gain, floor2_lock, trail)."""
    n = len(df); eo = df["open"].iloc[ei]
    stop = eo - ATR_STOP_M * atr
    hwm = eo
    for j in range(ei + 1, min(ei + max_hold + 1, n)):
        hi, lo, op = df["high"].iloc[j], df["low"].iloc[j], df["open"].iloc[j]
        prev = df.iloc[j - 1]
        hwm = max(hwm, hi)
        if ladder:
            gain = (hwm - eo) / eo
            if gain >= ladder["tier1"]:                       # breakeven + trail
                stop = max(stop, eo, hwm * (1 - ladder["trail"]))
            if gain >= ladder["floor2_gain"]:                 # lock a higher floor
                stop = max(stop, eo * (1 + ladder["floor2_lock"]))
        # exit priority: signal (prior close) → stop (intraday low) → time cap
        if signal_exit(prev):
            return _trade(df, ei, j, op, "signal", atr, sym)
        if lo <= stop:
            return _trade(df, ei, j, stop, "stop", atr, sym)
        if j == min(ei + max_hold, n - 1):
            return _trade(df, ei, j, op, "time_cap", atr, sym)
    return _trade(df, ei, n - 1, df["close"].iloc[-1], "eod", atr, sym)


def run(strat_entries, ladder):
    trades = []
    for sym in ALL:
        df = _prep(sym)
        if df is None: continue
        for ei, atr, sx, mh in strat_entries(df):
            trades.append(simulate(df, ei, atr, sx, mh, ladder, sym))
    capped = portfolio_cap(trades, MAX_CONCURRENT)
    if not capped: return None
    dates = sorted({t["date"] for t in capped}); split = dates[len(dates)//2]
    test = [t for t in capped if t["date"] >= split]
    # max drawdown on test cumulative P&L @3bp
    ps = [pnl(t, 3) for t in sorted(test, key=lambda x: x["date"])]
    cum = np.cumsum(ps); peak = np.maximum.accumulate(np.concatenate([[0], cum]))[1:]
    dd = float((peak - cum).max()) if len(cum) else 0.0
    return {"n": len(capped), "test_pf3": stats(test, 3)["pf"], "test_pf5": stats(test, 5)["pf"],
            "win": stats(test, 3)["win"], "tot": stats(test, 3)["tot"], "maxdd": round(dd, 0)}


# pre-specified ladder configs (operator intent: protect profits) — small set
LADDERS = {
    "baseline":        None,
    "L1 be+trail30":   {"tier1": 0.05, "trail": 0.30, "floor2_gain": 0.20, "floor2_lock": 0.10},
    "L2 be8+trail40":  {"tier1": 0.08, "trail": 0.40, "floor2_gain": 0.30, "floor2_lock": 0.15},
    "L3 be10+trail50": {"tier1": 0.10, "trail": 0.50, "floor2_gain": 0.50, "floor2_lock": 0.25},
}


def main():
    print("Exit-ladder backtest — does profit-protection beat fixed baseline OOS?\n", flush=True)
    report = ["# Exit-Ladder Backtest (REQ-608) — " + datetime.now().strftime("%Y-%m-%d %H:%M"),
              "_Same entries, different exits. Cost gate Test PF ≥ 1.10 @ 3 & 5 bp OOS._", ""]
    for strat, gen in STRATS.items():
        print(f"=== {strat} ===", flush=True)
        report += [f"## {strat}", "", "| exit | n | TestPF 3/5bp | win% | test $ | maxDD $ |",
                   "|---|---|---|---|---|---|"]
        base = None
        for name, cfg in LADDERS.items():
            r = run(gen, cfg)
            if not r:
                print(f"  {name:18} 0 trades"); continue
            if name == "baseline": base = r
            delta = "" if name == "baseline" or not base else \
                f"  (Δtot {r['tot']-base['tot']:+.0f}, ΔDD {r['maxdd']-base['maxdd']:+.0f})"
            g = "✅" if r["test_pf3"] >= 1.10 and r["test_pf5"] >= 1.10 else "⛔"
            print(f"  {name:18} n={r['n']:<4} PF {r['test_pf3']}/{r['test_pf5']}{g} "
                  f"win {r['win']}% tot ${r['tot']:.0f} maxDD ${r['maxdd']:.0f}{delta}", flush=True)
            report.append(f"| {name} | {r['n']} | {r['test_pf3']}/{r['test_pf5']} {g} | "
                          f"{r['win']}% | ${r['tot']:.0f} | ${r['maxdd']:.0f} |")
        report.append("")
        print(flush=True)
    fn = OUT_DIR / f"exit_ladders_{datetime.now():%Y-%m-%d}.md"
    OUT_DIR.mkdir(exist_ok=True); fn.write_text("\n".join(report) + "\n")
    print(f"✓ Report → {fn}")


if __name__ == "__main__":
    main()
