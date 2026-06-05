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
    cap = OPT_PER_TRADE_MAX_USD                                  # config single source (no stale literal)
    assert rb.can_enter("options", 400, cap)[0] is True         # exactly at cap
    assert rb.can_enter("options", 400, cap + 0.01)[0] is False # over cap

def test_options_weekly_cap_blocks_over_cap():
    rb = RiskBrain(total_equity=107_846)
    today = date(2026, 6, 1)
    per = OPT_PER_TRADE_MAX_USD
    n = int(OPT_WEEK_MAX_USD // per)          # trades that exactly reach the rolling-week cap
    for _ in range(n):
        ok, _ = rb.can_enter("options", 100, per, today=today)
        assert ok
        rb.register_entry("options", 100, per, today=today)
    # the next trade pushes over the weekly cap → blocked
    ok, reason = rb.can_enter("options", 100, per, today=today)
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

def test_prioritize_route_aware():
    # Route-aware prioritization (operator 2026-06-01): shares lane trades stocks before
    # ETFs (large→small→ETF); options lane keeps ETF first (ETF→large→small).
    etf = {"SPY"}
    large = {"AAPL"}
    sigs = [
        Signal("SMALLCO", "bull", "s", strength=0.9),
        Signal("AAPL", "bull", "s", strength=0.5),
        Signal("SPY", "bull", "s", strength=0.1),
    ]
    # shares lane (no vol edge) → large, small, ETF last
    assert [s.symbol for s in RiskBrain.prioritize(sigs, etf, large)] == ["AAPL", "SMALLCO", "SPY"]
    # options lane (vol edge) → ETF first
    vsigs = [Signal(s.symbol, "bull", "vol", strength=s.strength, has_vol_edge=True) for s in sigs]
    assert [s.symbol for s in RiskBrain.prioritize(vsigs, etf, large)] == ["SPY", "AAPL", "SMALLCO"]


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


# ── Elder 6% Rule (REQ-611, book-dig) ─────────────────────────────────────────
def test_six_percent_rule_blocks_over_cap():
    rb = RiskBrain(total_equity=100_000)   # 6% = $6000
    # month loss $3000 + open risk $2500 + new trade $1000 = $6500 > $6000
    ok, reason = rb.six_percent_ok(new_risk_usd=1000, open_risk_usd=2500, month_loss_usd=3000)
    assert not ok and "6% rule" in reason

def test_six_percent_rule_allows_under_cap():
    rb = RiskBrain(total_equity=100_000)
    ok, _ = rb.six_percent_ok(new_risk_usd=1000, open_risk_usd=2000, month_loss_usd=1000)
    assert ok  # $4000 < $6000

def test_six_percent_breakeven_frees_budget():
    # Elder: a breakeven-stopped position has ZERO open risk (caller passes 0)
    rb = RiskBrain(total_equity=100_000)
    ok, _ = rb.six_percent_ok(new_risk_usd=1500, open_risk_usd=0, month_loss_usd=4000)
    assert ok  # $5500 < $6000 because breakeven positions free the budget
