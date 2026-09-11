#!/usr/bin/env python3
"""
daily_report.py — end-of-day edge report from the REAL closed-trade ledger.

Usage:
    python scripts/daily_report.py                # today (ET)
    python scripts/daily_report.py 2026-09-11     # one day
    python scripts/daily_report.py 2026-06-01 2026-09-11   # inclusive range
    python scripts/daily_report.py --since 30     # trailing N days

Complements analyze_trades.py. That script answers "is there an edge"; this one
answers "what did the EXIT LAYER do to it today", which is where this book was
measured to leak (ledger review 2026-09-11: realized +$1,426 against −$1,038
open over 165 closes, profit factor 1.14, the top 3 winners carrying everything).

Three things it reports that analyze_trades.py does not:

  1. COALESCED exits. A single market order that fills in chunks lands as several
     ledger rows — PLTR 2026-06-18 logged five "trades" at 09:35 (q=21/1/4/4/7),
     all the same exit. Counting rows overstates trade count by ~30% (165 rows →
     127 real exits) and distorts win rate and average size. Rows within
     COALESCE_WINDOW_MIN of each other on one symbol are folded into one exit.

  2. STOP DISCIPLINE. Every exit worse than the configured stop, with the excess
     loss beyond a clean stop priced in dollars. This is the number that pays for
     fixing the exit layer.

  3. GIVE-BACK. peak_pct (added 2026-09-11) records the best unrealized gain a
     position ever showed, so give_back = peak − exit tells you how much of each
     winner the exit logic handed back. Rows written before that date have no
     peak and are reported separately rather than silently counted as zero.

Read-only: never touches Alpaca, never places orders, never mutates the ledger.
Exit code is always 0 so a scheduled run never trips a supervisor.
"""
from __future__ import annotations

import json
import sys
import collections
import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))

ET = ZoneInfo("America/New_York")
LEDGER = Path(__file__).resolve().parent.parent / "data" / "real_trades.jsonl"

# Fills of one order can straddle tick boundaries; anything longer apart than
# this on the same symbol is a genuinely separate exit, not a fragment.
COALESCE_WINDOW_MIN = 10


def _stop_pct() -> float:
    try:
        import auto_engine
        return float(auto_engine.STOCK_STOP_PCT) * 100
    except Exception:
        return 3.0


def _load(lo: str | None, hi: str | None) -> list[dict]:
    if not LEDGER.exists():
        return []
    out = []
    for line in LEDGER.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("dry_run"):           # never pass simulated fills off as real
            continue
        day = (r.get("ts") or "")[:10]
        if (lo and day < lo) or (hi and day > hi):
            continue
        out.append(r)
    out.sort(key=lambda r: r.get("ts", ""))
    return out


def _coalesce(rows: list[dict]) -> list[dict]:
    """Fold partial fills of one order back into a single logical exit."""
    groups: list[dict] = []
    cur: dict | None = None
    for r in rows:
        try:
            t = dt.datetime.fromisoformat(r["ts"])
        except Exception:
            continue
        if (cur and cur["sym"] == r["sym"]
                and (t - cur["_end"]).total_seconds() <= COALESCE_WINDOW_MIN * 60):
            cur["rows"].append(r)
            cur["_end"] = t
        else:
            if cur:
                groups.append(cur)
            cur = {"sym": r["sym"], "rows": [r], "_end": t, "_start": t}
    if cur:
        groups.append(cur)
    for g in groups:
        rs = g["rows"]
        qty = sum(int(r.get("qty") or 0) for r in rs)
        g["qty"] = qty
        g["pnl_usd"] = round(sum(float(r.get("pnl_usd") or 0.0) for r in rs), 2)
        # size-weighted, so a 1-share fragment can't swing the exit's percentage
        g["pnl_pct"] = round(
            sum(float(r.get("pnl_pct") or 0.0) * int(r.get("qty") or 0) for r in rs) / qty, 2
        ) if qty else 0.0
        peaks = [float(r["peak_pct"]) for r in rs if r.get("peak_pct") is not None]
        g["peak_pct"] = max(peaks) if peaks else None
        g["setup"] = next((r.get("setup") for r in rs if r.get("setup")), "")
        g["ts"] = rs[0].get("ts", "")
        g["fragments"] = len(rs)
    return groups


def _money(v: float) -> str:
    return f"${v:,.2f}"


def _section(title: str) -> None:
    print(f"\n\033[1m{title}\033[0m")
    print("─" * len(title))


def report(lo: str | None, hi: str | None) -> None:
    rows = _load(lo, hi)
    span = f"{lo or 'start'} → {hi or 'today'}"
    print(f"\n\033[1mDAILY EDGE REPORT  ·  {span}\033[0m")
    if not rows:
        print("\nNo real closes in this window. Nothing to analyse.")
        return
    ex = _coalesce(rows)
    frag = sum(1 for g in ex if g["fragments"] > 1)

    # ── headline ──
    _section("P&L")
    tot = sum(g["pnl_usd"] for g in ex)
    wins = [g for g in ex if g["pnl_usd"] > 0]
    loss = [g for g in ex if g["pnl_usd"] <= 0]
    gw = sum(g["pnl_usd"] for g in wins)
    gl = sum(g["pnl_usd"] for g in loss)
    pf = (gw / abs(gl)) if gl else float("inf")
    print(f"  Net               {_money(tot)}")
    print(f"  Exits             {len(ex)}  (from {len(rows)} ledger rows; "
          f"{frag} were split fills)")
    print(f"  Win rate          {100*len(wins)/len(ex):.1f}%   "
          f"({len(wins)}W / {len(loss)}L)")
    print(f"  Gross win/loss    {_money(gw)} / {_money(gl)}")
    print(f"  Profit factor     {pf:.2f}" + ("   ⚠ below 1.0 — losing" if pf < 1 else ""))
    if wins and loss:
        aw = gw / len(wins)
        al = gl / len(loss)
        print(f"  Avg win/loss      {_money(aw)} / {_money(al)}   payoff {abs(aw/al):.2f}")
        be = abs(al) / (aw + abs(al)) * 100
        print(f"  Breakeven win%    {be:.1f}%  (actual {100*len(wins)/len(ex):.1f}%)")
    print(f"  Expectancy/exit   {_money(tot/len(ex))}")
    med = sorted(g["pnl_usd"] for g in ex)[len(ex) // 2]
    print(f"  Median exit       {_money(med)}")

    # Concentration: is the result carried by a couple of trades?
    if len(ex) >= 5:
        top = sorted(ex, key=lambda g: g["pnl_usd"], reverse=True)[:3]
        t3 = sum(g["pnl_usd"] for g in top)
        print(f"  Top-3 winners     {_money(t3)}   without them: {_money(tot - t3)}"
              + ("   ⚠ the result is a few outliers" if tot > 0 and tot - t3 < 0 else ""))

    # ── stop discipline ──
    _section("STOP DISCIPLINE")
    sl = _stop_pct()
    blown = [g for g in ex if g["pnl_pct"] < -(sl + 0.5)]
    print(f"  Configured stop   -{sl:.1f}%")
    if not blown:
        print("  No exit breached the stop band. ✓")
    else:
        excess = sum(g["pnl_usd"] - (g["pnl_usd"] * sl / abs(g["pnl_pct"])) for g in blown)
        print(f"  Breached          {len(blown)} of {len(ex)} exits, "
              f"{_money(sum(g['pnl_usd'] for g in blown))}")
        print(f"  Excess vs clean   {_money(excess)}  ← recoverable by the exit layer")
        for g in sorted(blown, key=lambda g: g["pnl_pct"])[:8]:
            print(f"    {g['ts'][:16]}  {g['sym']:6s} {g['pnl_pct']:>7.1f}%  "
                  f"{_money(g['pnl_usd']):>12}  {g['setup'] or 'legacy'}")

    # ── give-back ──
    _section("GIVE-BACK  (peak gain handed back before exit)")
    have = [g for g in ex if g["peak_pct"] is not None]
    if not have:
        print("  No exit in this window carries peak_pct.")
        print("  (Instrumented 2026-09-11 — only closes after that date have it.)")
    else:
        gb = [(g, g["peak_pct"] - g["pnl_pct"]) for g in have]
        gave = [(g, d) for g, d in gb if d >= 1.0]
        print(f"  Exits with peak   {len(have)} of {len(ex)}")
        if gave:
            print(f"  Gave back ≥1%     {len(gave)}")
            for g, d in sorted(gave, key=lambda x: -x[1])[:8]:
                print(f"    {g['sym']:6s} peaked +{g['peak_pct']:.1f}% → exited "
                      f"{g['pnl_pct']:+.1f}%  (gave back {d:.1f}pp)  {g['setup'] or ''}")
        else:
            print("  No exit gave back 1pp or more. ✓")
        roundtrip = [g for g, d in gb if g["peak_pct"] >= 3.0 and g["pnl_pct"] <= 0.5]
        if roundtrip:
            print(f"  ⚠ {len(roundtrip)} position(s) ran ≥+3% and still closed flat or "
                  f"negative — the profit floor is engaging too late.")

    # ── churn ──
    _section("CHURN")
    noise = [g for g in ex if abs(g["pnl_pct"]) < 1.0]
    print(f"  Exits inside ±1%  {len(noise)} of {len(ex)} "
          f"({100*len(noise)/len(ex):.0f}%), net {_money(sum(g['pnl_usd'] for g in noise))}")
    if len(noise) / len(ex) > 0.25:
        print("  ⚠ Over a quarter of activity is noise — spread and slippage with no thesis.")

    # ── attribution ──
    _section("BY SETUP")
    by = collections.defaultdict(list)
    for g in ex:
        by[g["setup"] or "(untagged)"].append(g)
    for k, v in sorted(by.items(), key=lambda x: sum(g["pnl_usd"] for g in x[1])):
        w = sum(1 for g in v if g["pnl_usd"] > 0)
        print(f"  {k:16s} n={len(v):3d}  {_money(sum(g['pnl_usd'] for g in v)):>12}  "
              f"win {100*w/len(v):5.1f}%")

    _section("BY SYMBOL  (worst first)")
    bs = collections.defaultdict(list)
    for g in ex:
        bs[g["sym"]].append(g)
    ranked = sorted(bs.items(), key=lambda x: sum(g["pnl_usd"] for g in x[1]))
    for k, v in ranked[:8]:
        w = sum(1 for g in v if g["pnl_usd"] > 0)
        flag = "   ⚠ repeat loser" if len(v) >= 3 and w <= 1 else ""
        print(f"  {k:6s} n={len(v):2d}  {_money(sum(g['pnl_usd'] for g in v)):>12}  "
              f"{w}W/{len(v)-w}L{flag}")
    if len(ranked) > 10:
        print("  …")
        for k, v in ranked[-2:]:
            w = sum(1 for g in v if g["pnl_usd"] > 0)
            print(f"  {k:6s} n={len(v):2d}  {_money(sum(g['pnl_usd'] for g in v)):>12}  "
                  f"{w}W/{len(v)-w}L")
    print()


def main() -> None:
    args = [a for a in sys.argv[1:] if a]
    today = dt.datetime.now(ET).date().isoformat()
    lo = hi = None
    if not args:
        lo = hi = today
    elif args[0] == "--since" and len(args) > 1:
        try:
            lo = (dt.datetime.now(ET).date() - dt.timedelta(days=int(args[1]))).isoformat()
        except ValueError:
            lo = None
    elif args[0] == "--all":
        lo = hi = None
    elif len(args) == 1:
        lo = hi = args[0]
    else:
        lo, hi = args[0], args[1]
    try:
        report(lo, hi)
    except Exception as e:                     # never trip a scheduled run
        print(f"daily_report failed: {e}")


if __name__ == "__main__":
    main()
