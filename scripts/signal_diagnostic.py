#!/usr/bin/env python3.11
"""
signal_diagnostic.py — entry-signal redesign STEP 1 (data-driven, not guesswork).

THE fork question: does each signal class predict the UNDERLYING's direction
better than a coin flip — decoupled entirely from option P&L (no strike, no
theta, no IV, no exit logic)?

  • Directional hit-rate > ~55% with positive net excursion
        → the signal HAS edge; the option structure (7-14 DTE naked + theta
          + the exit) is what's killing it → redesign the STRUCTURE.
  • Hit-rate ≈ 50% (coin flip) or net-negative excursion
        → the signal logic is NOISE → must be REPLACED wholesale.

Pure underlying analysis on the REAL 3yr Polygon stock bars already cached
on the Desktop (no new API cost). Uses the SAME real evaluators as live.

Run: venv/bin/python3.11 scripts/signal_diagnostic.py
"""
from __future__ import annotations
import sys
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent))
import numpy as np
import pandas as pd
import spy_auto_trader as T
import polygon_data as P
from backtest_v2 import replay_day, BACKTEST_YEARS   # reuse the proven replay

SYMS = ["SPY", "AMZN", "GOOG", "MSFT", "NVDA", "META"]
HORIZONS = [3, 6, 12]      # bars ahead = 15, 30, 60 min on 5-min bars


def diagnose(symbol: str) -> dict:
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=BACKTEST_YEARS * 365 + 5)).strftime("%Y-%m-%d")
    df = P.stock_5m(symbol, start, end)
    if df is None or df.empty:
        return {}
    df["day"] = df["begins_at"].dt.date
    # cls -> horizon -> list of signed favorable-move fractions (in ATR units)
    rec = defaultdict(lambda: defaultdict(list))
    for d in sorted(df["day"].unique()):
        day = df[df["day"] == d].drop(columns="day").reset_index(drop=True)
        di = T._add_indicators(day.copy()).reset_index(drop=True)
        n = len(di)
        for i, bar, direction, reason, sigcls in replay_day(day):
            if i >= n:
                continue
            spot0 = float(di["close_price"].iloc[i])
            atr0 = float(di["atr"].iloc[i]) if not np.isnan(di["atr"].iloc[i]) else None
            if not atr0 or atr0 <= 0:
                continue
            sign = 1.0 if direction == "bull" else -1.0
            for h in HORIZONS:
                j = i + h
                if j >= n:
                    continue
                fwd = float(di["close_price"].iloc[j]) - spot0
                # signed favorable move, normalized by ATR (regime-fair)
                rec[sigcls][h].append(sign * fwd / atr0)
    out = {}
    for cls, hd in rec.items():
        out[cls] = {}
        for h, xs in hd.items():
            a = np.array(xs)
            if len(a) < 20:
                continue
            out[cls][h] = {
                "n": len(a),
                "hit": round(float((a > 0).mean()) * 100, 1),     # % moved favorably
                "mean_atr": round(float(a.mean()), 3),            # avg favorable (ATR units)
                "median_atr": round(float(np.median(a)), 3),
                "p_pos_sharpe": round(float(a.mean() / (a.std() + 1e-9)), 3),
            }
    return out


def main():
    print(f"Signal directional-edge diagnostic — REAL {BACKTEST_YEARS}yr, "
          f"underlying only (no options/theta/exit)\n")
    agg = defaultdict(lambda: defaultdict(list))
    per_sym = {}
    for s in SYMS:
        print(f"  {s} …", end=" ", flush=True)
        r = diagnose(s)
        per_sym[s] = r
        tot = sum(v.get(6, {}).get("n", 0) for v in r.values())
        print(f"{tot} signals @30min")
        for cls, hd in r.items():
            for h, m in hd.items():
                agg[cls][h].append(m)

    def fmt(m):
        return (f"n={m['n']:>5} hit={m['hit']:>5}%  "
                f"mean={m['mean_atr']:+.3f}ATR  med={m['median_atr']:+.3f}  "
                f"sharpe={m['p_pos_sharpe']:+.3f}")

    print("\n" + "=" * 78)
    print("AGGREGATE (all 6 symbols) — directional edge by signal class & horizon")
    print("=" * 78)
    for cls in sorted(agg):
        print(f"\n■ {cls}")
        for h in HORIZONS:
            ms = agg[cls].get(h, [])
            if not ms:
                continue
            N = sum(x["n"] for x in ms)
            hit = sum(x["hit"] * x["n"] for x in ms) / N
            mean = sum(x["mean_atr"] * x["n"] for x in ms) / N
            shp = sum(x["p_pos_sharpe"] * x["n"] for x in ms) / N
            verdict = ("✅ EDGE" if hit >= 55 and mean > 0.02 else
                       "🟡 WEAK" if hit >= 52 and mean > 0 else
                       "⛔ NOISE")
            print(f"   {h*5:>2}min: n={N:>6} hit={hit:5.1f}%  "
                  f"mean={mean:+.3f}ATR  sharpe={shp:+.3f}   {verdict}")

    print("\n" + "=" * 78)
    print("PER-SYMBOL (30-min horizon) — is SPY's edge unique?")
    print("=" * 78)
    for s in SYMS:
        r = per_sym.get(s, {})
        bits = []
        for cls, hd in sorted(r.items()):
            m = hd.get(6)
            if m:
                bits.append(f"{cls}:hit{m['hit']}%/mean{m['mean_atr']:+.2f}")
        print(f"  {s:<5} {'  '.join(bits) if bits else '(no signals)'}")

    print("\n" + "=" * 78)
    print("INTERPRETATION")
    print("=" * 78)
    print("  ✅ EDGE  → signal predicts direction; option STRUCTURE kills it →")
    print("            redesign structure (DTE / spreads / faster targets), keep signal.")
    print("  🟡 WEAK  → marginal; needs a confluence/filter to lift hit-rate.")
    print("  ⛔ NOISE → signal has no directional predictive power → replace the")
    print("            signal logic entirely. Tuning anything else is futile.")


if __name__ == "__main__":
    main()
