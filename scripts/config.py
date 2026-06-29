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

# ── Option lane kill-switch (edge review 2026-06-12) ─────────────────────────
# analyze_trades.py over 600 closed trades (Jun 2–12) found the autonomous OPTION
# lane has NEGATIVE expectancy: 60 trades, 92% win rate, yet −$682 total / −$11 a
# trade. Avg win $12 vs avg loss $271 (payoff 0.05) — it needs a 95.7% win rate
# just to break even. The 90-min stall timer caps every winner at ~$12 while the
# −50% stop lets losers run, so the structure is a guaranteed bleed. Entries are
# paused until the exit logic earns its keep; EXITS still run (open legs stay
# managed). Re-run `python scripts/analyze_trades.py` and flip back to True only
# once the option lane shows positive per-trade expectancy. Reversible.
# Re-enable attempt 2026-06-17 (operator) jammed the eventlet hub on boot
# (/health 15–25s, flapping) — the entry path does heavy synchronous Alpaca/
# yfinance work across all option picks on the single hub. Reverted to restore
# stability; needs the entry work moved off-hub before re-enabling. See
# [[project-architecture-hardening]].
AUTO_EXEC_OPTIONS_ENABLED = False

# ── Option caps (operator 2026-06-04) ────────────────────────────────────────
OPT_HARD_MAX_USD      = 600.0     # HARD ceiling per option trade — ALL incl. ETFs
OPT_HARD_MAX_USD_ETF  = 600.0     # ETFs capped at $600 too (was $1500)
OPT_MAX_OPEN          = 5         # max concurrent option positions (by underlying)
MAX_AUTO_EXEC_PER_DAY = 2         # max auto option orders/day (EOD 2026-06-04: 5→2, dial down churn)
OPT_PER_TRADE_MAX_USD = 600.0     # risk_brain per-trade options cap (REQ-605)
OPT_WEEK_MAX_USD      = 3000.0    # risk_brain rolling-week options risk cap (REQ-605)

# ── Stock sizing ─────────────────────────────────────────────────────────────
STOCK_TARGET_USD      = 5000.0    # equal-dollar target capital per stock position

# ── Portfolio concentration cap (operator 2026-06-05) ────────────────────────
# Post-mortem of the −$2,549 / 0W-20L day: the screener + autonomous lanes each
# piled into 20+ same-direction LONG positions, so a single risk-off tape (12 of
# 15 names down) stopped them ALL out together. This is KB-5 ("max 3 correlated")
# generalised to a portfolio breadth ceiling: in a long-only book, position COUNT
# *is* the concentration measure. Enforced across BOTH auto-exec lanes (stocks +
# options) so neither can independently rebuild a 20-correlated-long book.
MAX_PORTFOLIO_POSITIONS = 12      # max concurrent open positions, stocks + options combined

# ── Per-symbol stop-out cooldown (edge review 2026-06-12) ────────────────────
# analyze_trades.py found a handful of names that the screener re-buys and then
# stops out of, over and over, for the bulk of the book's losses: GLD (0W/12L,
# −$3,564), AMAT (1W/18L, −$3,149), GOOG (1W/12L, −$1,502) — ~−$8.2k, most of the
# window's max drawdown. A name that keeps stopping out is one the strategy is
# chronically misjudging in the current regime. After SYMBOL_COOLDOWN_MIN_STOPS
# stop-outs inside the trailing SYMBOL_COOLDOWN_WINDOW_DAYS *and* a net-negative
# P&L on that name over the window, block fresh entries until it ages out. The
# net-negative AND clause is deliberate: a high-churn name that still nets
# positive keeps trading. Set MIN_STOPS very high to disable.
SYMBOL_COOLDOWN_WINDOW_DAYS = 5
SYMBOL_COOLDOWN_MIN_STOPS    = 2   # edge review 2026-06-27: 3→2. GLD/MU stopped out
                                  # TWICE before re-entry was blocked (GLD -3% then
                                  # re-bought and -5.5%); two net-negative stops in
                                  # the window is enough signal to sit a name out.

# ── Sector / correlation concentration cap (edge review 2026-06-27) ──────────
# The 2026-06-23 wipeout (-$1,674, 0W/12L) was one risk-off semis tape that
# stopped out NVDA/AMAT/LRCX/MU/TXN/INTC at once. MAX_PORTFOLIO_POSITIONS counts
# positions but can't tell "12 names" from "12 semis" — a long-only book of one
# correlated basket is a single trade. Cap concurrent open positions per
# correlation GROUP. Semis / semi-equip / photonics / servers / semi-ETFs collapse
# into ONE group (they move together — see _corr_group in app.py); names with an
# unknown sector are each their own group, never falsely lumped. Set high to disable.
MAX_POSITIONS_PER_SECTOR = 3

# ── High-priced gap-risk exclusion (edge review 2026-06-27) ──────────────────
# The worst stop slippage was all in expensive names: MU stopped at -7.3% (-$346)
# from a $1,179 entry, AMAT -6.7%, LRCX -5.7%, GLD -5.5%. At ~$5000/position a
# $1,100 stock is ~4 shares — no sizing granularity, and a single overnight/midday
# gap blows clean through the -3.5% stop the 10s polling monitor can't defend.
# Sub-$100 names were net POSITIVE over the window; the >$300 semis carried the
# losses. Skip fresh stock entries priced above this. Set high to disable.
MAX_STOCK_ENTRY_PRICE = 300.0

# ── Entry-time window (edge review 2026-06-27) ───────────────────────────────
# Midday entries were the worst: the 2026-06-23 losers clustered 12:17-12:41 ET in
# lunchtime chop, and the few real target-reachers were all morning entries.
# Restrict fresh auto-buys to the first N minutes after the 09:30 ET open. Set to a
# large number (e.g. 390) to effectively disable.
ENTRY_WINDOW_END_MIN = 90   # 09:30 + 90 min = 11:00 ET cutoff for NEW entries


# ═══ DESK REVIEW IMPLEMENTATION (2026-06-29) ═════════════════════════════════
# Buy-side desk review (TODO.md §BUY-SIDE DESK REVIEW). The 🔴 items below change
# trade economics, so per the standing convention they ship behind flags that
# DEFAULT OFF — flip to True only after a ≥3bp walk-forward + operator sign-off.
# The 🟢 observability items (DESK-4/5/6/9/10) are live and need no flag.

# DESK-1/2/3 — honor each setup's VALIDATED exit (horizon / target / stop) instead
# of the one-size flat band. When True, manage_exits uses SETUP_EXIT_PARAMS for any
# position whose `setup` is known; otherwise falls back to the existing kind logic.
SETUP_EXIT_ENABLED = False

# Per-setup exit params — machine-readable form of screener_engine.SETUP_STRATEGY.
#   same_day      : force an intraday close (these edges decay overnight)
#   max_hold_min  : minutes from entry to force-close (None → hold to EOD)
#   stop_pct      : hard stop as a fraction of entry (the PRESCRIBED tight stop)
#   target_pct    : fixed take-profit as a fraction of entry (None → no fixed target)
# RSI Dip is a next-day mean-reversion handled by daily_trader (NOT same-day) — wide
# stop, hold to EOD, no fixed target.
SETUP_EXIT_PARAMS = {
    "Breakout":  {"same_day": True,  "max_hold_min": 90,   "stop_pct": 0.0125, "target_pct": 0.025},
    "Bull Flag": {"same_day": True,  "max_hold_min": 15,   "stop_pct": 0.015,  "target_pct": 0.010},
    "Gap+Vol":   {"same_day": True,  "max_hold_min": 120,  "stop_pct": 0.0175, "target_pct": 0.030},
    "RSI Dip":   {"same_day": False, "max_hold_min": None, "stop_pct": 0.020,  "target_pct": None},
}

# DESK-7 — regime filter: block NEW long entries when the market proxy is below its
# moving average (both -$5k cliff days were broad risk-off). Observability when off.
REGIME_FILTER_ENABLED = False
REGIME_PROXY_SYMBOL   = "SPY"
REGIME_MA_DAYS        = 20

# DESK-8 — volatility-based sizing: size each position so it risks a CONSTANT dollar
# amount (risk = STOCK_RISK_USD, shares = risk / per-share stop distance) instead of
# a flat $5000 notional. Falls back to equal-dollar when ATR/stop is unknown.
VOL_SIZING_ENABLED = False
STOCK_RISK_USD     = 175.0    # target $ risk per stock position (3.5% of a $5k sleeve)

# DESK-6 — book exposure cap (observability + optional gate). Net long $ as a multiple
# of equity; a long-only book of correlated names is one big beta bet.
MAX_NET_LONG_EXPOSURE_X = 1.5  # informational ceiling surfaced by exposure_snapshot

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
