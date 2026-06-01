#!/usr/bin/env python3
"""
auto_engine.py — autonomous orchestrator (Phase 5b, SHADOW mode). Satisfies REQ-612.

Ties the decision modules into one cycle:
  strategies → signals → tier-prioritize → KB/debate gate → router → risk_brain
            → execution PLAN

DUAL_ENGINE_ENABLED defaults OFF. When enabled it runs in SHADOW: it computes the
full plan and LOGS what it WOULD trade alongside the current system, placing NO
orders. Going live (shadow→execute) is a later, deliberate flip — protects the
Connors incubation and lets us validate the pipeline end-to-end first.

`build_plan()` is pure (testable with synthetic signals). `generate_live_signals()`
does the data fetch. `run_cycle()` ties them and logs.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np

from trade_signal import Signal
from strategy import default_registry
from risk_brain import RiskBrain
from router import route_signal, RouteDecision, SPREADS_ENABLED

log = logging.getLogger("auto_engine")

DUAL_ENGINE_ENABLED = True    # SHADOW mode ON (logs intended trades, places NO
                              # orders). Validate the pipeline end-to-end before
                              # any live flip. Set False to silence the shadow loop.

# entry constants (match the validated backtests)
RSI_LO = 10.0


@dataclass
class PlannedTrade:
    signal: Signal
    decision: RouteDecision


# ── live signal generation (latest complete daily bar) ────────────────────────
def _fired(strat_name: str, df) -> bool:
    """Does `strat_name` fire an entry on the latest bar of `df`?"""
    r, p = df.iloc[-1], df.iloc[-2]
    if strat_name == "connors_rsi2":
        return r["rsi2"] < RSI_LO and r["close"] > r["sma200"]
    if strat_name == "bollinger_reversion":
        return (r["close"] < r["sma20"] - 2 * r["std20"]) and (r["close"] > r["sma200"])
    if strat_name == "trend_pullback":
        return (r["close"] > r["sma50"] > r["sma200"]) and (p["close"] < p["sma20"]) and (r["close"] > r["sma20"])
    if strat_name == "breakout_52w":
        return (r["close"] >= df["hi252"].iloc[-2]) and (r["close"] > r["sma200"])
    return False


def signals_for_symbol(sym: str, names: list[str], etf_set: Optional[set] = None) -> list[Signal]:
    """Prep `sym` ONCE, then check all strategies (avoids 4× redundant prep)."""
    from backtest_multi_strategy import _prep   # reuse indicator prep
    df = _prep(sym)
    if df is None or len(df) < 3:
        return []
    r = df.iloc[-1]
    if np.isnan(r.get("atr14", np.nan)) or r["atr14"] <= 0:
        return []
    asset = "etf" if (etf_set and sym.upper() in etf_set) else "stock"
    out = []
    for name in names:
        if _fired(name, df):
            out.append(Signal(symbol=sym, direction="bull", strategy=name,
                              strength=0.7, price=float(r["close"]),
                              atr=float(r["atr14"]), asset_class=asset))
    return out


def latest_signal(strat_name: str, sym: str, etf_set: Optional[set] = None) -> Optional[Signal]:
    """Single-strategy convenience wrapper (kept for callers/tests)."""
    sigs = signals_for_symbol(sym, [strat_name], etf_set)
    return sigs[0] if sigs else None


def generate_live_signals(universe: list[str], etf_set: set,
                          strategies: Optional[list[str]] = None) -> list[Signal]:
    reg = default_registry()
    names = strategies or [s.name for s in reg.all() if s.validated]
    out: list[Signal] = []
    for sym in universe:
        try:
            out.extend(signals_for_symbol(sym, names, etf_set))
        except Exception as e:
            log.debug(f"signal gen {sym}: {e}")
    return out


# ── pure plan builder (testable) ──────────────────────────────────────────────
def build_plan(signals: list[Signal], equity: float, etf_set: set,
               large_cap_set: Optional[set] = None,
               spreads_enabled: bool = SPREADS_ENABLED) -> dict:
    """Prioritize → route → size against a fresh RiskBrain; return the plan.
    Pure: no I/O, no order placement. RiskBrain accumulates within the cycle so
    sleeves/caps bind across the planned trades."""
    rb = RiskBrain(total_equity=equity)
    ordered = RiskBrain.prioritize(signals, etf_set, large_cap_set)
    planned: list[PlannedTrade] = []
    skipped: list[tuple[str, str]] = []
    for sig in ordered:
        d = route_signal(sig, rb, spreads_enabled=spreads_enabled)
        if d.route == "skip":
            skipped.append((sig.symbol, d.reason))
            continue
        rb.register_entry(d.route, d.est_cost_usd, d.est_risk_usd)
        planned.append(PlannedTrade(sig, d))
    return {
        "planned": planned,
        "skipped": skipped,
        "risk_snapshot": rb.snapshot(),
        "n_signals": len(signals),
    }


def format_plan(plan: dict) -> str:
    lines = [f"[auto-engine SHADOW] {len(plan['planned'])} planned / "
             f"{plan['n_signals']} signals / {len(plan['skipped'])} skipped"]
    for pt in plan["planned"]:
        s, d = pt.signal, pt.decision
        struct = f" {d.structure}" if d.structure else ""
        lines.append(f"  WOULD {d.route.upper()}{struct} {s.symbol} "
                     f"({s.strategy}) qty={d.qty} cost=${d.est_cost_usd:.0f} "
                     f"risk=${d.est_risk_usd:.0f} — {d.reason}")
    snap = plan["risk_snapshot"]
    lines.append(f"  sleeves: stocks free ${snap['stocks']['sleeve_usd']-snap['stocks']['deployed_usd']:.0f} "
                 f"| options free ${snap['options']['sleeve_usd']-snap['options']['deployed_usd']:.0f} "
                 f"| options week-risk ${snap['options_week_risk']:.0f}")
    return "\n".join(lines)


# ── full cycle (data → plan → shadow-log) ─────────────────────────────────────
def run_cycle(equity: float, universe: list[str], etf_set: set,
              large_cap_set: Optional[set] = None,
              enabled: bool = None) -> Optional[dict]:
    """Run one autonomous cycle. SHADOW: logs the plan, places no orders."""
    if enabled is None:
        enabled = DUAL_ENGINE_ENABLED
    if not enabled:
        return None
    signals = generate_live_signals(universe, etf_set)
    plan = build_plan(signals, equity, etf_set, large_cap_set)
    log.info(format_plan(plan))
    plan["mode"] = "shadow"
    return plan


if __name__ == "__main__":
    # synthetic demo of the pure planner
    etf = {"SPY", "QQQ"}
    sigs = [
        Signal("SPY", "bull", "trend_pullback", strength=0.6, price=560, atr=6, asset_class="etf"),
        Signal("AAPL", "bull", "connors_rsi2", strength=0.7, price=200, atr=4, has_vol_edge=False),
        Signal("NVDA", "bull", "connors_rsi2", strength=0.9, price=120, atr=3,
               has_vol_edge=True, ivr=22),
    ]
    plan = build_plan(sigs, equity=107_846, etf_set=etf)
    print(format_plan(plan))
