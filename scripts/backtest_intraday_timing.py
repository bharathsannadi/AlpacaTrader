#!/usr/bin/env python3.11
"""
backtest_intraday_timing.py — Intraday timing analysis using 5yr Polygon data.

For each validated screener setup signal (Breakout, Bull Flag, RSI Dip, Gap+Vol):
  1. Classify signal days from 5yr daily bars
  2. Load 1-min Polygon bars for the NEXT trading day
  3. Simulate entry at 9:35 ET (skip the open 5-min volatility spike)
  4. Measure returns at: 15, 30, 60, 90, 120, 180 min and EOD (15:55)
  5. Simulate stop-loss / profit-target exit rules
  6. Find optimal hold period + stop/target for each setup

Key questions answered:
  - "RSI Dip: hold 60 min or all day?"
  - "Breakout: take profits at 30 min or let it run?"
  - "What stop % minimises drawdown without choking winners?"

Output:
  - AlpacaTrader_Data/intraday_timing_results.json
  - Console summary tables

Requires: polygon_cache.py to have been run first (or run automatically).

Usage:
  venv/bin/python3.11 scripts/backtest_intraday_timing.py
  venv/bin/python3.11 scripts/backtest_intraday_timing.py --download  # fetch cache first
"""
from __future__ import annotations
import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import warnings
warnings.filterwarnings("ignore")

# ── Add scripts dir to path ────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))
import polygon_cache as pcache

OUT_DIR  = Path.home() / "Desktop" / "bharath" / "AlpacaTrader_Data"
OUT_FILE = OUT_DIR / "intraday_timing_results.json"

UNIVERSE = pcache.UNIVERSE   # 50 symbols (UNIVERSE_1 + UNIVERSE_2)

VALID_SETUPS  = ["Breakout", "Bull Flag", "RSI Dip", "Gap+Vol"]
HOLD_MINUTES  = [15, 30, 60, 90, 120, 180, "EOD"]  # EOD = 15:55 bar
STOPS         = [0.5, 1.0, 1.5, 2.0]    # % stop loss below entry
TARGETS       = [1.0, 1.5, 2.0, 3.0]   # % profit target above entry
ENTRY_DELAY   = 5                        # minutes after open (enter at 9:35)

# ── Daily indicator helpers (same formulae as screener backtest) ───────────────
def _rsi(s: pd.Series, n: int) -> pd.Series:
    d = s.diff()
    g = d.clip(lower=0).rolling(n).mean()
    l = (-d).clip(lower=0).rolling(n).mean()
    rs = g / l.replace(0, np.nan)
    return 100 - 100 / (1 + rs)

def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def classify_daily_signals(df_daily: pd.DataFrame) -> pd.DataFrame:
    """
    Classify each daily bar into a setup type using EOD indicators.
    Returns DataFrame with 'setup' column, trimmed to valid signal rows.
    Signal on day N → trade entry on day N+1.
    """
    df = df_daily.copy()
    df = df.sort_values("ts").reset_index(drop=True)

    # Ensure we have a date column
    df["date"] = pd.to_datetime(df["ts"]).dt.date

    rsi14   = _rsi(df["close"], 14)
    rsi2    = _rsi(df["close"], 2)
    ema20   = _ema(df["close"], 20)
    ema9    = _ema(df["close"], 9)
    high50  = df["close"].rolling(50).max().shift(1)
    gap     = (df["open"] - df["close"].shift(1)) / df["close"].shift(1) * 100
    vol_avg = df["volume"].rolling(30).mean().shift(1)
    rel_vol = df["volume"] / vol_avg.replace(0, np.nan)
    chg     = (df["close"] - df["open"]) / df["open"] * 100

    setup = pd.Series("Neutral", index=df.index)

    # Breakout
    mask = (df["close"] > high50) & (rsi14 > 55) & (rsi14 < 75) & (rel_vol > 1.3)
    setup[mask] = "Breakout"

    # Gap+Vol (Aziz p.31)
    mask = (gap > 1.0) & (rel_vol > 1.5)
    setup[mask] = "Gap+Vol"

    # RSI Dip
    mask = rsi14 < 35
    setup[mask] = "RSI Dip"

    # Bull Flag
    prior_chg  = chg.shift(1)
    prior_chg2 = chg.shift(2)
    surge_any  = (prior_chg > 2.0) | (prior_chg2 > 2.0)
    prior_range = (df["high"].shift(1) - df["low"].shift(1)).replace(0, np.nan)
    today_range = df["high"] - df["low"]
    tight_flag  = today_range < 0.5 * prior_range
    flagpole    = (df["close"].shift(1) - df["low"].shift(1)) / prior_range
    strong_up   = flagpole > 0.6
    mask = surge_any & tight_flag & strong_up & (rsi14 >= 50) & (rsi14 <= 75) & (rel_vol >= 1.2)
    # Bull Flag only if not already a higher-priority setup
    bull_flag_mask = mask & ~setup.isin(["Breakout", "Gap+Vol", "RSI Dip"])
    setup[bull_flag_mask] = "Bull Flag"

    df["setup"]   = setup
    df["rsi14"]   = rsi14
    df["rel_vol"] = rel_vol

    # Only return valid signal rows (warm-up 55 bars)
    df = df.iloc[55:].copy()
    df = df[df["setup"].isin(VALID_SETUPS)].copy()
    df["entry_date"] = pd.to_datetime(df["date"]) + pd.tseries.offsets.BDay(1)
    df["entry_date"] = df["entry_date"].dt.date
    return df[["date", "entry_date", "setup", "close", "rsi14", "rel_vol"]].copy()


# ── Intraday trade simulation ──────────────────────────────────────────────────
def simulate_hold(entry_price: float, bars_after_entry: pd.DataFrame,
                  hold_minutes) -> float | None:
    """
    Returns % return for a fixed hold period (no stop/target).
    hold_minutes: int (minutes to hold) or "EOD" (last bar of day)
    """
    if bars_after_entry.empty:
        return None
    if hold_minutes == "EOD":
        exit_bar = bars_after_entry.iloc[-1]
    else:
        idx = min(hold_minutes, len(bars_after_entry) - 1)
        exit_bar = bars_after_entry.iloc[idx]
    return (float(exit_bar["close"]) - entry_price) / entry_price * 100


def simulate_stop_target(entry_price: float, bars_after_entry: pd.DataFrame,
                         stop_pct: float, target_pct: float,
                         max_hold_minutes) -> dict:
    """
    Walk bars bar-by-bar from entry. Stop on first bar that hits stop or target,
    else exit at max_hold_minutes (or EOD).
    Returns {'ret': float, 'exit': 'stop'|'target'|'time'}
    """
    if bars_after_entry.empty:
        return {"ret": None, "exit": "no_data"}

    stop_price   = entry_price * (1 - stop_pct / 100)
    target_price = entry_price * (1 + target_pct / 100)
    max_idx      = (len(bars_after_entry) - 1
                    if max_hold_minutes == "EOD"
                    else min(max_hold_minutes, len(bars_after_entry) - 1))

    for i, (_, bar) in enumerate(bars_after_entry.head(max_idx + 1).iterrows()):
        # Check stop (low touched stop)
        if float(bar["low"]) <= stop_price:
            return {"ret": (stop_price - entry_price) / entry_price * 100, "exit": "stop"}
        # Check target (high touched target)
        if float(bar["high"]) >= target_price:
            return {"ret": (target_price - entry_price) / entry_price * 100, "exit": "target"}
        # Time exit on last allowed bar
        if i == max_idx:
            return {"ret": (float(bar["close"]) - entry_price) / entry_price * 100, "exit": "time"}

    # Fallback
    last = bars_after_entry.iloc[-1]
    return {"ret": (float(last["close"]) - entry_price) / entry_price * 100, "exit": "time"}


# ── Stats helper ───────────────────────────────────────────────────────────────
def _stats(rets: list[float]) -> dict:
    if not rets:
        return {"n": 0, "win_pct": 0, "avg_ret": 0, "pf": 0, "median": 0}
    wins = [r for r in rets if r > 0]
    loss = [r for r in rets if r <= 0]
    pf   = (sum(wins) / abs(sum(loss))) if loss and sum(loss) != 0 else float("inf")
    return {
        "n":       len(rets),
        "win_pct": round(len(wins) / len(rets) * 100, 1),
        "avg_ret": round(float(np.mean(rets)), 3),
        "median":  round(float(np.median(rets)), 3),
        "pf":      round(pf, 2),
    }


# ── Main backtest ──────────────────────────────────────────────────────────────
def run_backtest() -> dict:
    print("=" * 70)
    print("  Intraday Timing Backtest — Polygon 5yr 1-min data")
    print(f"  Universe: {len(UNIVERSE)} symbols  |  Setups: {VALID_SETUPS}")
    print(f"  Entry: 9:35 ET (5 min after open) · Hold: {HOLD_MINUTES}")
    print("=" * 70)

    # ── Step 1: collect all signal days from daily bars ───────────────────────
    all_signals: list[dict] = []
    print("\n── Classifying signal days from daily bars ──")
    for sym in UNIVERSE:
        try:
            daily = pcache.load_daily(sym)
            sigs  = classify_daily_signals(daily)
            for _, row in sigs.iterrows():
                all_signals.append({
                    "sym":        sym,
                    "signal_date": str(row["date"]),
                    "entry_date": str(row["entry_date"]),
                    "setup":      row["setup"],
                })
            print(f"  {sym:<6}: {len(sigs):3d} signals")
        except FileNotFoundError as e:
            print(f"  {sym}: SKIP — {e}")

    total_sigs = len(all_signals)
    print(f"\n  Total signal days: {total_sigs} across {len(UNIVERSE)} symbols")

    # ── Step 2: load minute bars per symbol (dict for fast lookup) ─────────────
    print("\n── Loading 1-min bars (this may take ~30s) ──")
    minute_cache: dict[str, pd.DataFrame] = {}
    for sym in UNIVERSE:
        try:
            df = pcache.load_minute(sym)
            df["date"] = df["ts"].dt.date
            minute_cache[sym] = df
            print(f"  {sym:<6}: {len(df):,} bars loaded")
        except FileNotFoundError as e:
            print(f"  {sym}: SKIP — {e}")

    # ── Step 3: simulate all trades ───────────────────────────────────────────
    # Structure: trade_results[setup][hold_key] = list of returns
    trade_results: dict[str, dict] = {s: {} for s in VALID_SETUPS}
    for s in VALID_SETUPS:
        for h in HOLD_MINUTES:
            trade_results[s][str(h)] = []

    # Stop+target results: trade_results_st[setup][(stop, target)] = list of returns
    trade_results_st: dict[str, dict] = {s: {} for s in VALID_SETUPS}
    for s in VALID_SETUPS:
        for stop in STOPS:
            for tgt in TARGETS:
                trade_results_st[s][(stop, tgt)] = []

    # Time-of-day buckets: how often does a bar exceed entry price at each minute?
    tod_wins: dict[str, list[int]] = {s: [] for s in VALID_SETUPS}   # list of "minutes to first profit" values

    skipped = 0
    processed = 0

    print(f"\n── Simulating {total_sigs} trades ──")
    for sig in all_signals:
        sym   = sig["sym"]
        setup = sig["setup"]
        entry_date_str = sig["entry_date"]

        min_df = minute_cache.get(sym)
        if min_df is None:
            skipped += 1
            continue

        # Get minute bars for the entry day
        try:
            entry_date = date.fromisoformat(entry_date_str)
            day_bars   = min_df[min_df["date"] == entry_date].copy()
        except Exception:
            skipped += 1
            continue

        if len(day_bars) < ENTRY_DELAY + 5:
            skipped += 1
            continue

        # Entry bar: ENTRY_DELAY bars after open (9:35 ET = bar index ENTRY_DELAY)
        day_bars = day_bars.sort_values("ts").reset_index(drop=True)
        entry_bar  = day_bars.iloc[ENTRY_DELAY]
        entry_price = float(entry_bar["open"])   # enter at 9:35 open

        if entry_price <= 0:
            skipped += 1
            continue

        # Bars available after entry (from 9:35 onwards)
        bars_fwd = day_bars.iloc[ENTRY_DELAY:].copy()

        # ── Fixed hold periods ────────────────────────────────────────────────
        for h in HOLD_MINUTES:
            ret = simulate_hold(entry_price, bars_fwd, h)
            if ret is not None:
                trade_results[setup][str(h)].append(ret)

        # ── Stop + target combos (all at 60-min max hold) ────────────────────
        for stop in STOPS:
            for tgt in TARGETS:
                result = simulate_stop_target(entry_price, bars_fwd, stop, tgt, 60)
                if result["ret"] is not None:
                    trade_results_st[setup][(stop, tgt)].append(result["ret"])

        # ── Time-of-day: minutes until +1% gain (efficiency measure) ─────────
        for i, (_, bar) in enumerate(bars_fwd.iterrows()):
            if float(bar["high"]) >= entry_price * 1.01:
                tod_wins[setup].append(i)   # bars until first +1% gain
                break

        processed += 1

    print(f"  Processed: {processed:,}  |  Skipped: {skipped:,}")

    # ── Step 4: aggregate and format results ──────────────────────────────────
    print(f"\n{'═'*70}")
    print("  RESULTS: Fixed Hold Period (entry 9:35 ET, no stop/target)")
    print(f"{'═'*70}")

    hold_results: dict[str, dict] = {}
    for setup in VALID_SETUPS:
        hold_results[setup] = {}
        print(f"\n  ── {setup} ──")
        print(f"  {'Hold':>8}  {'N':>5}  {'Win%':>6}  {'AvgRet%':>8}  {'Median%':>8}  {'PF':>6}")
        print(f"  {'-'*52}")
        best_pf = 0
        best_hold = None
        for h in HOLD_MINUTES:
            rets = trade_results[setup][str(h)]
            s    = _stats(rets)
            mark = "  ◄ BEST" if s["pf"] > best_pf and s["n"] >= 20 else ""
            if s["pf"] > best_pf and s["n"] >= 20:
                best_pf   = s["pf"]
                best_hold = h
                mark = "  ◄ BEST"
            hlabel = f"{h}min" if h != "EOD" else "EOD"
            print(f"  {hlabel:>8}  {s['n']:>5}  {s['win_pct']:>5.1f}%  "
                  f"{s['avg_ret']:>+7.3f}%  {s['median']:>+7.3f}%  {s['pf']:>5.2f}{mark}")
            hold_results[setup][str(h)] = s
        hold_results[setup]["best_hold"] = str(best_hold)

    # ── Stop+Target analysis ──────────────────────────────────────────────────
    print(f"\n{'═'*70}")
    print("  RESULTS: Stop + Target (60-min max hold)")
    print(f"  Showing best 3 combos per setup")
    print(f"{'═'*70}")

    st_results: dict[str, dict] = {}
    for setup in VALID_SETUPS:
        combos: list[dict] = []
        for stop in STOPS:
            for tgt in TARGETS:
                rets = trade_results_st[setup][(stop, tgt)]
                s    = _stats(rets)
                combos.append({"stop": stop, "target": tgt, **s})
        combos.sort(key=lambda x: x["pf"], reverse=True)
        best3 = [c for c in combos if c["n"] >= 20][:3]
        st_results[setup] = best3

        print(f"\n  ── {setup} ──")
        print(f"  {'Stop%':>6}  {'Tgt%':>5}  {'N':>5}  {'Win%':>6}  {'AvgRet%':>8}  {'PF':>6}")
        print(f"  {'-'*48}")
        for c in best3:
            mark = "  ◄ BEST" if c == best3[0] else ""
            print(f"  {c['stop']:>5.1f}%  {c['target']:>4.1f}%  {c['n']:>5}  "
                  f"{c['win_pct']:>5.1f}%  {c['avg_ret']:>+7.3f}%  {c['pf']:>5.2f}{mark}")

    # ── Time-of-day analysis ──────────────────────────────────────────────────
    print(f"\n{'═'*70}")
    print("  TIME-OF-DAY: Minutes from entry until first +1% gain")
    print(f"  (distribution — tells you when the move typically happens)")
    print(f"{'═'*70}")

    tod_results: dict[str, dict] = {}
    for setup in VALID_SETUPS:
        tod = tod_wins[setup]
        if not tod:
            print(f"\n  {setup}: no +1% gains recorded")
            tod_results[setup] = {}
            continue
        arr = np.array(tod)
        p25, p50, p75 = np.percentile(arr, [25, 50, 75])
        pct_under_30  = (arr <= 30).mean() * 100
        pct_under_60  = (arr <= 60).mean() * 100
        tod_results[setup] = {
            "n":         len(tod),
            "p25_min":   round(float(p25), 0),
            "p50_min":   round(float(p50), 0),
            "p75_min":   round(float(p75), 0),
            "pct_under_30min": round(pct_under_30, 1),
            "pct_under_60min": round(pct_under_60, 1),
        }
        print(f"\n  ── {setup} (n={len(tod)} days hit +1%) ──")
        print(f"    25th pct: {p25:.0f} min  |  Median: {p50:.0f} min  |  75th: {p75:.0f} min")
        print(f"    {pct_under_30:.0f}% hit +1% within 30min  |  {pct_under_60:.0f}% within 60min")

    # ── Executive summary ─────────────────────────────────────────────────────
    print(f"\n{'═'*70}")
    print("  EXECUTIVE SUMMARY — Recommended timing per setup")
    print(f"{'═'*70}")
    for setup in VALID_SETUPS:
        bh   = hold_results[setup].get("best_hold", "?")
        best_combo = st_results[setup][0] if st_results[setup] else {}
        tod  = tod_results.get(setup, {})
        base_pf = hold_results[setup].get(bh, {}).get("pf", "?")
        stpf    = best_combo.get("pf", "?")
        print(f"\n  {setup}:")
        print(f"    Best fixed hold: {bh}min → PF={base_pf}")
        if best_combo:
            print(f"    Best stop+target: {best_combo['stop']}% stop / {best_combo['target']}% target → PF={stpf}")
        if tod:
            print(f"    +1% move timing: {tod.get('pct_under_30min',0)}% within 30min, "
                  f"{tod.get('pct_under_60min',0)}% within 60min (median {tod.get('p50_min',0):.0f}min)")

    # ── Save to JSON ──────────────────────────────────────────────────────────
    out = {
        "date":          str(date.today()),
        "universe_size": len(UNIVERSE),
        "total_signals": total_sigs,
        "processed":     processed,
        "entry":         "9:35 ET (5 min after open)",
        "hold_results":  hold_results,
        "st_results":    {s: st_results[s] for s in VALID_SETUPS},
        "tod_results":   tod_results,
    }
    OUT_FILE.write_text(json.dumps(out, indent=2))
    print(f"\n  Results → {OUT_FILE}")
    print("=" * 70)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--download", action="store_true",
                    help="Download/update Polygon cache before running backtest")
    args = ap.parse_args()

    if args.download:
        pcache.main(force=False)

    # Warn on missing cache but don't block — backtest skips unavailable symbols
    missing_daily  = [s for s in UNIVERSE if not (pcache.CACHE_DIR / f"{s}_daily.parquet").exists()]
    missing_minute = [s for s in UNIVERSE if not (pcache.CACHE_DIR / f"{s}_minute.parquet").exists()]
    if missing_daily or missing_minute:
        print(f"\n⚠  Missing daily cache:  {missing_daily}")
        print(f"⚠  Missing minute cache: {missing_minute}")
        print("   Backtest will skip those symbols.")
        print("   To download: venv/bin/python3.11 scripts/polygon_cache.py --batch 2\n")
    cached = [s for s in UNIVERSE
              if (pcache.CACHE_DIR / f"{s}_daily.parquet").exists()
              and (pcache.CACHE_DIR / f"{s}_minute.parquet").exists()]
    print(f"  Running on {len(cached)}/{len(UNIVERSE)} symbols with complete cache")

    run_backtest()


if __name__ == "__main__":
    main()
