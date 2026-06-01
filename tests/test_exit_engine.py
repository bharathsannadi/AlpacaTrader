"""Tests for exit_engine — dynamic profit-floor ladder (REQ-608/609)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from exit_engine import ExitEngine, ExitConfig, ExitState


def test_init_position_default_stop():
    eng = ExitEngine()
    st = eng.init_position(entry=2.00)        # default init_stop_frac 0.50
    assert st.stop == 1.00 and st.hwm == 2.00 and st.tier == 0

def test_breakeven_activates_at_trigger():
    eng = ExitEngine()  # be_trigger +5%
    st = eng.init_position(entry=100.0, init_stop=90.0)
    # rise to +5% → stop should ratchet to at least breakeven (entry)
    eng.update(st, high=105.0, low=100.0, last=105.0)
    assert st.tier >= 1 and st.stop >= 100.0

def test_no_whipsaw_on_bar_that_sets_breakeven():
    # the bar that first reaches +5% has a low at entry; must NOT exit on that bar
    eng = ExitEngine()
    st = eng.init_position(entry=100.0, init_stop=90.0)
    action, _, st = eng.update(st, high=105.0, low=100.0, last=102.0)
    assert action == "hold"   # protected from next tick on, not this one

def test_winner_cannot_become_loss():
    eng = ExitEngine()
    st = eng.init_position(entry=2.00, init_stop=1.00)
    eng.update(st, 2.10, 2.00, 2.05)          # +5% → breakeven
    # now it reverses below entry
    action, why, st = eng.update(st, 2.10, 1.90, 1.90)
    assert action == "exit" and st.stop >= 2.00   # exits at >= breakeven, no loss

def test_tier2_locks_higher_floor():
    eng = ExitEngine()  # floor2 at +20% locks +10%
    st = eng.init_position(entry=2.00, init_stop=1.00)
    eng.update(st, 2.10, 2.05, 2.10)          # +5% breakeven
    eng.update(st, 2.50, 2.40, 2.50)          # +25% → tier 2, floor +10% = 2.20
    assert st.tier == 2 and st.stop >= 2.20
    # reverse to 2.15 → breaches 2.20 floor → exit locking ~+10%
    action, why, st = eng.update(st, 2.50, 2.15, 2.15)
    assert action == "exit" and st.stop == 2.20

def test_floor_is_monotonic():
    eng = ExitEngine()
    st = eng.init_position(entry=2.00, init_stop=1.00)
    eng.update(st, 2.50, 2.40, 2.50)          # tier 2, stop 2.20
    s1 = st.stop
    eng.update(st, 2.10, 2.05, 2.10)          # pullback — stop must not drop
    assert st.stop == s1 >= 2.20

def test_initial_stop_fires_before_any_profit():
    eng = ExitEngine()
    st = eng.init_position(entry=2.00, init_stop=1.00)
    action, why, st = eng.update(st, 1.50, 0.95, 0.95)   # drops to init stop
    assert action == "exit" and "initial stop" in why

def test_shares_atr_stop_via_init_stop():
    eng = ExitEngine()
    # shares: pass an ATR-derived init stop instead of the 50%-premium default
    st = eng.init_position(entry=100.0, init_stop=92.0)   # 2×ATR below
    assert st.stop == 92.0

def test_snapshot_reports_locked_gain():
    eng = ExitEngine()
    st = eng.init_position(entry=2.00, init_stop=1.00)
    eng.update(st, 2.50, 2.40, 2.50)
    snap = eng.snapshot(st)
    assert snap["tier"] == 2 and snap["locked_gain_pct"] == 10.0
