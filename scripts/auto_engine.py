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

DUAL_ENGINE_ENABLED = False   # master flag — default OFF (shadow only when on)

# entry constants (match the validated backtests)
RSI_LO = 10.0


@dataclass
class PlannedTrade:
    signal: Signal
    decision: RouteDecision


# ── live signal generation (latest complete daily bar) ────────────────────────
def latest_signal(strat_name: str, sym: str, etf_set: Optional[set] = None) -> Optional[Signal]:
    """Return today's Signal for `strat_name` on `sym`, or None if no entry fires.
    Uses the same entry conditions as the cost-robust-validated backtests."""
    from backtest_multi_strategy import _prep   # reuse indicator prep
    df = _prep(sym)
    if df is None or len(df) < 3:
        return None
    r, p = df.iloc[-1], df.iloc[-2]
    if np.isnan(r.get("atr14", np.nan)) or r["atr14"] <= 0:
        return None

    fired = False
    if strat_name == "connors_rsi2":
        fired = r["rsi2"] < RSI_LO and r["close"] > r["sma200"]
    elif strat_name == "bollinger_reversion":
        fired = (r["close"] < r["sma20"] - 2 * r["std20"]) and (r["close"] > r["sma200"])
    elif strat_name == "trend_pullback":
        fired = (r["close"] > r["sma50"] > r["sma200"]) and (p["close"] < p["sma20"]) and (r["close"] > r["sma20"])
    elif strat_name == "breakout_52w":
        fired = (r["close"] >= df["hi252"].iloc[-2]) and (r["close"] > r["sma200"])
    if not fired:
        return None

    asset = "etf" if (etf_set and sym.upper() in etf_set) else "stock"
    return Signal(symbol=sym, direction="bull", strategy=strat_name,
                  strength=0.7, price=float(r["close"]), atr=float(r["atr14"]),
                  asset_class=asset)


def generate_live_signals(universe: list[str], etf_set: set,
                          strategies: Optional[list[str]] = None) -> list[Signal]:
    reg = default_registry()
    names = strategies or [s.name for s in reg.all() if s.validated]
    out: list[Signal] = []
    for name in names:
        for sym in universe:
            try:
                s = latest_signal(name, sym, etf_set)
                if s:
                    out.append(s)
            except Exception as e:
                log.debug(f"signal gen {name}/{sym}: {e}")
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
