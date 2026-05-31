#!/usr/bin/env python3
"""
kelly.py — Kelly criterion sizing helpers (3R-B.1).

Given a backtest's win-rate and average win/loss, compute the Kelly fraction
and recommended live size. Always use ½-Kelly; full-Kelly is shown for reference.

Usage:
    from kelly import half_kelly, kelly_sizing
    frac = half_kelly(win_pct=66.4, avg_win_pct=2.1, avg_loss_pct=-1.1)
    size = kelly_sizing(account=5000, win_pct=66.4, avg_win_pct=2.1, avg_loss_pct=-1.1)
"""
from __future__ import annotations

# Hard bounds: never bet less than 0.5% or more than 5% per trade.
# These override the Kelly output when the formula returns an extreme value.
KELLY_FLOOR = 0.005   # 0.5% min
KELLY_CEIL  = 0.05    # 5% max


def full_kelly(win_pct: float, avg_win_pct: float, avg_loss_pct: float) -> float:
    """Full-Kelly fraction as a decimal (e.g. 0.16 = 16%).

    win_pct      : win rate as a percentage (e.g. 66.4 for 66.4%)
    avg_win_pct  : average win as a positive % of trade value (e.g. 2.1)
    avg_loss_pct : average loss as a negative % of trade value (e.g. -1.1)

    Returns the optimal bet fraction in [0, 1], clamped to KELLY_FLOOR/CEIL.
    Returns 0.0 if the edge is negative or inputs are degenerate.
    """
    try:
        p = win_pct / 100.0
        q = 1.0 - p
        b = abs(avg_win_pct) / abs(avg_loss_pct) if avg_loss_pct != 0 else 0.0
        if b <= 0 or p <= 0 or q <= 0:
            return 0.0
        k = (p * b - q) / b
        if k <= 0:
            return 0.0
        return max(KELLY_FLOOR, min(KELLY_CEIL, k))
    except Exception:
        return 0.0


def half_kelly(win_pct: float, avg_win_pct: float, avg_loss_pct: float) -> float:
    """½-Kelly fraction (recommended for live trading).

    Same parameters as full_kelly. Returns full_kelly / 2, clamped to bounds.
    ½-Kelly reduces variance substantially while capturing ~75% of the full-Kelly
    growth rate — the standard practitioner choice (Sinclair KB §4).
    """
    fk = full_kelly(win_pct, avg_win_pct, avg_loss_pct)
    if fk <= 0:
        return 0.0
    return max(KELLY_FLOOR, min(KELLY_CEIL, fk / 2.0))


def kelly_sizing(account: float, win_pct: float,
                 avg_win_pct: float, avg_loss_pct: float) -> dict:
    """Compute full-Kelly and ½-Kelly dollar amounts for a given account size.

    Returns a dict with:
        full_kelly_frac  : full-Kelly fraction
        half_kelly_frac  : ½-Kelly fraction (recommended)
        full_kelly_usd   : full-Kelly $ per trade
        half_kelly_usd   : ½-Kelly $ per trade (recommended)
        edge_exists      : bool — True if edge > 0
        expectancy_pct   : expected % gain per trade
    """
    fk = full_kelly(win_pct, avg_win_pct, avg_loss_pct)
    hk = half_kelly(win_pct, avg_win_pct, avg_loss_pct)
    p = win_pct / 100.0
    exp = p * avg_win_pct + (1 - p) * avg_loss_pct
    return {
        "full_kelly_frac":  round(fk, 4),
        "half_kelly_frac":  round(hk, 4),
        "full_kelly_usd":   round(account * fk, 2),
        "half_kelly_usd":   round(account * hk, 2),
        "edge_exists":      fk > 0,
        "expectancy_pct":   round(exp, 3),
    }


if __name__ == "__main__":
    # Connors RSI(2) validated stats (2026-05-20 backtest)
    result = kelly_sizing(
        account=5000,
        win_pct=66.4,
        avg_win_pct=2.1,
        avg_loss_pct=-1.1,
    )
    print("Connors RSI(2) Kelly sizing on $5K account:")
    for k, v in result.items():
        print(f"  {k}: {v}")
