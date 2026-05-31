#!/usr/bin/env python3.11
"""
backtest_connors_experiments.py — A/B tests on the FROZEN Connors RSI(2) baseline.

Does NOT modify backtest_connors_daily.py (the frozen, validated baseline).
Imports its exact helpers (_rsi, _atr, pnl, stats, portfolio_cap) so the math
is identical, then runs parameterized variants for two pre-specified hypotheses:

  EXP-1  MIN_ATR_PCT universe filter (live daily_trader has MIN_ATR_PCT=0.015,
         backtest never tested it). Entry also requires ATR14/close >= min_atr_pct.
         Question: does the 1.5% filter improve walk-forward Test PF vs no-filter?

  EXP-2  H-SEL-REGIME (KB §19 candidate, book-dig 2026-05-31). Connors
         (Short Selling w/ConnorsRSI p.26): stricter entry -> fewer, higher-
         expectancy trades. Attack the 2022 bear-year PF<1 weakness via:
           (a) broad-market regime gate: only go long when SPY > its own SMA200
           (b) tiered RSI strictness: require RSI(2) < strict_lo when broad
               market is risk-off, normal RSI(2) < 10 when risk-on
         Question: does regime-conditioned selectivity beat the frozen baseline
         OOS (higher Test PF and/or lower maxDD) without overfitting?

DISCIPLINE: every variant judged on the SAME 50/50 walk-forward split + the
SAME cost gate (Test PF >= 1.10 at BOTH 3 and 5 bp). A variant only "wins" if
it beats baseline OOS. Pre-specified; no parameter sweeping beyond the stated
hypotheses.

Usage:
  venv/bin/python3.11 scripts/backtest_connors_experiments.py
"""
from __future__ import annotations
import sys, warnings
from pathlib import Path
from datetime import datetime

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent))
import logging
logging.disable(logging.CRITICAL)

import numpy as np
import pandas as pd
from daily_data import fetch_daily
from universe import ALL

# Reuse the EXACT frozen baseline helpers — identical math, no divergence.
import backtest_connors_daily as base
from backtest_connors_daily import (
    _rsi, _atr, pnl, stats, portfolio_cap,
    SMA_WIN, RSI_N, RSI_LO, RSI_EXIT_BULL, ATR_WIN, ATR_STOP_M,
    TIME_CAP_DAYS, RISK_BUDGET, MAX_CONCURRENT,
)

OUT_DIR = Path(__file__).parent.parent / "backtest_results"
STRICT_LO = 5.0   # H-SEL-REGIME: stricter RSI entry when broad market is risk-off


# ── broad-market regime map (SPY close > SPY SMA200, by date) ─────────────────
def build_spy_regime() -> dict[str, bool]:
    """date_str -> True if SPY closed above its own 200-day SMA that day."""
    spy = fetch_daily("SPY")
    if spy is None or spy.empty:
        raise RuntimeError("SPY daily cache missing — cannot build regime gate")
    spy = spy.sort_values("date").reset_index(drop=True)
    spy["sma200"] = spy["close"].rolling(SMA_WIN).mean()
    out: dict[str, bool] = {}
    for _, r in spy.iterrows():
        if not np.isnan(r["sma200"]):
            out[str(r["date"].date())] = bool(r["close"] > r["sma200"])
    return out


# ── parameterized long-only generator (mirrors baseline gen exactly) ──────────
def gen_variant(symbol: str,
                min_atr_pct: float = 0.0,
                spy_regime: dict[str, bool] | None = None,
                tiered_rsi: bool = False) -> list[dict]:
    """Long-only Connors RSI(2), same exit walk as the frozen baseline.

    min_atr_pct : if > 0, require ATR14/close >= this at entry (EXP-1).
    spy_regime  : if provided, require SPY risk-on (SPY>SMA200) at entry (EXP-2a).
    tiered_rsi  : if True, use STRICT_LO when SPY risk-off else RSI_LO (EXP-2b).
                  (only meaningful alongside spy_regime; when risk-off AND not
                  tiered, the regime gate blocks the trade entirely.)
    """
    df = fetch_daily(symbol)
    if df is None or df.empty:
        return []
    df = df.sort_values("date").reset_index(drop=True)
    if len(df) < SMA_WIN + 10:
        return []

    df["sma200"] = df["close"].rolling(SMA_WIN).mean()
    df["rsi2"]   = _rsi(df["close"], RSI_N)
    df["atr14"]  = _atr(df["high"], df["low"], df["close"], ATR_WIN)

    trades: list[dict] = []
    n = len(df)

    for i in range(SMA_WIN, n - 2):
        sma   = df["sma200"].iloc[i]
        rsi   = df["rsi2"].iloc[i]
        atr   = df["atr14"].iloc[i]
        close = df["close"].iloc[i]
        if np.isnan(sma) or np.isnan(atr) or atr <= 0:
            continue

        # EXP-1: ATR% universe filter
        if min_atr_pct > 0 and (atr / close) < min_atr_pct:
            continue

        # EXP-2: broad-market regime gate + tiered RSI strictness
        rsi_lo = RSI_LO
        if spy_regime is not None:
            sig_date = str(df["date"].iloc[i].date())
            risk_on = spy_regime.get(sig_date)
            if risk_on is None:
                continue   # no SPY regime info → skip (conservative)
            if not risk_on:
                if tiered_rsi:
                    rsi_lo = STRICT_LO   # risk-off → demand a deeper oversold
                else:
                    continue             # risk-off → block (regime gate only)

        # --- entry (long only) ---
        if not (rsi < rsi_lo and close > sma):
            continue

        ei = i + 1
        if ei >= n:
            continue
        entry_open = df["open"].iloc[ei]
        entry_date = df["date"].iloc[ei]
        shares = max(1.0, RISK_BUDGET / (ATR_STOP_M * atr))
        stop_dist = ATR_STOP_M * atr

        # --- exit walk (identical to baseline) ---
        exit_price = None
        exit_why   = "eod"
        exit_date  = df["date"].iloc[-1]
        for j in range(ei + 1, min(ei + TIME_CAP_DAYS + 1, n)):
            prev_rsi = df["rsi2"].iloc[j - 1]
            j_open   = df["open"].iloc[j]
            if prev_rsi >= RSI_EXIT_BULL:
                exit_price, exit_why, exit_date = j_open, "mean_revert", df["date"].iloc[j]
                break
            day_low = df["low"].iloc[j]
            if (entry_open - day_low) >= stop_dist:
                exit_price = entry_open - stop_dist
                exit_why, exit_date = "atr_stop", df["date"].iloc[j]
                break
            if j == min(ei + TIME_CAP_DAYS, n - 1):
                exit_price, exit_why, exit_date = j_open, "time_cap", df["date"].iloc[j]
                break
        if exit_price is None:
            exit_price = float(df["close"].iloc[-1])
            exit_date  = df["date"].iloc[-1]
            exit_why   = "eod"

        trades.append({
            "sym": symbol, "date": str(entry_date.date()),
            "exit_date": str(exit_date.date()), "year": str(entry_date.year),
            "dir": "bull", "entry": float(entry_open), "exit": float(exit_price),
            "shares": shares, "sgn": 1.0, "why": exit_why,
        })
    return trades


# ── walk-forward evaluation for one variant ───────────────────────────────────
def evaluate(label: str, **gen_kwargs) -> dict:
    """Run a variant across the universe, apply the portfolio cap, split 50/50,
    return train/test PF at 3 and 5 bp + a per-year test breakdown."""
    all_tr: list[dict] = []
    for s in ALL:
        all_tr.extend(gen_variant(s, **gen_kwargs))
    capped = portfolio_cap(all_tr, MAX_CONCURRENT)

    if not capped:
        return {"label": label, "n": 0}

    dates = sorted({t["date"] for t in capped})
    split = dates[len(dates) // 2]
    train = [t for t in capped if t["date"] <  split]
    test  = [t for t in capped if t["date"] >= split]

    res = {
        "label": label, "n": len(capped), "split": split,
        "train_n": len(train), "test_n": len(test),
        "train_pf_3": stats(train, 3)["pf"], "train_pf_5": stats(train, 5)["pf"],
        "test_pf_3":  stats(test, 3)["pf"],  "test_pf_5":  stats(test, 5)["pf"],
        "test_win_3": stats(test, 3)["win"], "test_tot_3": stats(test, 3)["tot"],
    }
    # per-year TEST PF @3bp (the 2022 weakness lives here)
    by_year: dict[str, list[dict]] = {}
    for t in test:
        by_year.setdefault(t["year"], []).append(t)
    res["year_pf_3"] = {y: stats(ts, 3)["pf"] for y, ts in sorted(by_year.items())}
    return res


def _fmt(r: dict) -> str:
    if not r.get("n"):
        return f"  {r['label']:<28} — 0 trades"
    gate3 = "✅" if r["test_pf_3"] >= 1.10 else "⛔"
    gate5 = "✅" if r["test_pf_5"] >= 1.10 else "⛔"
    yrs = "  ".join(f"{y}:{pf}" for y, pf in r["year_pf_3"].items())
    return (f"  {r['label']:<28} n={r['n']:<5} "
            f"TrainPF {r['train_pf_3']}/{r['train_pf_5']}  "
            f"TestPF {r['test_pf_3']}{gate3}/{r['test_pf_5']}{gate5}  "
            f"win {r['test_win_3']}%  tot ${r['test_tot_3']:.0f}\n"
            f"  {'':<28} per-yr TestPF@3bp: {yrs}")


def main() -> None:
    print("Building SPY broad-market regime map…", flush=True)
    spy_regime = build_spy_regime()
    print(f"  SPY regime days: {len(spy_regime)}\n", flush=True)

    print("Running variants (this reuses the frozen baseline math)…\n", flush=True)
    variants = [
        ("baseline (frozen)",            dict()),
        ("EXP1 MIN_ATR_PCT=1.5%",        dict(min_atr_pct=0.015)),
        ("EXP1 MIN_ATR_PCT=1.0%",        dict(min_atr_pct=0.010)),
        ("EXP2a regime-gate (block)",    dict(spy_regime=spy_regime, tiered_rsi=False)),
        ("EXP2b regime+tiered RSI",      dict(spy_regime=spy_regime, tiered_rsi=True)),
        ("EXP1+2b combined",             dict(min_atr_pct=0.015, spy_regime=spy_regime, tiered_rsi=True)),
    ]
    results = []
    for label, kw in variants:
        r = evaluate(label, **kw)
        results.append(r)
        print(_fmt(r), flush=True)
        print(flush=True)

    # write report
    OUT_DIR.mkdir(exist_ok=True)
    lines = [
        f"# Connors RSI(2) — Experiment Sweep (MIN_ATR_PCT + H-SEL-REGIME)",
        f"_Run {datetime.now():%Y-%m-%d %H:%M}  ·  cost gate: Test PF ≥ 1.10 @ BOTH 3 & 5 bp OOS_",
        "",
        "| Variant | n | Train PF 3/5bp | Test PF 3bp | Test PF 5bp | Test win% | Test $ |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        if not r.get("n"):
            lines.append(f"| {r['label']} | 0 | — | — | — | — | — |")
            continue
        g3 = "✅" if r["test_pf_3"] >= 1.10 else "⛔"
        g5 = "✅" if r["test_pf_5"] >= 1.10 else "⛔"
        lines.append(
            f"| {r['label']} | {r['n']} | {r['train_pf_3']}/{r['train_pf_5']} | "
            f"{r['test_pf_3']} {g3} | {r['test_pf_5']} {g5} | {r['test_win_3']}% | "
            f"${r['test_tot_3']:.0f} |"
        )
    lines += ["", "## Per-year Test PF @3bp (the 2022 bear-year weakness)", ""]
    lines.append("| Variant | " + " | ".join(
        sorted({y for r in results if r.get("n") for y in r["year_pf_3"]})) + " |")
    yrs_all = sorted({y for r in results if r.get("n") for y in r["year_pf_3"]})
    lines.append("|---|" + "|".join("---" for _ in yrs_all) + "|")
    for r in results:
        if not r.get("n"):
            continue
        row = " | ".join(str(r["year_pf_3"].get(y, "—")) for y in yrs_all)
        lines.append(f"| {r['label']} | {row} |")

    fn = OUT_DIR / f"connors_experiments_{datetime.now():%Y-%m-%d}.md"
    fn.write_text("\n".join(lines) + "\n")
    print(f"✓ Report → {fn}")


if __name__ == "__main__":
    main()
