#!/usr/bin/env python3
"""
analyze_trades.py — Closed-trade edge report from the REAL trade ledger.

Usage:
    python scripts/analyze_trades.py                 # all history
    python scripts/analyze_trades.py 2026-06-02      # one day
    python scripts/analyze_trades.py 2026-06-02 2026-06-12   # inclusive range

Reads the authoritative closed-trade ledger `data/real_trades.jsonl` (written by
app.py's real-fill close detector, one JSON object per *real* paper close) and
answers the only question that matters: *is there an edge, and where is it
leaking?* Every row is a confirmed real fill (`dry_run` False); any simulated
row is skipped, so the report can NEVER pass off shadow P&L as real. The numbers
here should reconcile with `~/.spy_trader/equity_history.json`.

(The old autonomous-engine `journal.jsonl` is NOT read — it was a fabricated
churn log that reported +$31k while the real account was flat.)

For every population (overall, then per `kind` lane) it reports win rate,
average win/loss, payoff ratio, the break-even win rate that combination
requires, and per-trade expectancy. A lane whose expectancy is <= $0 is
flagged LOSING — that is the signal to pause or rework it, regardless of how
high its win rate looks (a 92%-win lane still bleeds if the losses are 20x the
wins). It also ranks exit reasons and per-symbol net P&L so the biggest drains
are obvious, and prints the worst equity drawdown / losing streak over the
window.

Read-only: never touches Alpaca, never places orders, never mutates the
ledger. Safe to run any time.
"""
import json
import sys
import collections
import statistics as st
from pathlib import Path

LEDGER = Path(__file__).resolve().parent.parent / "data" / "real_trades.jsonl"


def _load(date_from: str | None, date_to: str | None) -> list[dict]:
    if not LEDGER.exists():
        print(f"Real trade ledger not found: {LEDGER}")
        print("No real (paper) closes recorded yet — nothing to analyze.")
        sys.exit(0)
    rows = []
    for line in LEDGER.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("dry_run"):              # never report simulated fills as real
            continue
        day = (r.get("ts") or "")[:10]
        if date_from and day < date_from:
            continue
        if date_to and day > date_to:
            continue
        rows.append(r)
    return rows


def _stats(rows: list[dict], label: str) -> float:
    """Print one population's edge stats. Returns per-trade expectancy ($)."""
    pnl = [r.get("pnl_usd", 0.0) for r in rows]
    if not pnl:
        return 0.0
    wins = [p for p in pnl if p > 0]
    loss = [p for p in pnl if p < 0]
    flat = [p for p in pnl if p == 0]
    wr = len(wins) / len(pnl)
    exp = st.mean(pnl)
    aw = st.mean(wins) if wins else 0.0
    al = abs(st.mean(loss)) if loss else 0.0
    payoff = (aw / al) if al else float("inf")
    breakeven = (al / (aw + al)) if (aw + al) else 0.0

    verdict = "LOSING — pause/rework" if exp <= 0 else "positive edge"
    print(f"── {label}  (n={len(pnl)})  →  {verdict}")
    print(f"     win rate     {wr:6.1%}   (W{len(wins)} / L{len(loss)} / F{len(flat)})")
    print(f"     total P&L    ${sum(pnl):>10,.0f}")
    print(f"     expectancy   ${exp:>10,.1f} / trade")
    print(f"     avg win      ${aw:>10,.0f}      avg loss ${-al:>9,.0f}")
    print(f"     payoff ratio {payoff:6.2f}      break-even WR needed {breakeven:6.1%}")
    print(f"     best ${max(pnl):,.0f}   worst ${min(pnl):,.0f}")
    print()
    return exp


def _by(rows: list[dict], key, title: str, top: int, reverse: bool) -> None:
    groups: dict = collections.defaultdict(list)
    for r in rows:
        groups[key(r)].append(r.get("pnl_usd", 0.0))
    ordered = sorted(groups.items(), key=lambda kv: sum(kv[1]), reverse=reverse)
    print(f"── {title}")
    for k, v in ordered[:top]:
        print(f"     {str(k)[:34]:34s} n={len(v):4d}  net=${sum(v):>9,.0f}  avg=${st.mean(v):>7,.0f}")
    print()


def _drawdown(rows: list[dict]) -> None:
    rows = sorted(rows, key=lambda r: r.get("ts", ""))
    cum = peak = maxdd = streak = maxstreak = 0.0
    for r in rows:
        cum += r.get("pnl_usd", 0.0)
        peak = max(peak, cum)
        maxdd = min(maxdd, cum - peak)
        streak = streak + 1 if r.get("pnl_usd", 0.0) < 0 else 0
        maxstreak = max(maxstreak, streak)
    print("── Risk over the window")
    print(f"     max equity drawdown   ${maxdd:,.0f}")
    print(f"     longest losing streak {int(maxstreak)}")
    print()


def main() -> None:
    args = sys.argv[1:]
    date_from = args[0] if len(args) >= 1 else None
    date_to = args[1] if len(args) >= 2 else date_from if len(args) == 1 else None

    rows = _load(date_from, date_to)
    if not rows:
        print("No closed trades in range.")
        return

    span = f"{rows[0]['ts'][:10]} → {rows[-1]['ts'][:10]}"
    print(f"\n══ Closed-trade edge report   ({len(rows)} trades, {span}) ══\n")

    _stats(rows, "ALL LANES")
    lanes = sorted({r.get("kind", "unknown") for r in rows})
    for lane in lanes:
        _stats([r for r in rows if r.get("kind") == lane], f"lane: {lane}")

    _by(rows, lambda r: r.get("reason", "?").split(" @")[0].split(" stalled")[0],
        "Exit reasons by net P&L", top=15, reverse=True)
    _by(rows, lambda r: r.get("sym", "?"), "Worst 10 symbols (biggest drains)",
        top=10, reverse=False)
    _drawdown(rows)


if __name__ == "__main__":
    main()
