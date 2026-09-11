#!/usr/bin/env python3
"""
vol_edge.py — is long option premium actually CHEAP right now?

Why this module exists
──────────────────────
KB §2 routes by IV RANK: IVR < 30 → buy naked premium ("cheap"). The rule is
sound. The input was not. Two different code paths were feeding it something
that is not an IV rank at all:

  * screener_engine set `"ivr": round(hv20)` — a raw ANNUALISED REALISED
    VOLATILITY LEVEL passed into a 0-100 PERCENTILE threshold. Measured over the
    trailing year, SPY's HV20 sat below 30 on 100% of days and QQQ's on 94%. So
    the router read "IVR 9 → cheap premium" every single session and bought
    naked long calls unconditionally, never once testing whether options were
    actually cheap.
  * spy_auto_trader.fetch_iv_rank ranks a real IV against a range built from
    HISTORICAL REALISED vol. Because implied vol structurally exceeds realised
    vol (that is the variance risk premium), ranking IV inside an HV range
    biases the rank upward — a different error, in the opposite direction.

KB §22 (Sinclair, *Volatility Trading*) is unambiguous about the stakes: implied
vol exceeds subsequent realised vol in ~70% of months, running 2-4 vol points
rich. That premium is a structural headwind on every long-premium trade. Buying
it unconditionally is negative expectancy before direction is even considered —
which is the most likely explanation for the option lane's 60 trades at a 92%
win rate and −$682 net.

So this module answers the question the router was never actually asking, using
the blend §22 prescribes:

    Expected_5d_vol = 0.45×HV5 + 0.35×IV30 + 0.20×HV30

Long premium is favourable only when Expected_5d_vol > IV30 — the underlying is
forecast to move MORE than options currently imply. Everything here is pure
arithmetic on numbers the caller supplies: no network, no clock, no I/O.

Fail-safe direction: every helper refuses (returns False / None) when an input
is missing or nonsensical. "Unknown" must never read as "cheap", because the
default action on a refusal is KB §5 — express the edge in shares instead.
"""
from __future__ import annotations

import math
from typing import Optional, Sequence

# KB §22 blend weights (Sinclair Ch. 7 — ~55% predictive power on a 5-day
# horizon, the best of the three single forecasters he measures).
W_HV5, W_IV30, W_HV30 = 0.45, 0.35, 0.20

# Require the forecast to beat implied by this margin (in vol points) before
# calling premium cheap. IV also carries the bid-ask and theta the ledger
# already charged us for, so a dead heat is not good enough.
MIN_VOL_EDGE_PTS = 1.0

TRADING_DAYS = 252


def hv_annualized(closes: Sequence[float], window: int = 20) -> Optional[float]:
    """Annualised realised volatility (%) from a close series, or None.

    Uses log returns and the sample stdev, matching how IV is quoted so the two
    are comparable. Needs window+1 closes to produce `window` returns."""
    if closes is None or window < 2:
        return None
    px = [float(c) for c in closes if c is not None and float(c) > 0]
    if len(px) < window + 1:
        return None
    rets = [math.log(px[i] / px[i - 1]) for i in range(len(px) - window, len(px))]
    n = len(rets)
    if n < 2:
        return None
    mean = sum(rets) / n
    var = sum((r - mean) ** 2 for r in rets) / (n - 1)     # sample, not population
    return math.sqrt(var) * math.sqrt(TRADING_DAYS) * 100.0


def iv_rank(current_iv: Optional[float], iv_history: Sequence[float]) -> Optional[float]:
    """TRUE IV rank: where current IV sits in its own 52-week IV range, 0-100.

    The history must be IMPLIED vols. Passing realised vols here reproduces the
    bug this module exists to fix, so a caller without real IV history should
    pass None and let the vol-edge test below decide instead."""
    if current_iv is None or iv_history is None:
        return None
    hist = [float(v) for v in iv_history if v is not None and float(v) > 0]
    if len(hist) < 2:
        return None
    lo, hi = min(hist), max(hist)
    if hi - lo < 0.1:                 # flat history carries no ranking information
        return None
    return round(max(0.0, min(100.0, (float(current_iv) - lo) / (hi - lo) * 100.0)), 1)


def expected_vol(hv5: Optional[float], iv30: Optional[float],
                 hv30: Optional[float]) -> Optional[float]:
    """KB §22 blended 5-day realised-vol forecast, or None if any input is missing."""
    if hv5 is None or iv30 is None or hv30 is None:
        return None
    if hv5 < 0 or iv30 <= 0 or hv30 < 0:
        return None
    return W_HV5 * float(hv5) + W_IV30 * float(iv30) + W_HV30 * float(hv30)


def long_premium_ok(hv5: Optional[float], hv30: Optional[float],
                    iv30: Optional[float],
                    min_edge_pts: float = MIN_VOL_EDGE_PTS) -> tuple[bool, str]:
    """Is buying premium justified right now? Returns (ok, human-readable why).

    Cheap means the blended forecast of what the underlying will actually do
    exceeds what options currently imply, by at least `min_edge_pts` vol points.
    Anything else — including missing data — refuses, and the caller should fall
    back to shares under KB §5."""
    ev = expected_vol(hv5, iv30, hv30)
    if ev is None:
        return False, ("vol inputs incomplete (need HV5, HV30, IV30) — "
                       "can't confirm premium is cheap (§22)")
    edge = ev - float(iv30)
    if edge >= min_edge_pts:
        return True, (f"forecast vol {ev:.1f}% > IV30 {float(iv30):.1f}% "
                      f"by {edge:.1f}pts — premium is cheap (§22)")
    return False, (f"forecast vol {ev:.1f}% vs IV30 {float(iv30):.1f}% "
                   f"({edge:+.1f}pts) — paying the variance risk premium (§22)")


def vol_regime(daily_pct_moves: Sequence[float]) -> tuple[str, str]:
    """GARCH clustering read from recent absolute daily moves (%), KB §22.

    Returns (regime, why) where regime is "expansion" | "compression" | "normal".
    Vol clusters, so the recent run tells you which way IV is likely mispriced:
      * 3+ consecutive days > 1.0%  → expansion. IV is inflated by the move that
        already happened; the move is priced in. Reduce size, prefer spreads.
      * 5+ consecutive days < 0.4%  → compression. Options are cheap relative to
        recent movement. Sinclair's best window for long premium.
    """
    if not daily_pct_moves:
        return "normal", "no recent move data"
    moves = [abs(float(m)) for m in daily_pct_moves if m is not None]
    if len(moves) < 3:
        return "normal", "insufficient move history"
    if all(m > 1.0 for m in moves[-3:]):
        return "expansion", ("3+ consecutive >1% days — IV inflated by the move "
                             "already made; it is priced in (§22 GARCH)")
    if len(moves) >= 5 and all(m < 0.4 for m in moves[-5:]):
        return "compression", ("5+ consecutive <0.4% days — options cheap vs "
                               "recent movement; best long-premium window (§22)")
    return "normal", "no vol cluster"


def size_multiplier(regime: str) -> float:
    """Position-size scalar for the regime. Expansion halves size (§22: the move
    is already priced in, and short-gamma risk is highest there)."""
    return {"expansion": 0.5, "compression": 1.0}.get(regime, 1.0)


if __name__ == "__main__":
    # SPY-like: calm tape, implied still rich → refuse, this is the common case
    print(long_premium_ok(hv5=8.0, hv30=10.0, iv30=14.0))
    # underlying moving far more than options imply → buy
    print(long_premium_ok(hv5=26.0, hv30=18.0, iv30=15.0))
    print(vol_regime([0.2, 0.3, 0.1, 0.35, 0.2]))
    print(vol_regime([1.4, 1.8, 2.1]))
