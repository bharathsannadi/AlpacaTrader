"""Tests for kb_principles — the KB-match scorer that powers the Confidence
column and the pre-trade gate."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import kb_principles as kb


def test_clean_connors_option_scores_high():
    row = {"dir_pct": 66.4, "pf": 1.32, "ivr": "IVR 22",
           "expiry": "2099-01-15", "structure": "ATM Call", "max_risk": 400}
    sc = kb.score_option_candidate(row, vix=18)
    assert sc["pct"] >= kb.KB_MATCH_MIN
    assert sc["n_matched"] >= 5
    assert "matched" in sc and "failed" in sc


def test_weak_edge_option_fails_floor():
    # below-threshold directional edge + losing PF + over-budget risk
    row = {"dir_pct": 48.0, "pf": 0.9, "ivr": "IVR 70",
           "expiry": "2099-01-15", "structure": "ATM Call", "max_risk": 900}
    sc = kb.score_option_candidate(row, vix=35)
    assert sc["pct"] < kb.KB_MATCH_MIN


def test_ivr_structure_routing():
    # high IVR with a naked structure should FAIL the routing principle
    naked_high = kb.score_option_candidate(
        {"dir_pct": 60, "pf": 1.3, "ivr": "IVR 55", "expiry": "2099-01-15",
         "structure": "ATM Call", "max_risk": 400}, vix=18)
    spread_high = kb.score_option_candidate(
        {"dir_pct": 60, "pf": 1.3, "ivr": "IVR 55", "expiry": "2099-01-15",
         "structure": "Debit Call Spread", "max_risk": 400}, vix=18)
    assert spread_high["pct"] > naked_high["pct"]


def test_stock_scorer_validity_matters():
    valid = kb.score_stock_candidate(
        {"valid": True, "bt_pf": 1.88, "rel_vol": 2.1, "rsi14": 58,
         "impulse": "Green", "setup": "Breakout"}, vix=18)
    invalid = kb.score_stock_candidate(
        {"valid": False, "bt_pf": 0.85, "rel_vol": 0.6, "rsi14": 82,
         "impulse": "Red", "setup": "VWAP Bounce"}, vix=32)
    assert valid["pct"] > invalid["pct"]
    assert valid["pct"] >= kb.KB_MATCH_MIN


def test_dte_parsing_and_unknown_fields_safe():
    assert kb._dte_from_expiry("") is None
    assert kb._parse_ivr("—") is None
    # missing everything should not raise, just score low
    sc = kb.score_option_candidate({}, vix=None)
    assert 0 <= sc["pct"] <= 100


# ── rank-liquidity-gate: §9 liquidity must affect the score/rank ──────────────
_LIQ_BASE = {"dir_pct": 66.4, "pf": 1.32, "ivr": "IVR 22",
             "expiry": "2099-01-15", "structure": "ATM Call", "max_risk": 400}


def test_liquid_option_score_unchanged():
    # liquidity is a one-sided gate: being liquid is the baseline and must NOT
    # boost the score (otherwise a borderline name jumps the 60 gate → more trades).
    no_liq = kb.score_option_candidate(dict(_LIQ_BASE), vix=18)
    liquid = kb.score_option_candidate({**_LIQ_BASE, "liquidity": {"ok": True}}, vix=18)
    assert liquid["pct"] == no_liq["pct"]


def test_illiquid_option_forced_below_floor():
    # an otherwise-perfect contract must be disqualified (below 60) when illiquid,
    # so it can never rank/show as a top BUY (the hard-floor, not just -3 weight).
    sc = kb.score_option_candidate(
        {**_LIQ_BASE, "liquidity": {"ok": False, "reason": "OI 12 < 200"}}, vix=18)
    assert sc["pct"] < kb.KB_MATCH_MIN
    assert any("liquidity FAIL" in f for f in sc["failed"])


def test_unknown_liquidity_is_fail_open():
    no_liq = kb.score_option_candidate(dict(_LIQ_BASE), vix=18)
    unknown = kb.score_option_candidate({**_LIQ_BASE, "liquidity": {"ok": None}}, vix=18)
    assert unknown["pct"] == no_liq["pct"]     # not checked yet → no effect


def test_calibrate_is_identity_today():
    assert kb.calibrate(73) == 73
    assert kb.calibrate(73, ivr=40, win_prob=0.6) == 73
