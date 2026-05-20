#!/usr/bin/env python3.11
"""
bkb_cache_only.py — parallel-safe option-cache filler.

Runs the SAME per-symbol logic as backtest_structures.backtest_symbol()
but skips report writing — purpose is purely to populate the permanent
Desktop cache before Polygon cancellation. Idempotent (cache writes are
filename-keyed). Safe to run alongside backtest_structures.py — both
hit the same on-disk cache, last-write-wins (data is identical).

Usage:
    venv/bin/python3.11 scripts/bkb_cache_only.py SYM [SYM ...]
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import logging, warnings
warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)

from backtest_structures import backtest_symbol


def main():
    syms = [s.upper() for a in sys.argv[1:] for s in a.split()]
    if not syms:
        print("usage: bkb_cache_only.py SYM [SYM ...]", file=sys.stderr)
        sys.exit(2)
    print(f"bkb_cache_only — caching {len(syms)} symbol(s): {syms}",
          flush=True)
    for s in syms:
        print(f"  {s} … start", flush=True)
        try:
            r = backtest_symbol(s)
            if "error" in r:
                print(f"  {s} … FAIL: {r['error']}", flush=True)
            else:
                c = {k: len(v) for k, v in r["trades"].items()}
                print(f"  {s} … done  {r['days']}d  {c}", flush=True)
        except Exception as e:
            print(f"  {s} … EXCEPTION: {e}", flush=True)
    print("✓ workers done — option cache filled.", flush=True)


if __name__ == "__main__":
    main()
