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

EXISTING = ["SPY", "AMZN", "GOOG", "MSFT", "NVDA", "META", "IWM"]

NEW = [
    "CBRE", "GLW", "QQQ", "NFLX", "CRWV", "NET", "AAPL", "NOW", "SOFI",
    "HOOD", "UNH", "MU", "AMD", "ARM", "TSM", "LRCX", "AVGO", "IBM",
    "PLTR", "CRM", "ORCL", "NKE", "TEAM", "UBER", "CRWD", "ADBE", "INTC",
    "MA", "V", "WFC", "C", "BAC", "JPM",
]

# ── ETFs (added 2026-05-31, operator request: "trade all the ETFs") ───────────
# LONG-ONLY tradable: broad-index, sector, industry, international, commodity,
# and bond ETFs. These trend/mean-revert like stocks, so the daily strategies
# (Connors §19, trend §8/§14, breakout §15) apply directly.
ETFS_TRADE = [
    # broad index
    "SPY", "QQQ", "IWM", "DIA", "VTI", "VOO", "RSP",
    # SPDR sectors
    "XLF", "XLE", "XLK", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC",
    # industry / thematic
    "SMH", "SOXX", "XBI", "KRE", "ARKK", "IYR", "XHB", "XOP", "GDX",
    # international
    "EEM", "EFA", "FXI", "EWZ",
    # commodity / bond (non-equity-beta sleeves — useful diversifiers)
    "GLD", "SLV", "TLT", "IEF", "HYG", "USO",
]

# HEDGE / inverse / vol ETFs — NOT in the long-only strategy universe. They
# decay structurally (daily-rebalanced leverage / vol roll), so naive long
# mean-reversion is a trap. Reserved for the regime/hedge overlay (the real
# fix for the long-only tail risk found 2026-05-31).
ETFS_HEDGE = ["SH", "PSQ", "SDS", "SQQQ", "VIXY"]

# de-dupe while preserving order, in case of overlap
_seen: set[str] = set()
ALL: list[str] = [s for s in (EXISTING + NEW + ETFS_TRADE)
                  if not (s in _seen or _seen.add(s))]

# All symbols we want Polygon data for (trading universe + hedge sleeve)
ALL_WITH_HEDGE: list[str] = ALL + [s for s in ETFS_HEDGE if s not in _seen]

OPTIONS_SAMPLE = ["QQQ", "AAPL", "NFLX", "JPM", "AMD", "UNH", "PLTR", "V"]

# Known partial-history names (informational; backtests just get fewer bars)
PARTIAL_HISTORY = {"CRWV": "~1yr (IPO 2025)", "ARM": "~2.5yr (IPO 2023-09)"}


if __name__ == "__main__":
    print(f"EXISTING ({len(EXISTING)}): {EXISTING}")
    print(f"NEW ({len(NEW)}): {NEW}")
    print(f"ETFS_TRADE ({len(ETFS_TRADE)}): {ETFS_TRADE}")
    print(f"ETFS_HEDGE ({len(ETFS_HEDGE)}): {ETFS_HEDGE}")
    print(f"ALL ({len(ALL)}): {ALL}")
    print(f"ALL_WITH_HEDGE ({len(ALL_WITH_HEDGE)})")
    print(f"OPTIONS_SAMPLE ({len(OPTIONS_SAMPLE)}): {OPTIONS_SAMPLE}")
    print(f"PARTIAL_HISTORY: {PARTIAL_HISTORY}")
