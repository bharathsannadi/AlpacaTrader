#!/usr/bin/env python3
"""
router.py — KB-driven instrument router (Phase 2). Satisfies REQ-601.

For each Signal, decide HOW to express it — shares vs option, and which option
structure — using the knowledge base, then check the shared risk brain. Pure
decision logic; it returns a RouteDecision and places no orders (executors do).

KB rules encoded:
  §5 cost hierarchy : a DIRECTIONAL-ONLY edge (no volatility edge) is cheapest in
                      SHARES. Options costs (spread + theta + fees) destroy a thin
                      directional edge — this is why naked options backtested PF 0.92.
  §2 IV routing     : with a volatility edge, choose structure by IVR —
                      IVR < 30  → naked long (cheap premium)
                      IVR 30-50 → debit spread (cap vega)
                      IVR > 50  → debit spread ONLY (never naked)
  REQ-601.3         : if the option won't fit the budget, fall back to shares (or skip).

Spreads are GATED: SPREADS_ENABLED=False until the 2S-B spread-data harness passes.
When a spread is required but disabled, reroute to shares (if a directional edge
exists) or skip — never silently buy a forbidden naked option.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

from trade_signal import Signal
from risk_brain import RiskBrain

ATR_STOP_M = 2.0          # shares stop = 2×ATR (matches daily strategy)
SPREADS_ENABLED = False   # 2S-B blocked — no validated spread harness yet
# rough ATM premium estimate when no live quote is supplied (decision-time only;
# real execution uses the live option quote)
EST_ATM_PREMIUM_FRAC = 0.03   # ~3% of underlying for a near-ATM, ~21-30 DTE option


@dataclass
class RouteDecision:
    route: str                      # "stocks" | "options" | "skip"
    structure: Optional[str]        # options: naked_call|naked_put|debit_call_spread|debit_put_spread
    reason: str
    est_cost_usd: float = 0.0       # capital tied up
    est_risk_usd: float = 0.0       # max $ loss
    qty: int = 0                    # shares or contracts


def _structure_for_ivr(ivr: Optional[float], direction: str) -> tuple[Optional[str], str]:
    """Return (structure, why) per KB §2. None structure means 'cannot route to options'."""
    side = "call" if direction == "bull" else "put"
    if ivr is None:
        return None, "IVR unknown — can't confirm option structure (§2)"
    if ivr < 30:
        return f"naked_{side}", f"IVR {ivr:.0f}<30 → naked {side} (§2 cheap premium)"
    if ivr <= 50:
        return f"debit_{side}_spread", f"IVR {ivr:.0f} 30-50 → debit {side} spread (§2)"
    return f"debit_{side}_spread", f"IVR {ivr:.0f}>50 → debit {side} spread ONLY (§2)"


def route_signal(sig: Signal, rb: RiskBrain,
                 option_premium: Optional[float] = None,
                 spreads_enabled: bool = SPREADS_ENABLED) -> RouteDecision:
    """Decide the route for one signal, honoring KB rules + the risk brain."""
    # ── shares economics (fixed 10 shares, REQ-606) ──
    shares = rb.stock_shares(sig.price) if sig.price > 0 else 0
    stock_cost = shares * sig.price
    stock_risk = shares * (ATR_STOP_M * sig.atr) if sig.atr > 0 else stock_cost

    def shares_decision(why: str) -> RouteDecision:
        if shares == 0:
            return RouteDecision("skip", None, f"{why}; but shares don't fit sleeve/price")
        ok, rsn = rb.can_enter("stocks", stock_cost, stock_risk)
        if not ok:
            return RouteDecision("skip", None, f"{why}; shares blocked: {rsn}")
        return RouteDecision("stocks", None, why, stock_cost, stock_risk, shares)

    # ── §5: directional-only edge → shares (cheapest vehicle) ──
    if not sig.has_vol_edge:
        return shares_decision("directional-only edge → shares (§5 cost hierarchy)")

    # ── §2: has a volatility edge → options, structure by IVR ──
    structure, why = _structure_for_ivr(sig.ivr, sig.direction)
    if structure is None:
        # can't confirm structure → safest is the cheaper directional vehicle
        return shares_decision(f"{why} → fall back to shares")

    is_spread = "spread" in structure
    if is_spread and not spreads_enabled:
        # spread required but harness not validated (2S-B). Naked is FORBIDDEN here
        # (§2), so route the directional edge to shares, or skip.
        return shares_decision(f"{why}, but spreads disabled (2S-B) → shares")

    # estimate option economics (real execution uses a live quote)
    prem = option_premium if option_premium is not None else EST_ATM_PREMIUM_FRAC * sig.price
    if is_spread:
        # debit spread: risk ≈ net debit (assume ~40% of a 1-leg premium as a proxy)
        opt_cost = opt_risk = round(prem * 0.4 * 100, 2)
    else:
        # naked long: risk = full premium paid
        opt_cost = opt_risk = round(prem * 100, 2)

    # REQ-601.3 affordability + risk brain
    ok, rsn = rb.can_enter("options", opt_cost, opt_risk)
    if not ok:
        # fall back to shares if a directional edge can still be expressed cheaply
        fb = shares_decision(f"option blocked ({rsn}) → fall back to shares")
        if fb.route != "skip":
            return fb
        return RouteDecision("skip", structure, f"option blocked: {rsn}; shares also unavailable")

    return RouteDecision("options", structure, why, opt_cost, opt_risk, 1)


if __name__ == "__main__":
    rb = RiskBrain(total_equity=107_846)
    # directional-only → shares
    s1 = Signal("AAPL", "bull", "connors_rsi2", price=200, atr=4, has_vol_edge=False)
    print("1 directional-only:", route_signal(s1, rb))
    # vol edge, low IVR → naked call
    s2 = Signal("NVDA", "bull", "vol", price=120, atr=3, has_vol_edge=True, ivr=22)
    print("2 vol-edge IVR22:", route_signal(s2, rb))
    # vol edge, high IVR → spread required but disabled → shares
    s3 = Signal("SPY", "bull", "vol", price=560, atr=6, has_vol_edge=True, ivr=60)
    print("3 vol-edge IVR60 (spread off):", route_signal(s3, rb))
