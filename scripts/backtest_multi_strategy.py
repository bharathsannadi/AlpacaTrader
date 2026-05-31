#!/usr/bin/env python3.11
"""
backtest_multi_strategy.py — KB-grounded multi-strategy daily backtest.

Goal: fix the "single regime-dependent strategy = fragile foundation" risk the
RIGHT way — not by *adding* unvalidated strategies, but by testing several
PRE-SPECIFIED, knowledge-base-sourced daily strategies through the SAME
cost-robust gate used for Connors, and keeping only what passes. The valuable
addition is a strategy UNCORRELATED with Connors (a trend/momentum strategy that
profits when mean-reversion fails — i.e. survives 2022).

Discipline (non-negotiable, same as every prior test):
  • PRE-SPECIFIED rules per strategy, each citing its KB source. No sweeping.
  • Walk-forward 50/50 split; cost gate = Test PF ≥ 1.10 at BOTH 3 bp AND 5 bp OOS.
  • Honest about multiple-comparisons risk: testing N strategies and keeping
    winners inflates false positives → survivors go to PAPER INCUBATION, not live.
  • Correlation of strategy P&L is reported — a diversifier must be LOW-correlated
    with Connors to actually reduce portfolio fragility.

Strategies (all long-only, daily bars, $200 risk / 2×ATR sizing for apples-to-apples):
  S1 Connors RSI(2)      — mean reversion in uptrend         (KB §19)
  S2 Bollinger reversion — close < lower BB(20,2), >SMA200   (KB §1 Bollinger / mean-rev)
  S3 SMA trend pullback  — dip-and-reclaim in 50>200 uptrend (KB §8 Gunn/Covel, §14 Schwager)
  S4 52w-high breakout   — new 252-day high momentum         (KB §15 O'Neil/Minervini breakout)

Usage:
  venv/bin/python3.11 scripts/backtest_multi_strategy.py
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
from universe import ALL
from backtest_connors_daily import (
    _rsi, _atr, pnl, stats, portfolio_cap,
    SMA_WIN, RSI_N, RSI_LO, RSI_EXIT_BULL, ATR_WIN, ATR_STOP_M,
    RISK_BUDGET, MAX_CONCURRENT,
)

OUT_DIR = Path(__file__).parent.parent / "backtest_results"


# ── generic trade builder (shared exit engine) ────────────────────────────────
def _mk_trade(sym, df, ei, exit_idx, why, atr) -> dict:
    entry_open = float(df["open"].iloc[ei])
    # Exit-price model matches the FROZEN Connors baseline for comparability:
    #   atr_stop  → fill AT the stop level (entry − 2×ATR), not the next open
    #   signal/time_cap → next-day open · eod → last close
    if why == "atr_stop":
        exit_price = entry_open - ATR_STOP_M * atr
    elif why == "eod":
        exit_price = float(df["close"].iloc[-1])
    else:
        exit_price = float(df["open"].iloc[exit_idx])
    return {
        "sym": sym, "date": str(df["date"].iloc[ei].date()),
        "exit_date": str(df["date"].iloc[exit_idx].date()),
        "year": str(df["date"].iloc[ei].year), "dir": "bull",
        "entry": entry_open, "exit": exit_price,
        "shares": max(1.0, RISK_BUDGET / (ATR_STOP_M * atr)), "sgn": 1.0, "why": why,
    }


def _prep(symbol: str):
    df = fetch_daily(symbol)
    if df is None or df.empty:
        return None
    df = df.sort_values("date").reset_index(drop=True)
    if len(df) < SMA_WIN + 60:
        return None
    df["sma200"] = df["close"].rolling(SMA_WIN).mean()
    df["sma50"]  = df["close"].rolling(50).mean()
    df["sma20"]  = df["close"].rolling(20).mean()
    df["std20"]  = df["close"].rolling(20).std()
    df["rsi2"]   = _rsi(df["close"], RSI_N)
    df["atr14"]  = _atr(df["high"], df["low"], df["close"], ATR_WIN)
    df["hi252"]  = df["high"].rolling(252).max()
    return df


def _exit_walk(df, ei, atr, signal_exit, max_hold):
    """Walk forward from entry: signal_exit(row_prev) | 2×ATR stop | time cap."""
    n = len(df)
    entry_open = df["open"].iloc[ei]
    stop_dist = ATR_STOP_M * atr
    for j in range(ei + 1, min(ei + max_hold + 1, n)):
        prev = df.iloc[j - 1]
        if signal_exit(prev):
            return j, "signal"
        if (entry_open - df["low"].iloc[j]) >= stop_dist:
            return j, "atr_stop"
        if j == min(ei + max_hold, n - 1):
            return j, "time_cap"
    return n - 1, "eod"


# ── strategies: each returns list[trades] for one symbol ──────────────────────
def gen_connors(sym):                                   # S1 — KB §19
    df = _prep(sym)
    if df is None: return []
    out, n = [], len(df)
    for i in range(SMA_WIN, n - 2):
        r = df.iloc[i]
        if np.isnan(r.sma200) or np.isnan(r.atr14) or r.atr14 <= 0: continue
        if not (r.rsi2 < RSI_LO and r.close > r.sma200): continue
        ei = i + 1
        xi, why = _exit_walk(df, ei, r.atr14,
                             lambda p: p.rsi2 >= RSI_EXIT_BULL, 10)
        out.append(_mk_trade(sym, df, ei, xi, why, r.atr14))
    return out


def gen_bollinger(sym):                                 # S2 — KB §1 Bollinger / mean-rev
    df = _prep(sym)
    if df is None: return []
    out, n = [], len(df)
    for i in range(SMA_WIN, n - 2):
        r = df.iloc[i]
        if np.isnan(r.sma200) or np.isnan(r.std20) or np.isnan(r.atr14) or r.atr14 <= 0: continue
        lower = r.sma20 - 2 * r.std20
        if not (r.close < lower and r.close > r.sma200): continue
        ei = i + 1
        xi, why = _exit_walk(df, ei, r.atr14,
                             lambda p: p.close >= p.sma20, 10)   # exit at middle band
        out.append(_mk_trade(sym, df, ei, xi, why, r.atr14))
    return out


def gen_trend_pullback(sym):                            # S3 — KB §8/§14 trend
    df = _prep(sym)
    if df is None: return []
    out, n = [], len(df)
    for i in range(SMA_WIN, n - 2):
        r, p = df.iloc[i], df.iloc[i - 1]
        if np.isnan(r.sma50) or np.isnan(r.sma200) or np.isnan(r.atr14) or r.atr14 <= 0: continue
        uptrend = r.close > r.sma50 > r.sma200
        reclaim = (p.close < p.sma20) and (r.close > r.sma20)   # dip then reclaim
        if not (uptrend and reclaim): continue
        ei = i + 1
        xi, why = _exit_walk(df, ei, r.atr14,
                             lambda q: q.close < q.sma50, 20)    # exit on trend break
        out.append(_mk_trade(sym, df, ei, xi, why, r.atr14))
    return out


def gen_breakout(sym):                                  # S4 — KB §15 O'Neil/Minervini
    df = _prep(sym)
    if df is None: return []
    out, n = [], len(df)
    last_exit = -1
    for i in range(SMA_WIN, n - 2):
        if i <= last_exit: continue
        r, p = df.iloc[i], df.iloc[i - 1]
        if np.isnan(r.hi252) or np.isnan(r.sma200) or np.isnan(r.atr14) or r.atr14 <= 0: continue
        new_high = r.close >= df["hi252"].iloc[i - 1]           # closes at/above prior 252d high
        if not (new_high and r.close > r.sma200): continue
        ei = i + 1
        xi, why = _exit_walk(df, ei, r.atr14,
                             lambda q: q.close < q.sma50, 40)    # let momentum run
        out.append(_mk_trade(sym, df, ei, xi, why, r.atr14))
        last_exit = xi
    return out


STRATS = {
    "S1 Connors RSI2 (MR §19)":     gen_connors,
    "S2 Bollinger rev (MR §1)":     gen_bollinger,
    "S3 Trend pullback (§8/§14)":   gen_trend_pullback,
    "S4 52w breakout (§15)":        gen_breakout,
}


def evaluate(gen):
    all_tr = []
    for s in ALL:
        all_tr.extend(gen(s))
    capped = portfolio_cap(all_tr, MAX_CONCURRENT)
    if not capped:
        return None
    dates = sorted({t["date"] for t in capped})
    split = dates[len(dates) // 2]
    train = [t for t in capped if t["date"] < split]
    test  = [t for t in capped if t["date"] >= split]
    by_year = defaultdict(list)
    for t in test:
        by_year[t["year"]].append(t)
    # full-sample per-year (so 2022 shows even if in train half)
    fy = defaultdict(list)
    for t in capped:
        fy[t["year"]].append(t)
    return {
        "n": len(capped), "test_n": len(test), "split": split,
        "train_pf3": stats(train, 3)["pf"],
        "test_pf3": stats(test, 3)["pf"], "test_pf5": stats(test, 5)["pf"],
        "test_win": stats(test, 3)["win"], "test_tot": stats(test, 3)["tot"],
        "year_pf3": {y: stats(ts, 3)["pf"] for y, ts in sorted(fy.items())},
        "capped": capped,
    }


def monthly_series(trades) -> pd.Series:
    """Monthly realized P&L (@3bp) keyed by YYYY-MM of exit date — for correlation."""
    m = defaultdict(float)
    for t in trades:
        m[t["exit_date"][:7]] += pnl(t, 3)
    return pd.Series(m).sort_index()


def main():
    print("KB-grounded multi-strategy daily backtest (cost gate: Test PF ≥ 1.10 @ 3 & 5 bp OOS)\n", flush=True)
    results = {}
    for name, gen in STRATS.items():
        r = evaluate(gen)
        results[name] = r
        if not r:
            print(f"  {name:<30} 0 trades"); continue
        g3 = "✅" if r["test_pf3"] >= 1.10 else "⛔"
        g5 = "✅" if r["test_pf5"] >= 1.10 else "⛔"
        yrs = " ".join(f"{y}:{pf}" for y, pf in r["year_pf3"].items())
        print(f"  {name:<30} n={r['n']:<5} TrainPF {r['train_pf3']}  "
              f"TestPF {r['test_pf3']}{g3}/{r['test_pf5']}{g5}  win {r['test_win']}%  ${r['test_tot']:.0f}")
        print(f"  {'':<30} full per-yr PF@3bp: {yrs}\n", flush=True)

    # ── correlation matrix of monthly P&L (diversification) ──
    series = {n: monthly_series(r["capped"]) for n, r in results.items() if r}
    if len(series) >= 2:
        df = pd.DataFrame(series).fillna(0.0)
        corr = df.corr().round(2)
        print("Monthly-P&L correlation (low vs Connors = real diversifier):")
        print(corr.to_string(), flush=True)

    # ── report ──
    OUT_DIR.mkdir(exist_ok=True)
    lines = [f"# KB Multi-Strategy Backtest — {datetime.now():%Y-%m-%d %H:%M}",
             "_Cost gate: Test PF ≥ 1.10 at BOTH 3 & 5 bp, OOS 50/50 walk-forward. "
             "Survivors → paper incubation, NOT live (multiple-comparisons caveat)._", "",
             "| Strategy | n | Train PF | Test PF 3bp | Test PF 5bp | Win% | 2022 PF | Verdict |",
             "|---|---|---|---|---|---|---|---|"]
    for name, r in results.items():
        if not r:
            lines.append(f"| {name} | 0 | — | — | — | — | — | no trades |"); continue
        passed = r["test_pf3"] >= 1.10 and r["test_pf5"] >= 1.10
        lines.append(f"| {name} | {r['n']} | {r['train_pf3']} | {r['test_pf3']} | "
                     f"{r['test_pf5']} | {r['test_win']}% | {r['year_pf3'].get('2022','—')} | "
                     f"{'✅ PASS → incubate' if passed else '⛔ FAIL'} |")
    if len(series) >= 2:
        lines += ["", "## Monthly-P&L correlation", "", "```",
                  pd.DataFrame(series).fillna(0.0).corr().round(2).to_string(), "```"]
    fn = OUT_DIR / f"multi_strategy_{datetime.now():%Y-%m-%d}.md"
    fn.write_text("\n".join(lines) + "\n")
    print(f"\n✓ Report → {fn}")


if __name__ == "__main__":
    main()
