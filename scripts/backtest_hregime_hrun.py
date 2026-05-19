#!/usr/bin/env python3.11
"""
backtest_hregime_hrun.py — THE decisive Tier-1 experiment.

Same vwap_momentum entries (the one signal with proven thin directional
edge) tested as SHARES, varying two levers the books + our backtests
converged on, on REAL Polygon 3yr cached data ($0):

  H-REGIME : gate entries to a TRENDING regime (EMA-stack aligned with
             signal direction AND bb_width NOT compressed) — Gunn KB §8,
             Brooks "EMA compression → don't trade". Uses the LIVE
             engine's own indicators (T._add_indicators).
  H-RUN    : runner exit (partial @ +1ATR, stop→breakeven, Chandelier
             2xATR trail on the remainder) REPLACING the fixed 1.5xATR
             target that clipped the fat-tail winners — Brooks p.85 /
             Covel KB §8/§11.
  VOL-FILT : pre-specified universe rule — trade only symbols in the
             UPPER HALF by median ATR% (cost-vs-movement; 39-ticker
             finding). A RULE, not hand-picked names.

Variants (walk-forward 50/50, cost at 3 & 5 bp; honest: runner exit
charges slippage on entry + partial + final = 3 fills):
  V0 baseline  : fixed 1.5ATR target, no regime, all-39   (sanity vs prior)
  V1 H-RUN     : runner exit, no regime, all-39
  V2 +H-REGIME : runner + trending gate, all-39
  V3 +VOL-FILT : runner + trending gate + upper-half ATR% universe

Decision: a variant is a CANDIDATE only if TEST PF ≥ 1.10 at BOTH 3 and
5 bp out-of-sample. Anything else = not validated (stay paper).

Run: venv/bin/python3.11 scripts/backtest_hregime_hrun.py
"""
from __future__ import annotations
import sys, warnings
from pathlib import Path
from datetime import datetime
from collections import defaultdict

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent))
import logging
logging.disable(logging.CRITICAL)

import numpy as np
import spy_auto_trader as T
from backtest_v2 import replay_day, fetch_5m, BACKTEST_YEARS
from backtest_structures import RISK_BUDGET            # $200/trade
from universe import ALL
ET = T.ET
OUT_DIR = Path(__file__).parent.parent / "backtest_results"

ATR_STOP_M  = 1.0    # signal-invalidation distance
PARTIAL_M   = 1.0    # take 50% off here, move stop to breakeven
TRAIL_M     = 2.0    # Chandelier trail on the runner
FIXED_TGT_M = 1.5    # V0 legacy fixed target (the thing H-RUN replaces)
TIME_CAP    = 120    # minutes


def _trending(di, i: int, direction: str) -> bool:
    """Live-engine-indicator regime gate. Trending = EMA stack aligned
    with the signal AND Bollinger width not compressed (no chop/coil)."""
    r = di.iloc[i]
    e9, e21 = r.get("ema9", np.nan), r.get("ema21", np.nan)
    bw = r.get("bb_width", np.nan)
    if np.isnan(e9) or np.isnan(e21):
        return False
    aligned = (e9 > e21) if direction == "bull" else (e9 < e21)
    # bb_width not compressed: above its trailing-50 median (expansion)
    win = di["bb_width"].iloc[max(0, i - 50):i + 1].dropna()
    not_chop = (not np.isnan(bw)) and len(win) >= 10 and bw >= float(win.median())
    return bool(aligned and not_chop)


def _legacy_exit(di, i, direction, spot0, atr0):
    """V0: fixed 1.0xATR stop / 1.5xATR target / time / EOD. Returns list
    of (exit_spot, frac) legs."""
    n = len(di)
    for j in range(i + 1, n):
        s = float(di["close_price"].iloc[j])
        adv = (spot0 - s) if direction == "bull" else (s - spot0)
        fav = (s - spot0) if direction == "bull" else (spot0 - s)
        held = (di["begins_at"].iloc[j] - di["begins_at"].iloc[i]).total_seconds()/60
        if adv >= ATR_STOP_M*atr0:  return [(s, 1.0)]
        if fav >= FIXED_TGT_M*atr0: return [(s, 1.0)]
        if held >= TIME_CAP:        return [(s, 1.0)]
    return [(float(di["close_price"].iloc[-1]), 1.0)]


def _runner_exit(di, i, direction, spot0, atr0):
    """H-RUN: partial 50% @ +PARTIAL_M ATR + stop→breakeven, Chandelier
    TRAIL_M xATR trail on remaining 50%. Returns list of (spot, frac)."""
    n = len(di); legs = []
    rem = 1.0
    stop = spot0 - ATR_STOP_M*atr0 if direction == "bull" else spot0 + ATR_STOP_M*atr0
    peak = spot0
    partial_done = False
    for j in range(i + 1, n):
        s = float(di["close_price"].iloc[j])
        held = (di["begins_at"].iloc[j] - di["begins_at"].iloc[i]).total_seconds()/60
        if direction == "bull":
            peak = max(peak, s)
            fav = s - spot0
            if not partial_done and fav >= PARTIAL_M*atr0:
                legs.append((s, 0.5)); rem = 0.5; partial_done = True
                stop = spot0                                   # breakeven
            if partial_done:
                stop = max(stop, peak - TRAIL_M*atr0)           # Chandelier
            if s <= stop:
                legs.append((s, rem)); return legs
        else:
            peak = min(peak, s)
            fav = spot0 - s
            if not partial_done and fav >= PARTIAL_M*atr0:
                legs.append((s, 0.5)); rem = 0.5; partial_done = True
                stop = spot0
            if partial_done:
                stop = min(stop, peak + TRAIL_M*atr0)
            if s >= stop:
                legs.append((s, rem)); return legs
        if held >= TIME_CAP:
            legs.append((s, rem)); return legs
    legs.append((float(di["close_price"].iloc[-1]), rem))
    return legs


VARIANTS = ["V0_baseline", "V1_hrun", "V2_hrun_regime", "V3_hrun_regime_vol"]


def gen(symbol: str):
    df = fetch_5m(symbol)
    if df is None or df.empty:
        return {}, 0.0
    df["day"] = df["begins_at"].dt.date
    out = {v: [] for v in VARIANTS}
    atrpct_acc = []
    for d in sorted(df["day"].unique()):
        day = df[df["day"] == d].drop(columns="day").reset_index(drop=True)
        di = T._add_indicators(day.copy()).reset_index(drop=True)
        n = len(di)
        for i, bar, direction, reason, sig in replay_day(day):
            if sig != "vwap_momentum" or i >= n:
                continue
            spot0 = float(di["close_price"].iloc[i])
            a = di["atr"].iloc[i]
            atr0 = float(a) if not np.isnan(a) else None
            if not atr0 or atr0 <= 0 or spot0 <= 0:
                continue
            atrpct_acc.append(atr0 / spot0)
            sgn = 1.0 if direction == "bull" else -1.0
            sh = max(1.0, RISK_BUDGET / (ATR_STOP_M*atr0))
            trending = _trending(di, i, direction)
            for v in VARIANTS:
                if v == "V0_baseline":
                    legs = _legacy_exit(di, i, direction, spot0, atr0)
                else:
                    if v in ("V2_hrun_regime", "V3_hrun_regime_vol") and not trending:
                        continue                                # regime gate
                    legs = _runner_exit(di, i, direction, spot0, atr0)
                out[v].append({"sym": symbol, "date": str(d), "dir": direction,
                               "spot0": spot0, "legs": legs, "sh": sh, "sgn": sgn})
    med_atrpct = float(np.median(atrpct_acc)) if atrpct_acc else 0.0
    return out, med_atrpct


def pnl(t, slip_bp):
    """Slippage charged on EVERY fill: 1 entry + each exit leg (honest:
    the runner adds fills)."""
    sgn, sh, s0 = t["sgn"], t["sh"], t["spot0"]
    bp = slip_bp / 1e4
    p = -s0 * bp * sh                       # entry slippage (full size)
    for sp, fr in t["legs"]:
        p += sgn * (sp - s0) * sh * fr      # leg P&L
        p += -sp * bp * sh * fr             # exit slippage on that leg
    return p


def stats(tr, slip_bp):
    if not tr:
        return {"n": 0, "win": 0, "pf": 0, "avg": 0, "tot": 0}
    ps = [pnl(t, slip_bp) for t in tr]
    gw = sum(x for x in ps if x > 0); gl = abs(sum(x for x in ps if x < 0))
    return {"n": len(ps),
            "win": round(sum(1 for x in ps if x > 0)/len(ps)*100, 1),
            "pf": round(gw/gl, 2) if gl else (99.9 if gw else 0),
            "avg": round(sum(ps)/len(ps), 2), "tot": round(sum(ps), 0)}


def main():
    syms = [s.upper() for s in sys.argv[1:]] or list(ALL)
    print(f"backtest_hregime_hrun — {len(syms)} syms, REAL {BACKTEST_YEARS}yr "
          f"cached ($0)\n", flush=True)
    allt = {v: [] for v in VARIANTS}
    med = {}
    for s in syms:
        o, m = gen(s)
        med[s] = m
        c = {v: len(o.get(v, [])) for v in VARIANTS}
        print(f"  {s:<5} atr%={m*100:5.2f}  {c}", flush=True)
        for v in VARIANTS:
            allt[v] += o.get(v, [])
    # pre-specified vol-filter: symbols in UPPER HALF by median ATR%
    vals = sorted(med.values())
    cut = vals[len(vals)//2] if vals else 0.0
    hi = {s for s, m in med.items() if m >= cut}
    allt["V3_hrun_regime_vol"] = [t for t in allt["V3_hrun_regime_vol"]
                                  if t["sym"] in hi]

    L = [f"# H-REGIME + H-RUN + Vol-Universe — REAL Polygon {BACKTEST_YEARS}yr\n",
         f"_Generated {datetime.now(ET):%Y-%m-%d %H:%M ET}_\n",
         f"Same vwap_momentum entries as SHARES. Runner exit charges "
         f"slippage on entry+partial+final (honest). Vol-filter = upper "
         f"half by median ATR% (≥{cut*100:.2f}%), a pre-specified RULE. "
         f"Walk-forward 50/50.\n",
         "| Variant | n | Tr PF | **Te PF@3bp** | Te win% | Te$ | **Te PF@5bp** |",
         "|---|---|---|---|---|---|---|"]
    dates = sorted({t["date"] for t in allt["V0_baseline"]})
    split = dates[len(dates)//2] if len(dates) >= 4 else None
    verdict_rows = []
    for v in VARIANTS:
        tr = allt[v]
        if not tr or split is None:
            L.append(f"| {v} | {len(tr)} | – | – | – | – | – |"); continue
        trn = stats([t for t in tr if t["date"] < split], 3)
        te3 = stats([t for t in tr if t["date"] >= split], 3)
        te5 = stats([t for t in tr if t["date"] >= split], 5)
        L.append(f"| {v} | {te3['n']} | {trn['pf']} | **{te3['pf']}** | "
                 f"{te3['win']} | {te3['tot']:+} | **{te5['pf']}** |")
        verdict_rows.append((v, te3["pf"], te5["pf"]))

    L.append("\n## Verdict\n")
    cands = [v for v, p3, p5 in verdict_rows if p3 >= 1.10 and p5 >= 1.10]
    base = next((p3 for v, p3, p5 in verdict_rows if v == "V0_baseline"), None)
    if cands:
        L.append(f"**✅ CANDIDATE(S): {', '.join(cands)}** — Test PF ≥ 1.10 "
                 f"at BOTH 3 and 5 bp OOS. First strategy to clear the "
                 f"cost-robust gate. Next: paper incubation + GO_LIVE_"
                 f"CHECKLIST (NOT auto-live). Baseline V0 Te@3bp={base}.")
    else:
        best = max(verdict_rows, key=lambda r: r[1]) if verdict_rows else None
        L.append(f"**⛔ NONE clears the gate** (need Te PF ≥1.10 @ BOTH "
                 f"3&5bp). Best: {best[0] if best else '—'} "
                 f"@3bp={best[1] if best else '—'} / @5bp="
                 f"{best[2] if best else '—'}. H-RUN/H-REGIME/vol-filter "
                 f"do NOT rescue the thin signal after honest costs → "
                 f"Tier-1 exhausted; move to Tier-2 (orthogonal edge: "
                 f"Connors mean-reversion) or accept the signal is "
                 f"unmonetizable. Stay paper. Baseline V0 Te@3bp={base}.")
    L.append(f"\n_REAL Polygon {BACKTEST_YEARS}yr cached shares; runner "
             f"slippage on all fills (conservative). Ranks variants — not "
             f"a live green light (paper + GO_LIVE_CHECKLIST required)._")
    OUT_DIR.mkdir(exist_ok=True)
    fn = OUT_DIR / f"backtest_hregime_hrun_{datetime.now(ET):%Y-%m-%d}.md"
    fn.write_text("\n".join(L))
    print(f"\n✓ Report → {fn}\n")
    print("\n".join(L).split("## Verdict")[-1][:900])


if __name__ == "__main__":
    main()
