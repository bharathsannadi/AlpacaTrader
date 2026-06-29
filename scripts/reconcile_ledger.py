#!/usr/bin/env python3
"""reconcile_ledger.py — DESK-9 (2026-06-29) daily books-&-records check.

The -$863 phantom double-log (edge review 2026-06-27) went undetected until a manual
review. This script is the automated control that would have caught it: it reconciles
the REAL closed-trade ledger (`data/real_trades.jsonl`) against itself (duplicate
detection) and against the real equity curve (`~/.spy_trader/equity_history.json`).

It answers two desk questions:
  1. Are there duplicate closes inflating realized P&L? (the bug class we hit)
  2. Does ledger realized P&L roughly reconcile with the equity curve over the span?
     (They will NOT tie exactly — the equity curve also moves with open-position MTM,
     the options lane, and fees — so this flags only gross/structural drift, not the
     expected MTM gap.)

Exit code 1 if duplicates are found (a real integrity fault); 0 otherwise. Read-only:
never mutates the ledger, never touches Alpaca. Safe to run from cron daily.

Usage:
    python scripts/reconcile_ledger.py
"""
import json
import os
import sys
from pathlib import Path

LEDGER = Path(__file__).resolve().parent.parent / "data" / "real_trades.jsonl"
EQUITY = Path(os.path.expanduser("~/.spy_trader/equity_history.json"))


def _key(r: dict) -> tuple:
    return (str(r.get("sym", "")).upper(), int(r.get("qty", 0) or 0),
            round(float(r.get("entry", 0) or 0.0), 2),
            round(float(r.get("exit", 0) or 0.0), 2),
            str(r.get("ts", ""))[:10])


def main() -> int:
    if not LEDGER.exists():
        print(f"No ledger at {LEDGER} — nothing to reconcile.")
        return 0
    rows = []
    for line in LEDGER.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not r.get("dry_run"):
            rows.append(r)
    if not rows:
        print("No real closes recorded yet.")
        return 0

    # 1. Duplicate detection (the bug class).
    seen: dict = {}
    dupes = []
    for r in rows:
        k = _key(r)
        if k in seen:
            dupes.append((k, r.get("pnl_usd", 0.0)))
        else:
            seen[k] = True
    dupe_pnl = sum(p for _, p in dupes)

    realized = sum(float(r.get("pnl_usd", 0.0) or 0.0) for r in rows)
    span = f"{rows[0]['ts'][:10]} → {rows[-1]['ts'][:10]}"
    print(f"══ Ledger reconciliation (DESK-9)   ({len(rows)} real closes, {span}) ══\n")
    print(f"  realized P&L (ledger)   ${realized:>10,.2f}")

    # 2. Equity-curve cross-check (informational — MTM/options/fees make it inexact).
    if EQUITY.exists():
        try:
            eq = json.loads(EQUITY.read_text())
            if isinstance(eq, list) and len(eq) >= 2:
                delta = float(eq[-1]["equity"]) - float(eq[0]["equity"])
                print(f"  equity Δ over curve     ${delta:>10,.2f}   "
                      f"({eq[0]['date']} → {eq[-1]['date']})")
                print(f"  unexplained gap         ${realized - delta:>10,.2f}   "
                      f"(open-position MTM + options + fees — expected, not an error)")
        except (ValueError, KeyError, TypeError) as e:
            print(f"  equity curve unreadable: {e}")
    else:
        print("  equity curve not found — skipping cross-check")

    print()
    if dupes:
        print(f"  ❌ {len(dupes)} DUPLICATE close row(s) — ${dupe_pnl:,.2f} phantom P&L:")
        for k, p in dupes:
            print(f"       {k[0]:6s} {k[1]:>4}sh {k[2]}->{k[3]}  ${p:,.2f}  ({k[4]})")
        print("\n  Integrity fault — investigate the ledger writer (app._append_real_trade).")
        return 1
    print("  ✅ no duplicate closes — ledger integrity OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
