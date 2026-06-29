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


# Backtested per-setup reference — MIRRORS screener_engine.BT_METRICS (kept inline so
# this report stays hermetic / dependency-free). Used by the DESK-4 tracking-error check.
BT_REFERENCE = {
    "Breakout":    {"pf": 1.88, "win_pct": 51.5},
    "Bull Flag":   {"pf": 1.44, "win_pct": 61.5},
    "RSI Dip":     {"pf": 1.41, "win_pct": 53.7},
    "Gap+Vol":     {"pf": 1.37, "win_pct": 50.6},
}


def _profit_factor(pnl: list[float]) -> float:
    gains = sum(p for p in pnl if p > 0)
    losses = abs(sum(p for p in pnl if p < 0))
    return (gains / losses) if losses else float("inf")


def _risk_adjusted(rows: list[dict]) -> None:
    """DESK-10 (2026-06-29): risk-adjusted performance on the REAL book — profit
    factor, per-trade Sharpe/Sortino, and max drawdown. These are the metrics the
    GO_LIVE_CHECKLIST gates on, measured continuously on live paper (not just expectancy)."""
    pnl = [r.get("pnl_usd", 0.0) for r in rows]
    if len(pnl) < 2:
        print("── Risk-adjusted (DESK-10): too few trades\n")
        return
    mean = st.mean(pnl)
    sd = st.pstdev(pnl)
    downside = st.pstdev([min(p, 0.0) for p in pnl]) or 0.0
    sharpe = (mean / sd * (len(pnl) ** 0.5)) if sd else 0.0          # per-window Sharpe
    sortino = (mean / downside * (len(pnl) ** 0.5)) if downside else 0.0
    cum = peak = maxdd = 0.0
    for r in sorted(rows, key=lambda r: r.get("ts", "")):
        cum += r.get("pnl_usd", 0.0)
        peak = max(peak, cum)
        maxdd = min(maxdd, cum - peak)
    print("── Risk-adjusted performance (DESK-10)")
    print(f"     profit factor {_profit_factor(pnl):6.2f}")
    print(f"     Sharpe        {sharpe:6.2f}      Sortino {sortino:6.2f}   (per-trade)")
    print(f"     max drawdown  ${maxdd:>9,.0f}")
    print()


def _tracking_error(rows: list[dict]) -> None:
    """DESK-4 (2026-06-29): live-vs-backtest tracking error per setup. The screener
    promised a backtested win% / PF on each pick; this compares what actually happened.
    A desk halts a strategy on tracking-error, not on a single down day. Needs the
    `setup` field on ledger rows (DESK-5) — silently skips setups it can't attribute."""
    by_setup: dict = collections.defaultdict(list)
    for r in rows:
        s = r.get("setup")
        if s:
            by_setup[s].append(r.get("pnl_usd", 0.0))
    if not by_setup:
        print("── Tracking error (DESK-4): no per-setup data yet "
              "(ledger rows need the `setup` field — DESK-5)\n")
        return
    print("── Live-vs-backtest tracking error (DESK-4)")
    print(f"     {'setup':12s} {'n':>4} {'live WR':>8} {'bt WR':>7} {'ΔWR':>7} "
          f"{'live PF':>8} {'bt PF':>6}  flag")
    for s, pnl in sorted(by_setup.items()):
        if not pnl:
            continue
        wr = sum(1 for p in pnl if p > 0) / len(pnl) * 100
        pf = _profit_factor(pnl)
        ref = BT_REFERENCE.get(s, {})
        bt_wr = ref.get("win_pct"); bt_pf = ref.get("pf")
        dwr = (wr - bt_wr) if bt_wr is not None else None
        flag = "⚠ UNDER" if (dwr is not None and dwr <= -10) else ""
        pf_s = f"{pf:6.2f}" if pf != float("inf") else "   inf"
        print(f"     {s[:12]:12s} {len(pnl):>4} {wr:>7.1f}% "
              f"{(f'{bt_wr:.1f}%' if bt_wr is not None else '   —'):>7} "
              f"{(f'{dwr:+.1f}' if dwr is not None else '  —'):>7} "
              f"{pf_s:>8} {(f'{bt_pf:.2f}' if bt_pf is not None else '  —'):>6}  {flag}")
    print("     (ΔWR ≤ −10 pts ⇒ live materially under model — review/halt the setup)\n")


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
    _risk_adjusted(rows)      # DESK-10: risk-adjusted performance
    _tracking_error(rows)     # DESK-4: live-vs-backtest tracking error per setup


if __name__ == "__main__":
    main()
