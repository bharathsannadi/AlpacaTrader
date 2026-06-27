"""Tests for router — KB-driven instrument routing (REQ-601)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from trade_signal import Signal
from risk_brain import RiskBrain
from router import route_signal


def _rb():
    return RiskBrain(total_equity=107_846)


# ── §5: directional-only edge → shares ────────────────────────────────────────
def test_directional_only_routes_to_shares():
    sig = Signal("AAPL", "bull", "connors_rsi2", price=200, atr=4, has_vol_edge=False)
    d = route_signal(sig, _rb())
    assert d.route == "stocks" and d.qty == 10
    assert "§5" in d.reason


# ── §2: volatility edge → options by IVR ──────────────────────────────────────
def test_vol_edge_low_ivr_naked_call():
    sig = Signal("NVDA", "bull", "vol", price=120, atr=3, has_vol_edge=True, ivr=22)
    d = route_signal(sig, _rb())
    assert d.route == "options" and d.structure == "naked_call"

def test_vol_edge_low_ivr_naked_put_for_bear():
    sig = Signal("NVDA", "bear", "vol", price=120, atr=3, has_vol_edge=True, ivr=22)
    d = route_signal(sig, _rb())
    assert d.route == "options" and d.structure == "naked_put"

def test_vol_edge_mid_ivr_spread_when_enabled():
    sig = Signal("MSFT", "bull", "vol", price=400, atr=6, has_vol_edge=True, ivr=40)
    d = route_signal(sig, _rb(), spreads_enabled=True)
    assert d.route == "options" and d.structure == "debit_call_spread"

def test_vol_edge_mid_ivr_spread_disabled_falls_back_to_shares():
    sig = Signal("MSFT", "bull", "vol", price=400, atr=6, has_vol_edge=True, ivr=40)
    d = route_signal(sig, _rb(), spreads_enabled=False)
    assert d.route == "stocks"
    assert "spreads disabled" in d.reason

def test_vol_edge_high_ivr_never_naked():
    # IVR>50 must be spread-only; with spreads off → shares, never a naked option
    sig = Signal("SPY", "bull", "vol", price=560, atr=6, has_vol_edge=True, ivr=60)
    d = route_signal(sig, _rb(), spreads_enabled=False)
    assert d.route != "options" or "spread" in (d.structure or "")
    assert d.route == "stocks"

def test_ivr_unknown_falls_back_to_shares():
    sig = Signal("AMD", "bull", "vol", price=150, atr=4, has_vol_edge=True, ivr=None)
    d = route_signal(sig, _rb())
    assert d.route == "stocks"


# ── REQ-601.3 affordability + risk-brain interaction ──────────────────────────
def test_option_over_cap_falls_back_to_shares():
    # premium high enough that naked risk > the $600 per-trade cap → option blocked → shares
    sig = Signal("NVDA", "bull", "vol", price=120, atr=3, has_vol_edge=True, ivr=22)
    d = route_signal(sig, _rb(), option_premium=7.0)   # 7.00 × 100 = $700 > $600
    assert d.route == "stocks"
    assert "fall back to shares" in d.reason

def test_skip_when_neither_fits():
    from risk_brain import OPT_PER_TRADE_MAX_USD, OPT_WEEK_MAX_USD
    rb = RiskBrain(total_equity=107_846)
    rb.register_entry("stocks", cost_usd=95_000)   # stock sleeve full
    # exhaust the options weekly cap too (config single source — no stale literal).
    # Seed at TODAY so the seeded risk lands in the same rolling-week window that
    # route_signal() checks with the real date — otherwise this test is time-fragile
    # (a hardcoded past date falls out of the current week and the cap looks unused).
    from datetime import date
    t = date.today()
    per = OPT_PER_TRADE_MAX_USD
    for _ in range(int(OPT_WEEK_MAX_USD // per)):
        rb.register_entry("options", 100, per, today=t)
    sig = Signal("NVDA", "bull", "vol", price=120, atr=3, has_vol_edge=True, ivr=22)
    d = route_signal(sig, rb)
    assert d.route == "skip"


def test_naked_option_risk_within_cap_is_taken():
    sig = Signal("INTC", "bull", "vol", price=20, atr=0.6, has_vol_edge=True, ivr=20)
    d = route_signal(sig, _rb(), option_premium=2.0)   # $200 risk < $500
    assert d.route == "options" and d.est_risk_usd == 200.0
