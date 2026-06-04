"""Tests for router.route_for_pick — routing ONE merged screener pick to an
instrument (stocks vs options) by reusing the validated route_signal."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import router
from risk_brain import RiskBrain


def _rb():
    return RiskBrain(total_equity=107_846)


def test_no_option_row_routes_shares():
    # directional-only pick (no option candidate built) → shares (§5 cost hierarchy)
    dec = router.route_for_pick({"sym": "AAPL", "price": 200, "atr": 4}, None, _rb())
    assert dec.route == "stocks"


def test_option_low_ivr_routes_naked_option():
    dec = router.route_for_pick(
        {"sym": "NVDA", "price": 120, "atr": 3},
        {"sym": "NVDA", "direction": "bull", "ivr": "IVR 22"}, _rb())
    assert dec.route == "options"
    assert dec.structure and dec.structure.startswith("naked")


def test_high_ivr_spreads_disabled_falls_back_to_shares():
    # spread required (IVR>50) but harness disabled → never naked, route to shares
    dec = router.route_for_pick(
        {"sym": "XLF", "price": 50, "atr": 1},
        {"sym": "XLF", "direction": "bull", "ivr": "IVR 60"},
        _rb(), spreads_enabled=False)
    assert dec.route == "stocks"


def test_high_ivr_spreads_enabled_routes_spread():
    # cheap underlying so the debit spread fits the $400 budget
    dec = router.route_for_pick(
        {"sym": "XLF", "price": 50, "atr": 1},
        {"sym": "XLF", "direction": "bull", "ivr": "IVR 60"},
        _rb(), spreads_enabled=True)
    assert dec.route == "options"
    assert "spread" in (dec.structure or "")
