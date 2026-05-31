"""Tests for risk_brain — capital sleeves, options caps, stock sizing, tier priority.
Covers REQ-602, 605, 606, 604.2."""
import sys, os
from datetime import date
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import pytest
from risk_brain import (RiskBrain, RouteState, STOCK_SLEEVE_USD,
                        OPT_PER_TRADE_MAX_USD, OPT_WEEK_MAX_USD,
                        STOCK_SHARES_FIXED, TIER_ETF, TIER_LARGE, TIER_SMALL)
from trade_signal import Signal


# ── REQ-602: capital sleeves ──────────────────────────────────────────────────
def test_sleeve_split():
    rb = RiskBrain(total_equity=107_846)
    assert rb.stocks.sleeve_usd == 95_000
    assert round(rb.options.sleeve_usd, 0) == 12_846

def test_sleeve_split_small_account():
    # if total < $95K, stocks gets all of it, options gets 0
    rb = RiskBrain(total_equity=50_000)
    assert rb.stocks.sleeve_usd == 50_000
    assert rb.options.sleeve_usd == 0

def test_stock_sleeve_full_blocks_entry():
    rb = RiskBrain(total_equity=107_846)
    ok, _ = rb.can_enter("stocks", est_cost_usd=94_000, est_risk_usd=0)
    assert ok
    rb.register_entry("stocks", cost_usd=94_000)
    ok, reason = rb.can_enter("stocks", est_cost_usd=2_000, est_risk_usd=0)
    assert not ok and "sleeve full" in reason


# ── REQ-606: fixed 10-share stock sizing ──────────────────────────────────────
def test_stock_fixed_10_shares():
    rb = RiskBrain(total_equity=107_846)
    assert rb.stock_shares(200) == STOCK_SHARES_FIXED == 10
    assert rb.stock_shares(50) == 10

def test_stock_shares_zero_when_sleeve_cant_fit():
    rb = RiskBrain(total_equity=107_846)
    rb.register_entry("stocks", cost_usd=94_500)  # only $500 free
    # 10 shares of $200 = $2000 > $500 free → 0
    assert rb.stock_shares(200) == 0

def test_stock_shares_zero_on_bad_price():
    rb = RiskBrain(total_equity=107_846)
    assert rb.stock_shares(0) == 0
    assert rb.stock_shares(-5) == 0


# ── REQ-605: options per-trade + weekly caps ──────────────────────────────────
def test_options_per_trade_cap():
    rb = RiskBrain(total_equity=107_846)
    assert rb.can_enter("options", 400, 500)[0] is True       # exactly at cap
    assert rb.can_enter("options", 400, 500.01)[0] is False   # over cap

def test_options_weekly_cap_blocks_fourth_max_trade():
    rb = RiskBrain(total_equity=107_846)
    today = date(2026, 6, 1)
    # 3 × $500 = $1500 (at the weekly cap)
    for _ in range(3):
        ok, _ = rb.can_enter("options", 100, 500, today=today)
        assert ok
        rb.register_entry("options", 100, 500, today=today)
    # 4th would push to $2000 > $1500
    ok, reason = rb.can_enter("options", 100, 500, today=today)
    assert not ok and "weekly" in reason

def test_options_weekly_risk_rolls_off():
    rb = RiskBrain(total_equity=107_846, week_mode="rolling5")
    old = date(2026, 5, 1)
    rb.register_entry("options", 100, 500, today=old)
    # a week later the old risk is outside the rolling-5 window
    assert rb.week_options_risk(today=date(2026, 6, 1)) == 0.0


# ── REQ-604.2: tier prioritization ────────────────────────────────────────────
def test_tier_classification():
    etf = {"SPY", "QQQ"}
    large = {"AAPL", "MSFT"}
    assert RiskBrain.tier_of("SPY", etf, large) == TIER_ETF
    assert RiskBrain.tier_of("AAPL", etf, large) == TIER_LARGE
    assert RiskBrain.tier_of("RANDOMCO", etf, large) == TIER_SMALL
    # dollar-volume fallback
    assert RiskBrain.tier_of("XYZ", etf, None, dollar_volume=9e8) == TIER_LARGE
    assert RiskBrain.tier_of("XYZ", etf, None, dollar_volume=1e7) == TIER_SMALL

def test_prioritize_orders_etf_then_large_then_small():
    etf = {"SPY"}
    large = {"AAPL"}
    sigs = [
        Signal("SMALLCO", "bull", "s", strength=0.9),
        Signal("AAPL", "bull", "s", strength=0.5),
        Signal("SPY", "bull", "s", strength=0.1),
    ]
    ordered = RiskBrain.prioritize(sigs, etf, large)
    assert [s.symbol for s in ordered] == ["SPY", "AAPL", "SMALLCO"]


# ── entry/exit deployed accounting ────────────────────────────────────────────
def test_register_entry_exit_tracks_deployed():
    rb = RiskBrain(total_equity=107_846)
    rb.register_entry("stocks", cost_usd=2000)
    assert rb.stocks.deployed_usd == 2000 and rb.stocks.open_positions == 1
    rb.register_exit("stocks", cost_usd=2000)
    assert rb.stocks.deployed_usd == 0 and rb.stocks.open_positions == 0


# ── persistence ───────────────────────────────────────────────────────────────
def test_save_load_roundtrip(tmp_path):
    rb = RiskBrain(total_equity=107_846)
    rb.register_entry("options", 400, 400, today=date(2026, 6, 1))
    p = tmp_path / "rb.json"
    rb.save(p)
    rb2 = RiskBrain.load(p)
    assert rb2 is not None
    assert rb2.options.deployed_usd == 400
    assert rb2.week_options_risk(today=date(2026, 6, 1)) == 400


def test_unknown_route_refused():
    rb = RiskBrain(total_equity=107_846)
    ok, reason = rb.can_enter("futures", 100, 100)
    assert not ok and "unknown route" in reason
