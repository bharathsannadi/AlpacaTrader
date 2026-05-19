#!/usr/bin/env python3.11
"""
backtest_connors.py — TIER-2: orthogonal mean-reversion edge candidate.

After Tier-1 failed (H-REGIME+H-RUN+vol-universe couldn't clear 3-5bp
OOS), this tests a genuinely ORTHOGONAL signal family — Connors-style
short-term mean-reversion-in-trend (KB §8 Connors/Raschke). Independent
of vwap_momentum; uses live engine indicators (T._add_indicators).

RULES (PRE-SPECIFIED, NOT swept — same discipline as Tier-1):
  Long-term filter : close > intraday ema200 (bull) / < ema200 (bear)
                     — KB §8 Connors/Raschke trend filter
  Entry trigger    : RSI(2) < 10 (bull) / > 90 (bear)
                     — canonical Connors oversold/overbought
  Confirmation     : enter at NEXT bar's open (no look-ahead)
  Exit             : RSI(2) crosses 50 (mean reverted)
                     OR adverse 1.0xATR stop (invalidation)
                     OR 120-min time cap
  Per-day per-dir  : one trade max (no stacking)
  Sizing           : shares so 1xATR stop ≈ $200 risk (Tier-1 parity)
  Costs            : entry+exit fills both pay slip bp on notional
  Universe         : 39-ticker universe.ALL (Tier-1 parity, no vol-filter
                     — keep gate identical, no advantage)
  Pass bar         : Test PF ≥ 1.10 at BOTH 3 and 5 bp OOS (no loosening)

Walk-forward 50/50. $0 on cached Polygon 3yr.
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
import spy_auto_trader as T
from backtest_v2 import fetch_5m, BACKTEST_YEARS
from backtest_structures import RISK_BUDGET
from universe import ALL
ET = T.ET
OUT_DIR = Path(__file__).parent.parent / "backtest_results"

RSI_N         = 2          # Connors short-period RSI
RSI_LO        = 10.0       # bull entry threshold
RSI_HI        = 90.0       # bear entry threshold
RSI_EXIT      = 50.0       # mean-reverted exit
ATR_STOP_M    = 1.0
TIME_CAP_MIN  = 120


def rsi_n(close: pd.Series, n: int) -> pd.Series:
    """Wilder-style RSI (EMA alpha=1/n). Pre-specified n; no tuning."""
    d = close.diff()
    up = d.where(d > 0, 0.0)
    dn = (-d).where(d < 0, 0.0)
    ag = up.ewm(alpha=1.0 / n, adjust=False).mean()
    al = dn.ewm(alpha=1.0 / n, adjust=False).mean()
    rs = ag / al.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50.0)


def gen(symbol: str) -> list[dict]:
    df = fetch_5m(symbol)
    if df is None or df.empty:
        return []
    df["day"] = df["begins_at"].dt.date
    out = []
    for d in sorted(df["day"].unique()):
        day = df[df["day"] == d].drop(columns="day").reset_index(drop=True)
        if len(day) < 30:
            continue
        di = T._add_indicators(day.copy()).reset_index(drop=True)
        di["rsi2"] = rsi_n(di["close_price"], RSI_N)
        n = len(di)
        fired_dirs: set[str] = set()
        for i in range(20, n - 2):                  # need history + a next bar
            ema200 = di["ema200"].iloc[i]
            atr0 = di["atr"].iloc[i]
            r = di["rsi2"].iloc[i]
            c = float(di["close_price"].iloc[i])
            if np.isnan(ema200) or np.isnan(atr0) or atr0 <= 0:
                continue
            direction = None
            if r < RSI_LO and c > ema200:
                direction = "bull"
            elif r > RSI_HI and c < ema200:
                direction = "bear"
            if not direction or direction in fired_dirs:
                continue
            # enter at next bar's open (no look-ahead)
            entry_i = i + 1
            spot0 = float(di["open_price"].iloc[entry_i])
            ts0 = di["begins_at"].iloc[entry_i]
            sgn = 1.0 if direction == "bull" else -1.0
            sh = max(1.0, RISK_BUDGET / (ATR_STOP_M * float(atr0)))
            # walk exit
            exit_spot = None; why = "eod"
            for j in range(entry_i + 1, n):
                s = float(di["close_price"].iloc[j])
                rj = float(di["rsi2"].iloc[j])
                held = (di["begins_at"].iloc[j] - ts0).total_seconds() / 60
                adv = (spot0 - s) if direction == "bull" else (s - spot0)
                # invalidation
                if adv >= ATR_STOP_M * float(atr0):
                    exit_spot, why = s, "atr_stop"; break
                # mean-reverted
                if direction == "bull" and rj >= RSI_EXIT:
                    exit_spot, why = s, "mean_revert"; break
                if direction == "bear" and rj <= RSI_EXIT:
                    exit_spot, why = s, "mean_revert"; break
                if held >= TIME_CAP_MIN:
                    exit_spot, why = s, "time_cap"; break
            if exit_spot is None:
                exit_spot = float(di["close_price"].iloc[-1])
            out.append({"sym": symbol, "date": str(d), "year": str(d)[:4],
                        "dir": direction, "spot0": spot0, "ex": exit_spot,
                        "sh": sh, "sgn": sgn, "why": why})
            fired_dirs.add(direction)
    return out


def pnl(t, slip_bp: float) -> float:
    bp = slip_bp / 1e4
    return (t["sgn"] * (t["ex"] - t["spot0"]) * t["sh"]
            - (t["spot0"] + t["ex"]) * bp * t["sh"])


def stats(tr, slip_bp):
    if not tr:
        return {"n": 0, "win": 0, "pf": 0, "avg": 0, "tot": 0}
    ps = [pnl(t, slip_bp) for t in tr]
    gw = sum(x for x in ps if x > 0); gl = abs(sum(x for x in ps if x < 0))
    return {"n": len(ps),
            "win": round(sum(1 for x in ps if x > 0)/len(ps)*100, 1),
            "pf": round(gw/gl, 2) if gl else (99.9 if gw else 0),
            "avg": round(sum(ps)/len(ps), 2),
            "tot": round(sum(ps), 0)}


def main():
    syms = [s.upper() for s in sys.argv[1:]] or list(ALL)
    print(f"backtest_connors (Tier-2 mean-reversion) — {len(syms)} syms, "
          f"REAL {BACKTEST_YEARS}yr cached ($0)\n", flush=True)
    all_tr = []
    for s in syms:
        tr = gen(s)
        print(f"  {s:<5} {len(tr)} trades", flush=True)
        all_tr += tr

    L = [f"# Tier-2 Connors Mean-Reversion — REAL Polygon {BACKTEST_YEARS}yr\n",
         f"_Generated {datetime.now(ET):%Y-%m-%d %H:%M ET}_\n",
         "PRE-SPECIFIED rules (RSI(2)<10 above ema200 bull / >90 below ema200 bear; "
         "exit RSI(2)↔50 or 1xATR stop or 120-min cap). Same 39-sym universe, same "
         "$200 risk sizing, same cost gate. Walk-forward 50/50.\n"]

    # full sweep + walk-forward
    dates = sorted({t["date"] for t in all_tr})
    if not dates:
        L.append("**NO trades** — entry filter (RSI(2)<10 above ema200) returned zero on the universe. The signal is too strict at intraday 5-min granularity to fire enough. Honest negative.")
    else:
        split = dates[len(dates)//2] if len(dates) >= 4 else None
        L += ["| Slippage (bp RT) | n | Win% | PF | Avg$ | Total$ |",
              "|---|---|---|---|---|---|"]
        for bp in (1, 3, 5, 10):
            s = stats(all_tr, bp)
            flag = "✅" if s["pf"] >= 1.10 else ("⚠️" if s["pf"] >= 1.0 else "⛔")
            L.append(f"| {bp} | {s['n']} | {s['win']} | {s['pf']} {flag} | "
                     f"{s['avg']:+} | {s['tot']:+} |")
        if split:
            L.append("\n## Walk-forward (TEST half — the honest read)\n")
            L.append("| bp | Train PF | **Test PF** | Test Win% | Test $ |")
            L.append("|---|---|---|---|---|")
            for bp in (3, 5):
                trn = stats([t for t in all_tr if t["date"] < split], bp)
                tst = stats([t for t in all_tr if t["date"] >= split], bp)
                flag = "✅" if tst["pf"] >= 1.10 else ("⚠️" if tst["pf"] >= 1.0 else "⛔")
                L.append(f"| **{bp}** | {trn['pf']} | **{tst['pf']}** {flag} | "
                         f"{tst['win']} | {tst['tot']:+} |")
            # per-symbol (broad-based check)
            L.append("\n## Per-symbol (@ 3 bp) — is the edge broad?\n")
            L.append("| Symbol | n | Win% | PF | Total$ |")
            L.append("|---|---|---|---|---|")
            from collections import defaultdict
            grp = defaultdict(list)
            for t in all_tr:
                grp[t["sym"]].append(t)
            pos = tot = 0
            for sym in sorted(grp):
                s = stats(grp[sym], 3)
                tot += 1
                if s["pf"] >= 1.0: pos += 1
                flag = "✅" if s["pf"] >= 1.10 else ("⚠️" if s["pf"] >= 1.0 else "⛔")
                L.append(f"| {sym} | {s['n']} | {s['win']} | {s['pf']} {flag} | {s['tot']:+} |")
            L.append(f"\n**{pos}/{tot} symbols PF ≥ 1.0 @3bp.**")

        # verdict
        te3 = stats([t for t in all_tr if split and t["date"] >= split], 3) if split else stats(all_tr, 3)
        te5 = stats([t for t in all_tr if split and t["date"] >= split], 5) if split else stats(all_tr, 5)
        L.append("\n## Verdict\n")
        if te3["pf"] >= 1.10 and te5["pf"] >= 1.10:
            L.append(f"**✅ CANDIDATE — Test PF {te3['pf']}@3bp / {te5['pf']}@5bp BOTH ≥ 1.10 OOS.** "
                     f"First Tier-2 orthogonal edge to clear the cost-robust gate. Next: paper "
                     f"incubation + GO_LIVE_CHECKLIST (Davey rung). NOT auto-live.")
        else:
            L.append(f"**⛔ FAILS the gate (Test PF {te3['pf']}@3bp / {te5['pf']}@5bp; need ≥1.10 at BOTH).** "
                     f"The orthogonal mean-reversion edge does NOT survive realistic costs at this "
                     f"intraday frequency either. Tier-2 (this variant) closed. Project value = the "
                     f"rigorous negative + apparatus. Either explore additional Tier-2 candidates "
                     f"(slower frequency, daily Connors, earnings-IV, overnight gap) OR accept the "
                     f"signal layer as research, not strategy. Stay paper.")
        L.append(f"\n_REAL Polygon {BACKTEST_YEARS}yr cached; pre-specified Connors RSI(2) rules; "
                 f"same gate as Tier-1. Ranks variants — not a live green light._")

    OUT_DIR.mkdir(exist_ok=True)
    fn = OUT_DIR / f"backtest_connors_{datetime.now(ET):%Y-%m-%d}.md"
    fn.write_text("\n".join(L))
    print(f"\n✓ Report → {fn}\n")
    print("\n".join(L).split("## Verdict")[-1][:900] if "## Verdict" in "\n".join(L) else L[-1])


if __name__ == "__main__":
    main()
