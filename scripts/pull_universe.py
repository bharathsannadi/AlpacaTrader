#!/usr/bin/env python3.11
"""
pull_universe.py — 1S-A: pull & permanently cache 3yr 5-min STOCK bars for
the full 39-ticker universe (Polygon, Desktop cache). $0 to re-run after.

Idempotent: P.stock_5m caches on disk, so re-runs hit cache and only fetch
gaps. Prints a per-symbol summary (rows / date span / FAIL) so missing or
partial-history names are visible, never silently dropped.

Run:  venv/bin/python3.11 scripts/pull_universe.py
"""
from __future__ import annotations
import sys, warnings
from pathlib import Path
from datetime import datetime, timedelta

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent))

import logging
logging.disable(logging.CRITICAL)

import polygon_data as P
from backtest_v2 import BACKTEST_YEARS
from universe import ALL, PARTIAL_HISTORY


def main() -> None:
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=BACKTEST_YEARS * 365 + 5)
             ).strftime("%Y-%m-%d")
    print(f"pull_universe — {len(ALL)} symbols, {start} → {end} "
          f"(5-min bars, Desktop-cached, $0 re-run)\n")
    ok, fail, partial = [], [], []
    for i, s in enumerate(ALL, 1):
        try:
            df = P.stock_5m(s, start, end)
        except Exception as e:
            print(f"  [{i:>2}/{len(ALL)}] {s:<5} FAIL — {e}")
            fail.append(s)
            continue
        if df is None or df.empty:
            print(f"  [{i:>2}/{len(ALL)}] {s:<5} FAIL — no data returned")
            fail.append(s)
            continue
        d0, d1 = df["begins_at"].min(), df["begins_at"].max()
        span_days = (d1 - d0).days
        tag = ""
        if s in PARTIAL_HISTORY:
            tag = f"  (partial: {PARTIAL_HISTORY[s]})"
            partial.append(s)
        elif span_days < BACKTEST_YEARS * 365 - 120:
            tag = f"  ⚠️ only ~{span_days}d history"
            partial.append(s)
        print(f"  [{i:>2}/{len(ALL)}] {s:<5} {len(df):>7} bars  "
              f"{d0:%Y-%m-%d}→{d1:%Y-%m-%d}{tag}")
        ok.append(s)

    print(f"\n=== SUMMARY ===")
    print(f"  OK:      {len(ok)}/{len(ALL)}")
    print(f"  PARTIAL: {len(partial)} {partial}")
    print(f"  FAIL:    {len(fail)} {fail}")
    if fail:
        print(f"\n  ⚠️ {len(fail)} symbol(s) returned no Polygon data — "
              f"verify ticker validity / entitlement before relying on them.")
    print(f"\n✓ Stock cache populated. Cache: {P.cache_stats()}")


if __name__ == "__main__":
    main()
