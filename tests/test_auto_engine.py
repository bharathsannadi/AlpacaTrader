"""Tests for auto_engine.build_plan — the autonomous orchestrator's pure planner."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from trade_signal import Signal
from auto_engine import build_plan, run_cycle


ETF = {"SPY", "QQQ"}


def test_empty_signals_empty_plan():
    plan = build_plan([], equity=100_000, etf_set=ETF)
    assert plan["planned"] == [] and plan["n_signals"] == 0


def test_plan_routes_and_sizes():
    sigs = [
        Signal("AAPL", "bull", "connors_rsi2", price=200, atr=4, has_vol_edge=False),
        Signal("NVDA", "bull", "vol", price=120, atr=3, has_vol_edge=True, ivr=22),
    ]
    plan = build_plan(sigs, equity=107_846, etf_set=ETF)
    routes = {pt.signal.symbol: pt.decision.route for pt in plan["planned"]}
    assert routes["AAPL"] == "stocks"      # directional-only → shares (§5)
    assert routes["NVDA"] == "options"     # vol edge, IVR<30 → naked (§2)


def test_shares_lane_prioritizes_stocks_over_etf():
    # Route-aware (operator 2026-06-01): directional-only (shares-lane) signals trade
    # individual stocks BEFORE ETFs — so AAPL ranks ahead of SPY (was blanket ETF-first).
    sigs = [
        Signal("AAPL", "bull", "connors_rsi2", strength=0.9, price=200, atr=4, asset_class="stock"),
        Signal("SPY", "bull", "trend_pullback", strength=0.1, price=560, atr=6, asset_class="etf"),
    ]
    plan = build_plan(sigs, equity=200_000, etf_set=ETF)
    assert plan["planned"][0].signal.symbol == "AAPL"   # shares lane → stock before ETF


def test_options_weekly_cap_skips_excess():
    # many vol-edge option signals; weekly options cap ($1500 / $500 = 3) limits them
    sigs = [Signal(f"X{i}", "bull", "vol", price=20, atr=0.6, has_vol_edge=True, ivr=20)
            for i in range(6)]
    plan = build_plan(sigs, equity=107_846, etf_set=ETF)
    opt_planned = [pt for pt in plan["planned"] if pt.decision.route == "options"]
    # naked $20 stock ~ $60 premium risk each; weekly cap binds eventually OR they
    # fall back to shares — either way options risk never exceeds the $1500 cap
    assert plan["risk_snapshot"]["options_week_risk"] <= 1500


def test_sleeve_accumulates_within_cycle():
    sigs = [Signal(f"S{i}", "bull", "connors_rsi2", price=5000, atr=50, has_vol_edge=False)
            for i in range(40)]   # 10×$5000 = $50K each → $95K sleeve fits ~1
    plan = build_plan(sigs, equity=107_846, etf_set=ETF)
    deployed = plan["risk_snapshot"]["stocks"]["deployed_usd"]
    assert deployed <= 95_000   # never exceeds the stock sleeve


def test_run_cycle_disabled_returns_none():
    # default flag OFF → no cycle
    assert run_cycle(100_000, ["AAPL"], ETF, enabled=False) is None


# ── execution safety rails (REQ-205 regime-skip, dedup, caps) ─────────────────
def test_regime_off_skips_all_entries():
    sigs = [Signal("AAPL", "bull", "connors_rsi2", price=200, atr=4, has_vol_edge=False)]
    plan = build_plan(sigs, equity=107_846, etf_set=ETF, risk_on=False)
    assert plan["planned"] == []
    assert any("risk-off" in r[1] for r in plan["skipped"])

def test_dedup_skips_held_symbols():
    sigs = [Signal("AAPL", "bull", "connors_rsi2", price=200, atr=4, has_vol_edge=False)]
    plan = build_plan(sigs, equity=107_846, etf_set=ETF, held_symbols={"AAPL"})
    assert plan["planned"] == []

def test_max_new_per_cycle_cap():
    sigs = [Signal(f"S{i}", "bull", "connors_rsi2", price=50, atr=1, has_vol_edge=False)
            for i in range(10)]
    plan = build_plan(sigs, equity=107_846, etf_set=ETF, max_new=3)
    assert len(plan["planned"]) == 3

def test_max_concurrent_cap_via_open_count():
    sigs = [Signal(f"S{i}", "bull", "connors_rsi2", price=50, atr=1, has_vol_edge=False)
            for i in range(10)]
    plan = build_plan(sigs, equity=107_846, etf_set=ETF, open_count=7, max_concurrent=8, max_new=5)
    assert len(plan["planned"]) == 1   # only 1 slot left (8-7)
