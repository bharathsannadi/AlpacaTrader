#!/usr/bin/env python3.11
"""
universe.py — single source of truth for the tradable symbol universe.

Used by every backtest / pull / (eventually) the live router so the
symbol set is defined ONCE, not copy-pasted across scripts.

EXISTING  — the original validated-research 6 (mega-caps + SPY).
NEW       — 2026-05-19 expansion (user request). CBRS→CBRE typo-fixed.
            CRWV ~1yr / ARM ~2.5yr → partial history (expected, not error).
ALL       — EXISTING + NEW (39).
OPTIONS_SAMPLE — 8 deliberately diverse names for the options-route
            breadth re-check (sector / beta / price spread), so we don't
            pull option data for all 39.
"""
from __future__ import annotations

EXISTING = ["SPY", "AMZN", "GOOG", "MSFT", "NVDA", "META"]

NEW = [
    "CBRE", "GLW", "QQQ", "NFLX", "CRWV", "NET", "AAPL", "NOW", "SOFI",
    "HOOD", "UNH", "MU", "AMD", "ARM", "TSM", "LRCX", "AVGO", "IBM",
    "PLTR", "CRM", "ORCL", "NKE", "TEAM", "UBER", "CRWD", "ADBE", "INTC",
    "MA", "V", "WFC", "C", "BAC", "JPM",
]

# de-dupe while preserving order, in case of overlap
_seen: set[str] = set()
ALL: list[str] = [s for s in (EXISTING + NEW)
                  if not (s in _seen or _seen.add(s))]

OPTIONS_SAMPLE = ["QQQ", "AAPL", "NFLX", "JPM", "AMD", "UNH", "PLTR", "V"]

# Known partial-history names (informational; backtests just get fewer bars)
PARTIAL_HISTORY = {"CRWV": "~1yr (IPO 2025)", "ARM": "~2.5yr (IPO 2023-09)"}


if __name__ == "__main__":
    print(f"EXISTING ({len(EXISTING)}): {EXISTING}")
    print(f"NEW ({len(NEW)}): {NEW}")
    print(f"ALL ({len(ALL)}): {ALL}")
    print(f"OPTIONS_SAMPLE ({len(OPTIONS_SAMPLE)}): {OPTIONS_SAMPLE}")
    print(f"PARTIAL_HISTORY: {PARTIAL_HISTORY}")
