#!/usr/bin/env python3
"""
exit_engine.py — dynamic profit-protection + loss exit (REQ-608/609). Live version
of the L1 ladder validated 2026-05-31 (backtest_exit_ladders.py).

Operates on a VALUE series — option premium (debit) OR underlying price — and
maintains a monotonic protected floor: once a profit tier is reached, the stop
ratchets UP and never comes back down, so a winner can't become a loss and a big
winner can't give it all back (the operator's +X% examples).

Validated config (the one that beat the fixed baseline OOS on Connors + Trend,
improving PF AND drawdown): breakeven at +5%, trail 30% off the high-water mark,
lock +10% floor at +20% gain. Tighter configs whipsawed — do NOT shrink without
a re-backtest (REQ-608.4/603.3).

Per-strategy opt-in: breakout did NOT benefit, so the engine is enabled per
strategy, not globally.

Pure logic + per-position state. The position monitor calls update() each tick;
the engine never places orders.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class ExitConfig:
    be_trigger:   float = 0.05   # move stop to breakeven at +5% gain (REQ-608 tier1)
    trail:        float = 0.30   # give back 30% of the high-water-mark gain
    floor2_gain:  float = 0.20   # at +20% gain…
    floor2_lock:  float = 0.10   # …lock in at least +10% (monotonic floor)
    # loss side (REQ-609): initial stop as a fraction below entry (set per instrument)
    init_stop_frac: float = 0.50  # options: 50% of premium (§9). shares: pass ATR-derived.


@dataclass
class ExitState:
    entry: float
    hwm: float          # high-water mark of the value since entry
    stop: float         # current (monotonic) stop level
    tier: int = 0       # highest profit tier reached (for display)


class ExitEngine:
    def __init__(self, cfg: ExitConfig | None = None):
        self.cfg = cfg or ExitConfig()

    def init_position(self, entry: float, init_stop: float | None = None) -> ExitState:
        if entry <= 0:
            raise ValueError("entry must be > 0")
        stop = init_stop if init_stop is not None else entry * (1 - self.cfg.init_stop_frac)
        return ExitState(entry=entry, hwm=entry, stop=stop)

    def _protected_stop(self, st: ExitState) -> tuple[float, int]:
        """Compute the monotonic protected stop + tier from the high-water mark."""
        gain = (st.hwm - st.entry) / st.entry
        stop, tier = st.stop, st.tier
        c = self.cfg
        if gain >= c.be_trigger:                       # tier 1: breakeven + trail
            stop = max(stop, st.entry, st.hwm * (1 - c.trail))
            tier = max(tier, 1)
        if gain >= c.floor2_gain:                       # tier 2: lock a higher floor
            stop = max(stop, st.entry * (1 + c.floor2_lock))
            tier = max(tier, 2)
        return stop, tier

    def update(self, st: ExitState, high: float, low: float,
               last: float) -> tuple[str, str, ExitState]:
        """Advance one tick. Returns (action, reason, state).
        action ∈ {"hold", "exit"}.  high/low/last = this tick's value range.

        Order matters: we check the exit against the stop established on PRIOR
        ticks FIRST, then ratchet the floor. So a newly-raised breakeven/floor
        protects from the NEXT tick on and can never whipsaw-exit on the same
        bar that set it (conservative; matches 'the stop was already resting')."""
        # 1. exit against the existing (prior-tick) stop
        if low <= st.stop:
            gain_at_stop = (st.stop - st.entry) / st.entry
            why = ("breakeven/profit floor" if st.tier >= 1 else "initial stop")
            return "exit", f"{why} hit @ {st.stop:.2f} ({gain_at_stop:+.0%})", st
        # 2. then ratchet the protected floor for future ticks
        st.hwm = max(st.hwm, high)
        st.stop, st.tier = self._protected_stop(st)
        return "hold", f"tier {st.tier}, stop {st.stop:.2f}", st

    def snapshot(self, st: ExitState) -> dict:
        return {"entry": round(st.entry, 2), "hwm": round(st.hwm, 2),
                "stop": round(st.stop, 2), "tier": st.tier,
                "locked_gain_pct": round((st.stop - st.entry) / st.entry * 100, 1)}


if __name__ == "__main__":
    eng = ExitEngine()
    st = eng.init_position(entry=2.00)         # option debit $2.00, init stop $1.00
    print("init:", eng.snapshot(st))
    # value rises to +40% then reverses
    for hi, lo, last in [(2.10, 2.00, 2.05), (2.80, 2.40, 2.80), (2.80, 2.30, 2.35)]:
        act, why, st = eng.update(st, hi, lo, last)
        print(f"  hi={hi} lo={lo} -> {act}: {why} | {eng.snapshot(st)}")
