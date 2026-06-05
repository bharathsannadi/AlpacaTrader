#!/usr/bin/env python3
"""config.py — single source of truth for AlpacaTrader risk caps + position sizing (AH-2).

These constants were previously scattered across screener_executor / risk_brain / app, so
changing one cap meant editing several files (we hit this repeatedly 2026-06-04). Centralised
here; the home modules now `from config import ...`, so existing `module.X` references keep
working. Runtime-TUNABLE exit params (TP/SL %, stall, dynamic-exit flag, MERGED_PICKS_ENABLED)
deliberately stay on their home modules — those are mutated live via set_exit_config; THESE are
the static hard caps + sizing.
"""
from __future__ import annotations

# ── Option caps (operator 2026-06-04) ────────────────────────────────────────
OPT_HARD_MAX_USD      = 600.0     # HARD ceiling per option trade — ALL incl. ETFs
OPT_HARD_MAX_USD_ETF  = 600.0     # ETFs capped at $600 too (was $1500)
OPT_MAX_OPEN          = 5         # max concurrent option positions (by underlying)
MAX_AUTO_EXEC_PER_DAY = 2         # max auto option orders/day (EOD 2026-06-04: 5→2, dial down churn)
OPT_PER_TRADE_MAX_USD = 600.0     # risk_brain per-trade options cap (REQ-605)
OPT_WEEK_MAX_USD      = 3000.0    # risk_brain rolling-week options risk cap (REQ-605)

# ── Stock sizing ─────────────────────────────────────────────────────────────
STOCK_TARGET_USD      = 5000.0    # equal-dollar target capital per stock position


def size_position(route: str, price: float = 0.0, per_contract_cost: float = 0.0,
                  ceiling: float = OPT_HARD_MAX_USD) -> int:
    """Shared equal-dollar sizing (CR-6) — ONE place both executors and the router can size.
      route 'stocks'  → floor(STOCK_TARGET_USD / price)            (~$5000/position)
      route 'options' → floor(ceiling / per_contract_cost)         (gross long outlay → ~$600)
    Returns ≥1 when a single unit fits, 0 when it can't (caller skips). Never raises."""
    try:
        if route == "stocks":
            p = float(price)
            return max(1, int(STOCK_TARGET_USD // p)) if p > 0 else 0
        if route == "options":
            c = float(per_contract_cost)
            if c <= 0 or c > float(ceiling):
                return 0                      # 0 = doesn't fit even one (caller rejects)
            return max(1, int(float(ceiling) // c))
    except (TypeError, ValueError):
        return 0
    return 0
