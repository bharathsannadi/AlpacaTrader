#!/usr/bin/env python3.11
"""
backtest_structures.py — STRUCTURE comparison (the user's question made testable).

backtest_v2 sweeps EXIT variants on ONE structure (7-14 DTE naked ATM).
This asks the deeper question: the vwap_momentum SIGNAL has proven
directional edge on the underlying (signal_diagnostic: 55→60% hit-rate,
+0.62 ATR @60min). Does ANY option/share STRUCTURE convert that edge into
net-positive P&L after real costs — or only shares?

Same entries (vwap_momentum only — the one signal with proven edge).
4 structures, identical signals, real Polygon 3yr data, $0 (cached):

  S0_naked_short   7-14 DTE ATM naked, premium-% exit (50% stop / +100%
                   / 60min)  ← CURRENT PRODUCTION (the 2/10 baseline)
  S1_naked_long    25-45 DTE ATM naked, exit on UNDERLYING ATR (adverse
                   1.0×ATR stop / favorable 1.5×ATR target)  ← lever #1+#3
                   (less theta + spot-defined invalidation)
  S2_debit_spread  25-45 DTE: long ATM + short OTM (~1×ATR out), exit on
                   spot ATR  ← KB §5 (nets out theta + vega)
  S3_shares        underlying itself, ATR stop/target  ← CONTROL: zero
                   theta/vega/spread-tax; the edge's purest expression

Headline metric = Profit Factor (scale-invariant, comparable across
structures regardless of sizing). Walk-forward 50/50; ranked by TEST PF.

Run:  venv/bin/python3.11 scripts/backtest_structures.py
      venv/bin/python3.11 scripts/backtest_structures.py SPY NVDA
"""
from __future__ import annotations
import sys, warnings
from pathlib import Path
from datetime import datetime, timedelta

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent))

import logging
logging.disable(logging.CRITICAL)      # silence the live evaluator's per-bar
                                       # no-fire chatter (huge over 3yr×6 syms)

import numpy as np
import pandas as pd
import spy_auto_trader as T
import polygon_data as P
from backtest_v2 import (replay_day, fetch_5m, BACKTEST_YEARS,
                          FEE_PER_CONTRACT, SPREAD_PCT_OF_MID, _opt_px_at)

ET = T.ET
SYMBOLS_DEFAULT = ["SPY", "AMZN", "GOOG", "MSFT", "NVDA", "META"]
OUT_DIR = Path(__file__).parent.parent / "backtest_results"

# Per-trade risk budget — user's profile: 4% of $5K = $200 max loss/trade.
# Shares are sized so the ATR stop ≈ this $ loss, making $ P&L (and PF)
# directly comparable to a 1-contract option position with defined risk.
RISK_BUDGET   = 200.0
SHARE_SLIP_BP = 1.0          # 1 bp round-trip share slippage (very liquid names)

# ATR-based exit (used by S1/S2/S3) — grounded in signal_diagnostic:
# measured favorable excursion +0.34 ATR @30m, +0.62 ATR @60m. Target set
# beyond the measured edge so the winners are actually captured; stop at
# 1.0 ATR = the signal-invalidation distance (spot has gone the wrong way).
ATR_STOP_M = 1.0
ATR_TGT_M  = 1.5
TIME_CAP_MIN = 90            # hard time cap (edge is intraday; don't hold to EOD blindly)

STRUCTURES = ["S0_naked_short", "S1_naked_long", "S2_debit_spread", "S3_shares"]


def _atr_exit_spot(di, entry_i, direction, spot0, atr0):
    """Walk the UNDERLYING forward; return (exit_spot, bars_held, why) on
    adverse-1.0×ATR stop / favorable-1.5×ATR target / time cap / EOD."""
    n = len(di)
    t0 = di["begins_at"].iloc[entry_i]
    for j in range(entry_i + 1, n):
        bar = di.iloc[j]
        spot = float(bar["close_price"])
        held = (bar["begins_at"] - t0).total_seconds() / 60.0
        adverse = (spot0 - spot) if direction == "bull" else (spot - spot0)
        favor   = (spot - spot0) if direction == "bull" else (spot0 - spot)
        if adverse >= ATR_STOP_M * atr0:
            return spot, j - entry_i, "atr_stop"
        if favor >= ATR_TGT_M * atr0:
            return spot, j - entry_i, "atr_tgt"
        if held >= TIME_CAP_MIN:
            return spot, j - entry_i, "time_cap"
    return float(di["close_price"].iloc[-1]), n - 1 - entry_i, "eod"


def _premium_exit(oh, di, entry_i, entry_opt, t0):
    """Mirror current production: 50% premium stop / +100% target / 60-min
    stall stop / EOD — on the REAL option OHLC."""
    n = len(di)
    last = entry_opt
    for j in range(entry_i + 1, n):
        ts = di["begins_at"].iloc[j]
        opt = _opt_px_at(oh, ts)
        if opt is None:
            opt = last
        last = opt
        chg = (opt - entry_opt) / entry_opt
        held = (ts - t0).total_seconds() / 60.0
        if chg <= -T.STOP_LOSS_PCT:           return opt, j - entry_i, "stop"
        if chg >=  T.PROFIT_TARGET:           return opt, j - entry_i, "t2"
        if held >= T.TIME_STOP_MINS and -0.15 <= chg <= 0.10:
            return opt, j - entry_i, "time_stop"
    return (_opt_px_at(oh, di["begins_at"].iloc[-1]) or last,
            n - 1 - entry_i, "eod")


def _short_leg_strike(spot, atr, direction):
    """OTM short strike for the debit spread ≈ 1×ATR beyond ATM, rounded to
    a $1 strike (mega-caps have $1 strikes near the money)."""
    off = max(1, round(atr))
    return round(spot) + off if direction == "bull" else round(spot) - off


def backtest_symbol(symbol: str) -> dict:
    df = fetch_5m(symbol)
    if df is None or df.empty:
        return {"symbol": symbol, "error": "no data"}
    df["day"] = df["begins_at"].dt.date
    days = sorted(df["day"].unique())
    trades = {s: [] for s in STRUCTURES}

    for d in days:
        day_df = df[df["day"] == d].drop(columns="day").reset_index(drop=True)
        di = T._add_indicators(day_df.copy()).reset_index(drop=True)
        n = len(di)
        for i, bar, direction, reason, sigcls in replay_day(day_df):
            if sigcls != "vwap_momentum":      # proven-edge signal ONLY
                continue
            if i >= n:
                continue
            spot0 = float(di["close_price"].iloc[i])
            atr0 = float(di["atr"].iloc[i]) if not np.isnan(di["atr"].iloc[i]) else None
            if not atr0 or atr0 <= 0:
                continue
            t0 = di["begins_at"].iloc[i]

            # ---- S3 shares (control: zero theta/vega) --------------------
            ex_spot, _, why = _atr_exit_spot(di, i, direction, spot0, atr0)
            stop_dist = ATR_STOP_M * atr0
            shares = max(1.0, RISK_BUDGET / stop_dist)     # size to $200 stop
            sgn = 1.0 if direction == "bull" else -1.0
            slip = (spot0 + ex_spot) * (SHARE_SLIP_BP / 1e4)
            pnl = sgn * (ex_spot - spot0) * shares - slip * shares
            trades["S3_shares"].append({"sym": symbol, "date": str(d),
                "dir": direction, "pnl": round(pnl, 2), "why": why})

            # ---- option structures need a real tradable contract --------
            cS = P.pick_atm(symbol, str(d), spot0, direction, 7, 14)   # S0
            cL = P.pick_atm(symbol, str(d), spot0, direction, 25, 45)  # S1/S2

            if cS is not None:
                oh = cS["_ohlc"]
                e = _opt_px_at(oh, t0)
                if e is not None and e >= 0.30:
                    ef = e * (1 + SPREAD_PCT_OF_MID)
                    xo, _, w = _premium_exit(oh, di, i, e, t0)
                    xf = xo * (1 - SPREAD_PCT_OF_MID)
                    pnl = (xf - ef) * 100 - 2 * FEE_PER_CONTRACT
                    trades["S0_naked_short"].append({"sym": symbol,
                        "date": str(d), "dir": direction,
                        "pnl": round(pnl, 2), "why": w})

            if cL is not None:
                ohL = cL["_ohlc"]
                eL = _opt_px_at(ohL, t0)
                if eL is not None and eL >= 0.30:
                    # exit time is decided by the UNDERLYING ATR rule; price
                    # the option leg(s) at that exit bar.
                    _, held, w = _atr_exit_spot(di, i, direction, spot0, atr0)
                    ex_i = min(i + held, n - 1)
                    ts_x = di["begins_at"].iloc[ex_i]
                    xL = _opt_px_at(ohL, ts_x)
                    if xL is not None:
                        # S1 naked long (25-45 DTE), ATR-timed exit
                        efL = eL * (1 + SPREAD_PCT_OF_MID)
                        xfL = xL * (1 - SPREAD_PCT_OF_MID)
                        pnl = (xfL - efL) * 100 - 2 * FEE_PER_CONTRACT
                        trades["S1_naked_long"].append({"sym": symbol,
                            "date": str(d), "dir": direction,
                            "pnl": round(pnl, 2), "why": w})

                        # S2 debit spread: long cL − short OTM, same expiry
                        ks = _short_leg_strike(spot0, atr0, direction)
                        from datetime import datetime as _dt
                        exp = _dt.strptime(cL["expiration_date"],
                                           "%Y-%m-%d").date()
                        socc = P._occ(symbol, exp, cL["contract_type"], ks)
                        ohS = P.option_ohlc(socc, str(d))
                        if ohS is not None and len(ohS) >= 3:
                            sE = _opt_px_at(ohS, t0)
                            sX = _opt_px_at(ohS, ts_x)
                            if sE is not None and sX is not None and sE > 0:
                                # net debit = pay long ask, collect short bid
                                net_e = (eL * (1 + SPREAD_PCT_OF_MID)
                                         - sE * (1 - SPREAD_PCT_OF_MID))
                                net_x = (xL * (1 - SPREAD_PCT_OF_MID)
                                         - sX * (1 + SPREAD_PCT_OF_MID))
                                if net_e > 0:
                                    pnl = ((net_x - net_e) * 100
                                           - 4 * FEE_PER_CONTRACT)  # 2 legs RT
                                    trades["S2_debit_spread"].append(
                                        {"sym": symbol, "date": str(d),
                                         "dir": direction,
                                         "pnl": round(pnl, 2), "why": w})
    return {"symbol": symbol, "trades": trades, "days": len(days)}


def _stats(tr: list[dict]) -> dict:
    if not tr:
        return {"n": 0, "win": 0, "pf": 0, "avg": 0, "tot": 0, "mdd": 0}
    p = [t["pnl"] for t in tr]
    gw = sum(x for x in p if x > 0)
    gl = abs(sum(x for x in p if x < 0))
    eq = peak = mdd = 0.0
    for x in p:
        eq += x; peak = max(peak, eq); mdd = min(mdd, eq - peak)
    return {"n": len(tr),
            "win": round(sum(1 for x in p if x > 0) / len(p) * 100, 1),
            "pf": round(gw / gl, 2) if gl else (99.9 if gw else 0),
            "avg": round(sum(p) / len(p), 2),
            "tot": round(sum(p), 0), "mdd": round(mdd, 0)}


def build_report(results: list[dict]) -> str:
    allt = {s: [] for s in STRUCTURES}
    for r in results:
        if "trades" not in r:
            continue
        for s in STRUCTURES:
            allt[s].extend(r["trades"][s])

    L = [f"# Structure Comparison — REAL Polygon {BACKTEST_YEARS}yr\n",
         f"_Generated {datetime.now(ET):%Y-%m-%d %H:%M ET}_\n",
         "Same **vwap_momentum** entries (the one signal with proven "
         "directional edge — signal_diagnostic: 55→60% hit-rate, +0.62 "
         "ATR @60m) run through 4 structures. Headline = **Profit Factor** "
         "(scale-invariant). $ P&L sized to a $200/trade risk budget so "
         "shares vs options are directly comparable. Costs: options ±2% "
         "half-spread + $0.65/contract RT; shares 1bp slippage.\n",
         "## Walk-forward (50/50 split, ranked by TEST PF)\n",
         "| Structure | n | Train PF | **Test PF** | Test Win% | "
         "Test Avg$ | Test Total$ | Test MaxDD$ |",
         "|---|---|---|---|---|---|---|---|"]

    dates = sorted({t["date"] for t in allt["S3_shares"]}) if allt["S3_shares"] else []
    split = dates[len(dates) // 2] if len(dates) >= 4 else None
    rows = []
    for s in STRUCTURES:
        tr = allt[s]
        if not tr or split is None:
            rows.append((s, 0, 0, _stats([]))); continue
        trn = _stats([t for t in tr if t["date"] < split])
        tst = _stats([t for t in tr if t["date"] >= split])
        rows.append((s, tst["pf"], trn["pf"], tst))
    rows.sort(key=lambda r: -r[1])
    label = {"S0_naked_short": "S0 naked 7-14d (CURRENT)",
             "S1_naked_long": "S1 naked 25-45d +ATR-exit",
             "S2_debit_spread": "S2 debit spread +ATR-exit",
             "S3_shares": "S3 shares (control)"}
    for s, tpf, rpf, t in rows:
        L.append(f"| {label[s]} | {t['n']} | {rpf} | **{tpf}** | "
                 f"{t['win']} | {t['avg']:+} | {t['tot']:+} | {t['mdd']} |")

    base = next((r for r in rows if r[0] == "S0_naked_short"), None)
    best = rows[0] if rows else None
    L.append("\n## Verdict\n")
    if not best or best[3]["n"] == 0:
        L.append("**No trades** — cannot assess.")
    else:
        s0 = base[1] if base else 0
        L.append(f"- **Current production (S0)** Test PF = **{s0}** "
                 f"{'(net-negative — confirms the 2/10)' if s0 < 1 else ''}.")
        bs, bpf = best[0], best[1]
        if bpf < 1.0:
            L.append(f"- **Every structure loses OOS** (best {label[bs]} "
                     f"PF {bpf} < 1.0). The proven directional edge does "
                     f"**not** survive ANY of these wrappers after real "
                     f"costs — including shares. That would mean the "
                     f"underlying-only excursion edge is real but too small "
                     f"to clear costs at this signal frequency → the fix is "
                     f"signal SELECTIVITY, not structure.")
        elif bs == "S3_shares":
            L.append(f"- **Shares (S3) is the only/best positive structure "
                     f"(Test PF {bpf}).** This confirms the diagnosis "
                     f"exactly: the edge is a STOCK edge; every option "
                     f"wrapper (theta/vega/spread) destroys it. Actionable "
                     f"→ build the shares/ETF swing path; drop options.")
        else:
            beat = " — and BEATS current S0" if bpf > s0 else ""
            L.append(f"- **{label[bs]} is the best structure (Test PF "
                     f"{bpf}){beat}.** A redesigned option structure DOES "
                     f"monetize the edge → this is the Structure-fit fix; "
                     f"next step is parameter-robustness + GO_LIVE_CHECKLIST.")
        L.append("\n_REAL Polygon 3yr, real option OHLC, conservative "
                 "modeled spread. Not a go-live signal on its own — "
                 "ranks structures; the winner still needs robustness + "
                 "true-NBBO sensitivity + GO_LIVE_CHECKLIST._")
    return "\n".join(L)


def _resolve_syms(argv: list[str]) -> list[str]:
    """ALL→universe.ALL, SAMPLE→universe.OPTIONS_SAMPLE, else space-safe
    (defangs the zsh single-arg footgun). No args → SYMBOLS_DEFAULT."""
    toks: list[str] = []
    for a in argv:
        toks += a.split()
    toks = [t.upper() for t in toks]
    if not toks:
        return list(SYMBOLS_DEFAULT)
    if toks == ["ALL"]:
        from universe import ALL
        return list(ALL)
    if toks == ["SAMPLE"]:
        from universe import OPTIONS_SAMPLE
        return list(OPTIONS_SAMPLE)
    seen: set[str] = set()
    return [t for t in toks if not (t in seen or seen.add(t))]


def main():
    syms = _resolve_syms(sys.argv[1:])
    print(f"backtest_structures — {syms} — REAL {BACKTEST_YEARS}yr "
          f"(cached, $0)\n")
    results = []
    for s in syms:
        print(f"  {s} …", end=" ", flush=True)
        r = backtest_symbol(s)
        if "error" in r:
            print(r["error"])
        else:
            cnt = {k: len(v) for k, v in r["trades"].items()}
            print(f"{r['days']}d  {cnt}")
        results.append(r)
    OUT_DIR.mkdir(exist_ok=True)
    rep = build_report(results)
    fn = OUT_DIR / f"backtest_structures_{datetime.now(ET):%Y-%m-%d}.md"
    fn.write_text(rep)
    print(f"\n✓ Report → {fn}\n")
    print(rep.split("## Verdict")[-1][:1200])


if __name__ == "__main__":
    main()
