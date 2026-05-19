#!/usr/bin/env python3.11
"""
pull_sp500.py — 1S-A(full): pull & permanently cache 3yr 5-min STOCK bars
for the full S&P 500 (authoritative list in scripts/sp500.json). $0 to
re-run after Polygon is cancelled (disk cache on Desktop).

Idempotent: P.stock_5m caches on disk; re-runs only fetch gaps. Prints a
per-symbol line + a SUMMARY so any FAIL/partial is visible, never silently
dropped. Resumable — just re-run; cached symbols return instantly.

Run:  nohup venv/bin/python3.11 scripts/pull_sp500.py > /tmp/pull_sp500.log 2>&1 &
"""
from __future__ import annotations
import sys, json, warnings
from pathlib import Path
from datetime import datetime, timedelta

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent))
import logging
logging.disable(logging.CRITICAL)

import polygon_data as P
from backtest_v2 import BACKTEST_YEARS

SP500 = json.loads((Path(__file__).parent / "sp500.json").read_text())


def main() -> None:
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=BACKTEST_YEARS * 365 + 5)
             ).strftime("%Y-%m-%d")
    print(f"pull_sp500 — {len(SP500)} symbols, {start} → {end} "
          f"(5-min bars, Desktop-cached, $0 re-run, resumable)\n", flush=True)
    ok, fail, partial = [], [], []
    for i, s in enumerate(SP500, 1):
        try:
            df = P.stock_5m(s, start, end)
        except Exception as e:
            print(f"  [{i:>3}/{len(SP500)}] {s:<6} FAIL — {e}", flush=True)
            fail.append(s); continue
        if df is None or df.empty:
            print(f"  [{i:>3}/{len(SP500)}] {s:<6} FAIL — no data", flush=True)
            fail.append(s); continue
        d0, d1 = df["begins_at"].min(), df["begins_at"].max()
        span = (d1 - d0).days
        tag = ""
        if span < BACKTEST_YEARS * 365 - 120:
            tag = f"  ⚠️ ~{span}d only (recent IPO/listing)"
            partial.append(s)
        print(f"  [{i:>3}/{len(SP500)}] {s:<6} {len(df):>7} bars  "
              f"{d0:%Y-%m-%d}→{d1:%Y-%m-%d}{tag}", flush=True)
        ok.append(s)

    print(f"\n=== SUMMARY ===", flush=True)
    print(f"  OK:      {len(ok)}/{len(SP500)}")
    print(f"  PARTIAL: {len(partial)} {partial}")
    print(f"  FAIL:    {len(fail)} {fail}")
    if fail:
        print(f"\n  ⚠️ {len(fail)} symbol(s) returned no data — likely ticker"
              f" format (e.g. class shares) or no Polygon entitlement. "
              f"Verify BEFORE cancelling Polygon (these are unrecoverable after).")
    print(f"\n✓ Stock cache: {P.cache_stats()}", flush=True)
    print("  Backup is the permanent disk cache at "
          "~/Desktop/AlpacaTrader_Data/polygon_cache — do NOT cancel "
          "Polygon until OK count is acceptable.", flush=True)


if __name__ == "__main__":
    main()
