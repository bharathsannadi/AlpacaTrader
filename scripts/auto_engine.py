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
from exit_engine import ExitEngine, ExitState

log = logging.getLogger("auto_engine")

DUAL_ENGINE_ENABLED = True    # master on/off for the autonomous loop
DUAL_ENGINE_MODE    = "execute"  # "shadow" (log only) | "execute" (place PAPER orders)
MAX_CONCURRENT      = 8        # hard cap on open autonomous positions
MAX_NEW_PER_CYCLE   = 3        # hard cap on new entries per cycle

# entry constants (match the validated backtests)
RSI_LO = 10.0

import os, json as _json
from pathlib import Path as _Path
POSITIONS_FILE = _Path.home() / ".spy_trader" / "auto_engine_positions.json"
MONTH_PNL_FILE = _Path.home() / ".spy_trader" / "auto_engine_month_pnl.json"


def _open_risk(positions: list[dict]) -> float:
    """Total open risk on held stock positions = Σ (entry − stop) × qty.
    A position stopped at/above breakeven contributes 0 (Elder open-risk rule)."""
    total = 0.0
    for p in positions:
        if p.get("route") != "stocks":
            continue
        st = p.get("exit_state", {})
        entry, stop = st.get("entry", 0), st.get("stop", 0)
        total += max(0.0, (entry - stop)) * p.get("qty", 0)
    return round(total, 2)


def _month_key() -> str:
    from datetime import date as _date
    return _date.today().strftime("%Y-%m")


def _month_loss() -> float:
    """This month's realized NET LOSS (0 if net positive) — for Elder's 6% rule."""
    try:
        if MONTH_PNL_FILE.exists():
            d = _json.loads(MONTH_PNL_FILE.read_text())
            if d.get("month") == _month_key():
                return max(0.0, -float(d.get("realized", 0.0)))
    except Exception:
        pass
    return 0.0


def _record_realized(realized_usd: float) -> None:
    """Accumulate realized P&L for the current month (resets on month change)."""
    try:
        cur = {"month": _month_key(), "realized": 0.0}
        if MONTH_PNL_FILE.exists():
            d = _json.loads(MONTH_PNL_FILE.read_text())
            if d.get("month") == _month_key():
                cur = d
        cur["realized"] = round(float(cur.get("realized", 0.0)) + realized_usd, 2)
        MONTH_PNL_FILE.parent.mkdir(parents=True, exist_ok=True)
        MONTH_PNL_FILE.write_text(_json.dumps(cur))
    except Exception as e:
        log.warning(f"[auto-engine] record realized failed: {e}")


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
               spreads_enabled: bool = SPREADS_ENABLED,
               risk_on: bool = True,
               held_symbols: Optional[set] = None,
               open_count: int = 0,
               max_concurrent: int = MAX_CONCURRENT,
               max_new: int = MAX_NEW_PER_CYCLE) -> dict:
    """Prioritize → route → size against a fresh RiskBrain; return the plan.
    Pure: no I/O, no order placement.

    Safety rails baked in (the operator wanted them on for testing):
      • REGIME-SKIP (validated 2026-05-31): if not risk_on (SPY<200SMA), no new entries
      • dedup: skip a symbol we already hold (held_symbols)
      • caps: ≤ max_new this cycle, ≤ max_concurrent total open positions
      • sleeves/caps via RiskBrain (REQ-602/605/606)"""
    held = {s.upper() for s in (held_symbols or set())}
    if not risk_on:
        return {"planned": [], "skipped": [("ALL", "regime risk-off (SPY<200SMA) — no new entries")],
                "risk_snapshot": RiskBrain(total_equity=equity).snapshot(),
                "n_signals": len(signals)}
    rb = RiskBrain(total_equity=equity)
    ordered = RiskBrain.prioritize(signals, etf_set, large_cap_set)
    planned: list[PlannedTrade] = []
    skipped: list[tuple[str, str]] = []
    slots = max(0, max_concurrent - open_count)
    seen: set = set()
    for sig in ordered:
        if len(planned) >= max_new or len(planned) >= slots:
            skipped.append((sig.symbol, "cap reached (max_new/concurrent)")); continue
        if sig.symbol in held or sig.symbol in seen:
            skipped.append((sig.symbol, "already held / duplicate")); continue
        d = route_signal(sig, rb, spreads_enabled=spreads_enabled)
        if d.route == "skip":
            skipped.append((sig.symbol, d.reason)); continue
        rb.register_entry(d.route, d.est_cost_usd, d.est_risk_usd)
        planned.append(PlannedTrade(sig, d)); seen.add(sig.symbol)
    return {"planned": planned, "skipped": skipped,
            "risk_snapshot": rb.snapshot(), "n_signals": len(signals)}


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


# ── position store + regime + execution ───────────────────────────────────────
def _load_positions() -> list[dict]:
    try:
        if POSITIONS_FILE.exists():
            return _json.loads(POSITIONS_FILE.read_text())
    except Exception:
        pass
    return []


def _save_positions(positions: list[dict]) -> None:
    try:
        POSITIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = POSITIONS_FILE.with_suffix(".tmp")
        tmp.write_text(_json.dumps(positions, indent=2))
        tmp.replace(POSITIONS_FILE)
    except Exception as e:
        log.warning(f"[auto-engine] save positions failed: {e}")


def spy_risk_on() -> bool:
    """REGIME gate (validated 2026-05-31): True when SPY > its 200-SMA.
    Fail-safe = False (risk-off → no new entries) if SPY data is unavailable."""
    try:
        from backtest_multi_strategy import _prep
        df = _prep("SPY")
        if df is None or len(df) < 1:
            return False
        r = df.iloc[-1]
        return bool(r["close"] > r["sma200"])
    except Exception:
        return False


def _signal_gate(sig, route: str, vix, risk_on: bool) -> tuple[bool, str]:
    """Per-trade KB-principles + debate gate for the auto path (REQ-004/005)."""
    import kb_principles
    from strategy import default_registry
    spec = default_registry().get(sig.strategy)
    pf = spec.test_pf_3bp if spec else None
    sc = kb_principles.score_signal(pf, sig.strength, sig.asset_class, vix=vix,
                                    risk_on=risk_on, has_vol_edge=sig.has_vol_edge,
                                    route=route)
    if sc["pct"] < kb_principles.KB_MATCH_MIN:
        return False, f"KB match {sc['pct']}% < {kb_principles.KB_MATCH_MIN}% — {';'.join(sc['failed'][:2])}"
    # debate gate (only if enabled + key present); fail-closed
    try:
        import spy_auto_trader as trader
        if getattr(trader, "DEBATE_ENABLED", False):
            import debate as _d
            ind = {"strategy": sig.strategy, "price": sig.price, "atr": sig.atr,
                   "kb_match": sc["pct"]}
            proceed, conf, summ = _d.run_debate(sig.symbol, sig.direction, ind)
            if not proceed:
                return False, f"debate suppressed (conf {conf:.2f}): {summ}"
    except Exception as e:
        return False, f"debate gate error (failing closed): {e}"
    return True, f"KB {sc['pct']}% ✓"


def execute_plan(plan: dict, dry_run: bool = False,
                 vix=None, risk_on: bool = True, equity: float = 0.0) -> list[dict]:
    """Place PAPER orders for the planned trades; record positions w/ exit state.
    Each trade clears the per-trade KB-principles + debate gate (REQ-004/005) AND
    Elder's 6% monthly open-risk rule (REQ-611).
    Shares are executed; options execution is DEFERRED (needs contract selection)."""
    import shares_executor
    from dataclasses import asdict as _asdict
    from datetime import date as _date
    eng = ExitEngine()
    positions = _load_positions()
    held = {p["sym"] for p in positions}
    rb = RiskBrain(total_equity=equity) if equity > 0 else None
    open_risk = _open_risk(positions)
    month_loss = _month_loss()
    for pt in plan["planned"]:
        s, d = pt.signal, pt.decision
        if s.symbol in held:
            continue
        # ── per-trade KB-principles + debate gate ──
        ok, why = _signal_gate(s, d.route, vix, risk_on)
        if not ok:
            log.info(f"[auto-engine] ⛔ {s.symbol} gate-blocked — {why}")
            continue
        # ── Elder 6% monthly open-risk breaker (REQ-611) ──
        if rb is not None:
            ok6, why6 = rb.six_percent_ok(d.est_risk_usd, open_risk, month_loss)
            if not ok6:
                log.info(f"[auto-engine] ⛔ {s.symbol} {why6}")
                continue
        if d.route != "stocks":
            log.info(f"[auto-engine] {s.symbol} routes to OPTIONS — execution deferred "
                     f"(needs contract selection); skipping")
            continue
        res = shares_executor.buy(s.symbol, d.qty, dry_run=dry_run)
        if not res.get("success"):
            continue
        init_stop = s.price - 2.0 * s.atr if s.atr > 0 else s.price * 0.92
        st = eng.init_position(entry=s.price, init_stop=init_stop)
        positions.append({
            "sym": s.symbol, "strategy": s.strategy, "route": "stocks",
            "qty": d.qty, "entry_price": s.price, "entry_date": _date.today().isoformat(),
            "order_id": res.get("order_id"), "exit_state": _asdict(st), "dry_run": dry_run,
        })
        held.add(s.symbol)
        open_risk += max(0.0, (s.price - init_stop)) * d.qty   # for the 6% rule
        log.info(f"[auto-engine] OPENED {s.symbol} {d.qty}sh @ ~{s.price:.2f} ({s.strategy})"
                 f"{' [dry]' if dry_run else ''}")
    _save_positions(positions)
    return positions


def manage_exits(dry_run: bool = False) -> None:
    """Run the dynamic exit (REQ-608/609) on each held position; close when it fires
    or a 21-trading-day time cap is hit. Called from the position monitor."""
    import shares_executor
    from dataclasses import asdict as _asdict
    from datetime import date as _date
    positions = _load_positions()
    if not positions:
        return
    eng = ExitEngine()
    still_open = []
    for p in positions:
        if p.get("route") != "stocks":
            still_open.append(p); continue
        px = shares_executor.current_price(p["sym"])
        if px is None:
            still_open.append(p); continue
        st = ExitState(**p["exit_state"])
        action, why, st = eng.update(st, high=px, low=px, last=px)
        p["exit_state"] = _asdict(st)
        held_days = (_date.today() - _date.fromisoformat(p["entry_date"])).days
        if action == "exit" or held_days >= 21:
            reason = why if action == "exit" else f"time cap {held_days}d"
            shares_executor.close(p["sym"], dry_run=p.get("dry_run", dry_run))
            realized = (px - p.get("entry_price", px)) * p.get("qty", 0)
            _record_realized(realized)   # feed the monthly 6% rule (REQ-611)
            log.info(f"[auto-engine] CLOSED {p['sym']}: {reason}  P&L ${realized:+.0f}")
        else:
            still_open.append(p)
    _save_positions(still_open)


# ── full cycle (data → plan → shadow-log OR execute) ──────────────────────────
def run_cycle(equity: float, universe: list[str], etf_set: set,
              large_cap_set: Optional[set] = None,
              enabled: bool = None, mode: str = None,
              dry_run: bool = False, vix: float = None) -> Optional[dict]:
    """Run one autonomous cycle.
    mode 'shadow' → log the plan; mode 'execute' → place PAPER orders (all rails on)."""
    if enabled is None:
        enabled = DUAL_ENGINE_ENABLED
    if mode is None:
        mode = DUAL_ENGINE_MODE
    if not enabled:
        return None
    risk_on = spy_risk_on()
    held = {p["sym"] for p in _load_positions()}
    open_count = len(held)
    signals = generate_live_signals(universe, etf_set)
    plan = build_plan(signals, equity, etf_set, large_cap_set,
                      risk_on=risk_on, held_symbols=held, open_count=open_count)
    plan["mode"] = mode
    plan["risk_on"] = risk_on
    log.info(f"[regime {'RISK-ON' if risk_on else 'RISK-OFF (skip new)'}] " + format_plan(plan))
    if mode == "execute":
        execute_plan(plan, dry_run=dry_run, vix=vix, risk_on=risk_on, equity=equity)
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
