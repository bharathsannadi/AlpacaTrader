#!/usr/bin/env python3.11
"""
backtest_shares_robust.py — robustness stress-test of the S3 SHARES finding.

backtest_structures.py established: same vwap_momentum entries as SHARES =
Test PF 1.38 / +$70,212 / robust OOS. Before that becomes actionable it
must survive the make-or-break questions a pro asks of any backtest:

  1. PER-SYMBOL  — is +$70k broad, or 1-2 names carrying a dead book?
  2. PER-YEAR    — does it hold each of 3 years, or one lucky regime?
  3. SYMBOL×YEAR — the strict test: positive in most cells, not a few.
  4. COST/SLIP   — does the edge survive 1→3→5→10 bp round-trip slippage?
  5. WALK-FWD    — per-symbol train→test decay (curve-fit detector).

Shares-only (no option fetch) → fast, $0 (cached Polygon bars). Same
entry/exit logic as S3 in backtest_structures (single source of truth:
imports replay_day + _atr_exit_spot, does NOT re-implement).

Run:  venv/bin/python3.11 scripts/backtest_shares_robust.py
      venv/bin/python3.11 scripts/backtest_shares_robust.py SPY NVDA
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
from backtest_structures import (_atr_exit_spot, RISK_BUDGET,
                                 ATR_STOP_M, SYMBOLS_DEFAULT, OUT_DIR)

ET = T.ET
SLIP_BPS = [1.0, 3.0, 5.0, 10.0]      # round-trip share slippage sensitivity


def gen_share_trades(symbol: str) -> list[dict]:
    """Every vwap_momentum signal → one shares trade (gross of slippage;
    slippage applied later so the cost sweep needs only ONE data pass)."""
    df = fetch_5m(symbol)
    if df is None or df.empty:
        return []
    df["day"] = df["begins_at"].dt.date
    out = []
    for d in sorted(df["day"].unique()):
        day_df = df[df["day"] == d].drop(columns="day").reset_index(drop=True)
        di = T._add_indicators(day_df.copy()).reset_index(drop=True)
        n = len(di)
        for i, bar, direction, reason, sigcls in replay_day(day_df):
            if sigcls != "vwap_momentum" or i >= n:
                continue
            spot0 = float(di["close_price"].iloc[i])
            atr0 = float(di["atr"].iloc[i]) if not np.isnan(di["atr"].iloc[i]) else None
            if not atr0 or atr0 <= 0:
                continue
            ex_spot, _, why = _atr_exit_spot(di, i, direction, spot0, atr0)
            shares = max(1.0, RISK_BUDGET / (ATR_STOP_M * atr0))  # $200 stop
            sgn = 1.0 if direction == "bull" else -1.0
            out.append({"sym": symbol, "date": str(d),
                        "year": str(d)[:4], "dir": direction,
                        "spot0": spot0, "ex": ex_spot, "shares": shares,
                        "gross": sgn * (ex_spot - spot0) * shares,
                        "why": why})
    return out


def _pnl(t: dict, slip_bp: float) -> float:
    slip = (t["spot0"] + t["ex"]) * (slip_bp / 1e4) * t["shares"]
    return t["gross"] - slip


def _stats(tr: list[dict], slip_bp: float) -> dict:
    if not tr:
        return {"n": 0, "win": 0, "pf": 0, "avg": 0, "tot": 0, "mdd": 0}
    p = [_pnl(t, slip_bp) for t in tr]
    gw = sum(x for x in p if x > 0)
    gl = abs(sum(x for x in p if x < 0))
    eq = peak = mdd = 0.0
    for x in p:
        eq += x; peak = max(peak, eq); mdd = min(mdd, eq - peak)
    return {"n": len(p),
            "win": round(sum(1 for x in p if x > 0) / len(p) * 100, 1),
            "pf": round(gw / gl, 2) if gl else (99.9 if gw else 0),
            "avg": round(sum(p) / len(p), 2),
            "tot": round(sum(p), 0), "mdd": round(mdd, 0)}


def build_report(all_tr: list[dict]) -> str:
    BASE = 3.0   # headline slippage assumption (conservative vs the 1bp in S3)
    L = [f"# Shares-Path Robustness — REAL Polygon {BACKTEST_YEARS}yr\n",
         f"_Generated {datetime.now(ET):%Y-%m-%d %H:%M ET}_\n",
         f"Stress-test of the S3 shares finding. Headline uses **{BASE:.0f} bp** "
         f"round-trip slippage (3× the optimistic 1 bp in the structure run — "
         f"deliberately pessimistic). Same vwap_momentum entries, ATR "
         f"stop/target, $200/trade risk sizing.\n"]

    syms = sorted({t["sym"] for t in all_tr})
    years = sorted({t["year"] for t in all_tr})

    # 1 — per symbol
    L += ["## 1. Per-symbol (@ 3 bp) — is the edge broad?\n",
          "| Symbol | n | Win% | PF | Avg$ | Total$ | MaxDD$ |",
          "|---|---|---|---|---|---|---|"]
    for s in syms:
        st = _stats([t for t in all_tr if t["sym"] == s], BASE)
        flag = " ✅" if st["pf"] >= 1.1 else (" ⚠️" if st["pf"] >= 1.0 else " ⛔")
        L.append(f"| {s} | {st['n']} | {st['win']} | {st['pf']}{flag} | "
                 f"{st['avg']:+} | {st['tot']:+} | {st['mdd']} |")

    # 2 — per year
    L += ["\n## 2. Per-year (@ 3 bp) — does it hold every regime?\n",
          "| Year | n | Win% | PF | Avg$ | Total$ |",
          "|---|---|---|---|---|---|"]
    for y in years:
        st = _stats([t for t in all_tr if t["year"] == y], BASE)
        flag = " ✅" if st["pf"] >= 1.1 else (" ⚠️" if st["pf"] >= 1.0 else " ⛔")
        L.append(f"| {y} | {st['n']} | {st['win']} | {st['pf']}{flag} | "
                 f"{st['avg']:+} | {st['tot']:+} |")

    # 3 — symbol × year PF grid (the strict test)
    L += ["\n## 3. Symbol × Year PF grid (@ 3 bp) — the strict test\n",
          "| Symbol | " + " | ".join(years) + " |",
          "|---|" + "---|" * len(years)]
    pos = tot = 0
    for s in syms:
        cells = []
        for y in years:
            st = _stats([t for t in all_tr if t["sym"] == s and t["year"] == y], BASE)
            if st["n"] == 0:
                cells.append("—"); continue
            tot += 1
            if st["pf"] >= 1.0:
                pos += 1
            cells.append(f"{st['pf']}")
        L.append(f"| {s} | " + " | ".join(cells) + " |")
    L.append(f"\n**{pos}/{tot} symbol-year cells have PF ≥ 1.0.** "
             f"{'✅ broad-based' if tot and pos/tot >= 0.67 else '⚠️ concentrated — edge not robust across the matrix' }\n")

    # 4 — cost / slippage sensitivity
    L += ["\n## 4. Cost sensitivity — does the edge survive worse fills?\n",
          "| Slippage (bp RT) | n | Win% | PF | Avg$ | Total$ |",
          "|---|---|---|---|---|---|"]
    for bp in SLIP_BPS:
        st = _stats(all_tr, bp)
        flag = " ✅" if st["pf"] >= 1.1 else (" ⚠️" if st["pf"] >= 1.0 else " ⛔")
        L.append(f"| {bp:g} | {st['n']} | {st['win']} | {st['pf']}{flag} | "
                 f"{st['avg']:+} | {st['tot']:+} |")

    # 5 — per-symbol walk-forward (curve-fit detector)
    L += ["\n## 5. Per-symbol walk-forward (@ 3 bp) — OOS decay\n",
          "| Symbol | Train PF | Test PF | Decay% |",
          "|---|---|---|---|"]
    for s in syms:
        sr = [t for t in all_tr if t["sym"] == s]
        ds = sorted({t["date"] for t in sr})
        if len(ds) < 6:
            L.append(f"| {s} | — | — | (insufficient) |"); continue
        mid = ds[len(ds) // 2]
        tr = _stats([t for t in sr if t["date"] < mid], BASE)
        te = _stats([t for t in sr if t["date"] >= mid], BASE)
        dec = (tr["pf"] - te["pf"]) / tr["pf"] * 100 if tr["pf"] else 0
        f = " ✅" if dec <= 25 and te["pf"] >= 1.0 else " ⚠️"
        L.append(f"| {s} | {tr['pf']} | {te['pf']} | {dec:+.0f}%{f} |")

    # verdict
    agg = _stats(all_tr, BASE)
    L += ["\n## Verdict\n"]
    broad = tot and pos / tot >= 0.67
    survives = _stats(all_tr, 5.0)["pf"] >= 1.0
    if agg["pf"] >= 1.1 and broad and survives:
        L.append(f"**✅ ROBUST.** Aggregate PF {agg['pf']} @ 3 bp, broad across "
                 f"symbols & years ({pos}/{tot} cells positive), survives 5 bp "
                 f"slippage. The shares path holds up to the make-or-break "
                 f"checks → proceed to a shares advisory/paper harness + "
                 f"GO_LIVE_CHECKLIST. Still NOT auto-confirmation to trade "
                 f"real money — paper-validate live first.")
    elif agg["pf"] >= 1.0:
        L.append(f"**⚠️ MARGINAL / CONCENTRATED.** Aggregate PF {agg['pf']} @ "
                 f"3 bp but {'NOT broad-based' if not broad else ''}"
                 f"{' and ' if not broad and not survives else ''}"
                 f"{'fails at 5 bp slippage' if not survives else ''}. The "
                 f"+$70k headline was likely carried by a subset → do NOT "
                 f"build the shares path on the full watchlist; narrow to the "
                 f"symbols/years that pass, re-test, stay paper.")
    else:
        L.append(f"**⛔ FAILS robustness.** Aggregate PF {agg['pf']} @ a "
                 f"realistic 3 bp. The S3 1.38 was an artifact of the "
                 f"optimistic 1 bp assumption. Shares path is NOT validated. "
                 f"Re-examine the entry signal itself; do not deploy.")
    L.append(f"\n_REAL Polygon {BACKTEST_YEARS}yr 5-min bars, cached. Shares "
             f"execution is conservatively modeled; this RANKS robustness, it "
             f"is not a live-trading green light (paper + GO_LIVE_CHECKLIST "
             f"still required)._")
    return "\n".join(L)


def main():
    syms = [s.upper() for s in sys.argv[1:]] or SYMBOLS_DEFAULT
    print(f"backtest_shares_robust — {syms} — REAL {BACKTEST_YEARS}yr "
          f"(cached, $0)\n")
    all_tr = []
    for s in syms:
        print(f"  {s} …", end=" ", flush=True)
        tr = gen_share_trades(s)
        print(f"{len(tr)} trades")
        all_tr += tr
    OUT_DIR.mkdir(exist_ok=True)
    rep = build_report(all_tr)
    fn = OUT_DIR / f"backtest_shares_robust_{datetime.now(ET):%Y-%m-%d}.md"
    fn.write_text(rep)
    print(f"\n✓ Report → {fn}\n")
    print(rep.split("## Verdict")[-1][:1100])


if __name__ == "__main__":
    main()
