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
# #20: the engine can also place OPTIONS for vol-edge signals (ETFs + stocks).
# Defaults OFF (project safety rule #1 for new order paths) — wired + ready; flip
# on after a validation pass and the §9-OI fix (#28). Until then directional
# signals route to shares; the separate screener auto-exec lane covers live
# autonomous options in the meantime.
OPTIONS_ENGINE_ENABLED = False
# Operator 2026-06-02: stocks exit on PRIMARY ±2% bands; the dynamic trailing
# ladder + 21d time cap remain as the SIDEWAYS backstop. On a close, the stock
# auto-buy lane rotates capital into the next eligible screener pick.
STOCK_TAKE_PROFIT_PCT = 0.02
STOCK_STOP_PCT        = 0.02
# Time-stop on stall (#33): if green but no new high for STALL_MINUTES, lock the gain.
STALL_MINUTES         = 60
STALL_MIN_PROFIT_PCT  = 0.01
_JOURNAL_FILE = os.path.expanduser("~/.spy_trader/journal.jsonl")


def _journal_add(sym: str, kind: str, reason: str, pnl_pct: float, pnl_usd: float = 0.0) -> None:
    """Append a closed-trade event to the shared notes/journal (#34)."""
    try:
        import json as _j, datetime as _dt
        os.makedirs(os.path.dirname(_JOURNAL_FILE), exist_ok=True)
        with open(_JOURNAL_FILE, "a") as fh:
            fh.write(_j.dumps({"ts": _dt.datetime.now().isoformat(), "sym": sym,
                               "kind": kind, "reason": reason,
                               "pnl_pct": round(pnl_pct, 2), "pnl_usd": round(pnl_usd, 2)}) + "\n")
    except Exception:
        pass

# entry constants (match the validated backtests)
RSI_LO = 10.0

import os, json as _json
from pathlib import Path as _Path
POSITIONS_FILE = _Path.home() / ".spy_trader" / "auto_engine_positions.json"
MONTH_PNL_FILE = _Path.home() / ".spy_trader" / "auto_engine_month_pnl.json"
TRADES_LOG_FILE = _Path.home() / ".spy_trader" / "auto_engine_trades.json"


def _log_closed_trade(rec: dict) -> None:
    """Append a closed-trade record (append-only) for post-day review."""
    try:
        hist = []
        if TRADES_LOG_FILE.exists():
            hist = _json.loads(TRADES_LOG_FILE.read_text())
        hist.append(rec)
        TRADES_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        TRADES_LOG_FILE.write_text(_json.dumps(hist, indent=2))
    except Exception as e:
        log.warning(f"[auto-engine] log trade failed: {e}")


def eod_summary() -> str:
    """One-shot end-of-day review of the autonomous engine's CLOSED trades today.
    Aggregates n / win% / P&L overall and per-strategy. Logs + returns the text."""
    from datetime import date as _date
    today = _date.today().isoformat()
    try:
        hist = _json.loads(TRADES_LOG_FILE.read_text()) if TRADES_LOG_FILE.exists() else []
    except Exception:
        hist = []
    todays = [t for t in hist if t.get("exit_date") == today]
    open_now = _load_positions()
    if not todays and not open_now:
        msg = "[auto-engine EOD] no trades closed and no open positions today."
        log.info(msg); return msg
    wins = [t for t in todays if t.get("pnl_usd", 0) > 0]
    loss = [t for t in todays if t.get("pnl_usd", 0) < 0]
    tot = sum(t.get("pnl_usd", 0) for t in todays)
    wr = (len(wins) / len(todays) * 100) if todays else 0
    avg_slip = (sum(abs(t.get("entry_slippage_bps", 0)) for t in todays) / len(todays)) if todays else 0
    by_strat: dict[str, list] = {}
    for t in todays:
        by_strat.setdefault(t.get("strategy", "?"), []).append(t.get("pnl_usd", 0))
    lines = [
        "── [auto-engine] EOD review ──",
        f"  Closed today: {len(todays)}  ({len(wins)}W / {len(loss)}L, win {wr:.0f}%)  "
        f"P&L ${tot:+.0f}  avg entry-slippage {avg_slip:.1f}bp",
        f"  Open positions carried: {len(open_now)}",
    ]
    for st, pnls in sorted(by_strat.items(), key=lambda kv: -sum(kv[1])):
        lines.append(f"    {st:18} n={len(pnls):2}  P&L ${sum(pnls):+.0f}")
    msg = "\n".join(lines)
    log.info(msg)
    return msg


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
        if not _fired(name, df):
            continue
        sig = Signal(symbol=sym, direction="bull", strategy=name,
                     strength=0.7, price=float(r["close"]),
                     atr=float(r["atr14"]), asset_class=asset)
        # #20: when the options engine is enabled, express ETF signals as a
        # vol-edge route (ETF options are liquid — instrument-priority directive).
        # IV proxy = realized vol (HV); true IVR pending the Polygon feed. Gated by
        # the flag, so default behavior (all signals → shares) is unchanged.
        if OPTIONS_ENGINE_ENABLED and asset == "etf":
            try:
                rets = np.log(df["close"]).diff().dropna().tail(20)
                hv = float(rets.std() * np.sqrt(252) * 100) if len(rets) else 0.0
                sig.has_vol_edge = True
                sig.ivr = round(hv)
            except Exception:
                pass
        out.append(sig)
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
    # NOTE: the bull/bear debate is NOT run on the daily auto path. The debate
    # needs the full intraday indicator set (price/RSI/VWAP/EMA/vol/ATR); a daily
    # Signal doesn't carry it, so the debate would reject everything for "missing
    # data". The daily strategies are cost-robust-validated (§12) AND clear the
    # KB-principles gate above (the data-matched filters), which is sufficient.
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
        if d.route == "options":
            if not OPTIONS_ENGINE_ENABLED:
                log.info(f"[auto-engine] {s.symbol} routes to OPTIONS — engine options "
                         f"path disabled (OPTIONS_ENGINE_ENABLED=False); skipping")
                continue
            opos = _execute_option(s, d, dry_run=dry_run)
            if opos is not None:
                positions.append(opos)
                held.add(s.symbol)
                open_risk += float(opos.get("entry_debit") or 0.0) * 100
            continue
        if d.route != "stocks":
            continue
        res = shares_executor.buy(s.symbol, d.qty, dry_run=dry_run)
        if not res.get("success"):
            continue
        # actual fill (entry slippage vs the signal price) for review
        fill = res.get("fill_price") or s.price
        slip_bps = round((fill - s.price) / s.price * 1e4, 1) if s.price else 0.0
        init_stop = fill - 2.0 * s.atr if s.atr > 0 else fill * 0.92
        st = eng.init_position(entry=fill, init_stop=init_stop)
        positions.append({
            "sym": s.symbol, "strategy": s.strategy, "route": "stocks",
            "qty": d.qty, "entry_price": fill, "signal_price": s.price,
            "entry_slippage_bps": slip_bps,
            "entry_date": _date.today().isoformat(),
            "order_id": res.get("order_id"), "exit_state": _asdict(st), "dry_run": dry_run,
        })
        held.add(s.symbol)
        open_risk += max(0.0, (s.price - init_stop)) * d.qty   # for the 6% rule
        log.info(f"[auto-engine] OPENED {s.symbol} {d.qty}sh @ ~{s.price:.2f} ({s.strategy})"
                 f"{' [dry]' if dry_run else ''}")
    _save_positions(positions)
    return positions


def record_stock_position(sym: str, qty: int, entry: float, strategy: str = "external",
                          atr: float = 0.0, dry_run: bool = False,
                          stop_pct: float = 0.08) -> bool:
    """Bring an externally-bought stock (screener auto-buy, manual, or any account
    position opened outside the engine) under dynamic exit management (REQ-608/609):
    append it to the managed store with an exit_state so manage_exits trails a stop,
    locks a profit floor, and enforces the time cap. No-op if already tracked.
    Stop = entry − 2×ATR when ATR is known, else an 8% initial stop. Returns True
    if newly added."""
    from dataclasses import asdict as _asdict
    from datetime import date as _date
    sym = sym.upper()
    entry = float(entry or 0.0)
    if entry <= 0 or qty <= 0:
        return False
    positions = _load_positions()
    if any(p.get("sym") == sym for p in positions):
        return False
    init_stop = (entry - 2.0 * atr) if (atr and atr > 0) else entry * (1.0 - stop_pct)
    st = ExitEngine().init_position(entry=entry, init_stop=init_stop)
    positions.append({
        "sym": sym, "strategy": strategy, "route": "stocks",
        "qty": int(qty), "entry_price": entry, "signal_price": entry,
        "entry_slippage_bps": 0.0, "entry_date": _date.today().isoformat(),
        "order_id": None, "exit_state": _asdict(st), "dry_run": dry_run,
    })
    _save_positions(positions)
    log.info(f"[auto-engine] now managing {sym} {qty}sh @ ${entry:.2f} "
             f"(stop ${init_stop:.2f}) — {strategy}")
    return True


def _execute_option(signal, decision, dry_run: bool = False) -> Optional[dict]:
    """Place a PAPER option order for an options-routed signal (#20) and return the
    position record, or None if it didn't fill / failed a gate. Reuses the
    well-tested screener_executor, including its KB §9 liquidity gates."""
    import screener_executor
    from datetime import date as _date, timedelta as _td
    struct = (decision.structure or "").lower()
    opt_type = "Put" if "put" in struct else "Call"
    exec_structure = (f"Debit {opt_type} Spread" if "spread" in struct else f"ATM {opt_type}")
    payload = {
        "sym":       signal.symbol,
        "structure": exec_structure,
        "expiry":    (_date.today() + _td(days=25)).isoformat(),     # KB §25 Saliba 21-28 DTE
        "opt_type":  opt_type,
        "max_risk":  min(float(decision.est_risk_usd or 500.0), 500.0),  # REQ-607 $500/trade
    }
    res = screener_executor.execute_screener_option(payload, dry_run=dry_run)
    if not res.get("success"):
        log.info(f"[auto-engine] {signal.symbol} option not placed — {res.get('message','')}")
        return None
    debit = float(res.get("actual_debit") or 0.0)
    log.info(f"[auto-engine] OPENED {signal.symbol} OPTION {exec_structure} "
             f"debit=${debit:.2f}{' [dry]' if dry_run else ''}")
    return {
        "sym": signal.symbol, "strategy": signal.strategy, "route": "options",
        "structure": exec_structure, "opt_type": opt_type, "qty": 1,
        "long_occ": res.get("long_occ"), "short_occ": res.get("short_occ"),
        "entry_debit": debit, "entry_price": signal.price,
        "expiry": payload["expiry"], "entry_date": _date.today().isoformat(),
        "order_id": res.get("long_order_id"), "dry_run": dry_run,
    }


def _manage_option_exit(p: dict, dry_run: bool = False) -> bool:
    """Exit management for an engine OPTIONS position (#20). Returns True to keep it
    open. Currently a TIME_CAP_DAYS hold-limit exit (closes the leg(s) best-effort);
    a dynamic debit-based profit-floor/loss ladder is a refinement that needs a live
    option mark (tracked with the §9-OI work)."""
    from datetime import date as _date
    try:
        held_days = (_date.today() - _date.fromisoformat(p["entry_date"])).days
    except Exception:
        held_days = 0
    if held_days < TIME_CAP_DAYS:
        return True
    if not p.get("dry_run", dry_run):
        try:
            import spy_auto_trader as _t
            c = getattr(_t, "TRADING_CLIENT", None)
            if c is not None:
                for occ in (p.get("long_occ"), p.get("short_occ")):
                    if occ:
                        try:
                            c.close_position(occ)
                        except Exception as e:
                            log.warning(f"[auto-engine] close {occ}: {e}")
        except Exception as e:
            log.warning(f"[auto-engine] option close {p['sym']}: {e}")
    _log_closed_trade({
        "sym": p["sym"], "strategy": p.get("strategy"), "route": "options",
        "qty": p.get("qty", 1), "structure": p.get("structure"),
        "entry_debit": p.get("entry_debit"), "entry_date": p.get("entry_date"),
        "exit_date": _date.today().isoformat(), "hold_days": held_days,
        "reason": f"time cap {held_days}d", "dry_run": p.get("dry_run", dry_run),
    })
    log.info(f"[auto-engine] CLOSED OPTION {p['sym']}: time cap {held_days}d")
    return False


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
        if p.get("route") == "options":
            if _manage_option_exit(p, dry_run=dry_run):
                still_open.append(p)
            continue
        if p.get("route") != "stocks":
            still_open.append(p); continue
        px = shares_executor.current_price(p["sym"])
        if px is None:
            still_open.append(p); continue
        entry = p.get("entry_price", px)
        chg = (px - entry) / entry if entry else 0.0
        # Stall tracking (#33): remember the peak gain + when it was last set.
        import datetime as _dt2
        _nowiso = _dt2.datetime.now().isoformat()
        if "peak_pct" not in p or chg > p.get("peak_pct", -9.9):
            p["peak_pct"] = chg
            p["peak_ts"]  = _nowiso
        try:
            stall_min = (_dt2.datetime.now() - _dt2.datetime.fromisoformat(p.get("peak_ts", _nowiso))).total_seconds() / 60
        except Exception:
            stall_min = 0.0
        stalled = chg >= STALL_MIN_PROFIT_PCT and stall_min >= STALL_MINUTES
        # PRIMARY: fixed ±2% bands. Then a time-stop if green-but-stalled. Else the
        # dynamic trailing ladder as the SIDEWAYS backstop; 21d cap is max-time.
        if chg >= STOCK_TAKE_PROFIT_PCT:
            action, why = "exit", f"take-profit +{STOCK_TAKE_PROFIT_PCT*100:.0f}%"
        elif chg <= -STOCK_STOP_PCT:
            action, why = "exit", f"stop -{STOCK_STOP_PCT*100:.0f}%"
        elif stalled:
            action, why = "exit", f"time-stop {int(stall_min)}min stalled +{chg*100:.1f}%"
        else:
            st = ExitState(**p["exit_state"])
            action, why, st = eng.update(st, high=px, low=px, last=px)
            p["exit_state"] = _asdict(st)
        held_days = (_date.today() - _date.fromisoformat(p["entry_date"])).days
        if action == "exit" or held_days >= TIME_CAP_DAYS:
            reason = why if action == "exit" else f"time cap {held_days}d"
            shares_executor.close(p["sym"], dry_run=p.get("dry_run", dry_run))
            entry = p.get("entry_price", px)
            realized = (px - entry) * p.get("qty", 0)
            pnl_pct = round((px - entry) / entry * 100, 2) if entry else 0.0
            _record_realized(realized)   # feed the monthly 6% rule (REQ-611)
            _log_closed_trade({          # append-only review log
                "sym": p["sym"], "strategy": p.get("strategy"), "route": "stocks",
                "qty": p.get("qty"), "entry_price": entry, "exit_price": round(px, 2),
                "entry_date": p.get("entry_date"), "exit_date": _date.today().isoformat(),
                "hold_days": held_days, "pnl_usd": round(realized, 2), "pnl_pct": pnl_pct,
                "reason": reason, "entry_slippage_bps": p.get("entry_slippage_bps", 0),
                "dry_run": p.get("dry_run", dry_run),
            })
            _journal_add(p["sym"], "stock", reason, pnl_pct, realized)
            log.info(f"[auto-engine] CLOSED {p['sym']}: {reason}  "
                     f"P&L ${realized:+.0f} ({pnl_pct:+.1f}%)")
        else:
            # stash live price + P&L so the UI can show it for free (no extra API call)
            entry = p.get("entry_price", px)
            p["last_price"] = round(px, 2)
            p["pnl_usd"] = round((px - entry) * p.get("qty", 0), 2)
            p["pnl_pct"] = round((px - entry) / entry * 100, 2) if entry else 0.0
            still_open.append(p)
    _save_positions(still_open)


TIME_CAP_DAYS = 21  # REQ-608: max hold for a stock position before forced exit


def positions_snapshot() -> list[dict]:
    """Compact view of the autonomous engine's open positions for the UI."""
    from datetime import date as _date
    out = []
    for p in _load_positions():
        st = p.get("exit_state", {})
        entry = p.get("entry_price")
        stop = st.get("stop")
        held = None
        if p.get("entry_date"):
            try:
                held = (_date.today() - _date.fromisoformat(p["entry_date"])).days
            except Exception:
                held = None
        # exit plan: trailing stop ratchets up (no fixed target — winners ride it),
        # backstopped by a TIME_CAP_DAYS hold limit. Once the stop locks above entry
        # it's a profit floor, not just a stop.
        profit_floor = stop is not None and entry is not None and stop >= entry
        out.append({
            "sym": p.get("sym"), "qty": p.get("qty"),
            "strategy": p.get("strategy"), "entry": entry,
            "last": p.get("last_price"), "stop": stop,
            "tier": st.get("tier", 0), "pnl_usd": p.get("pnl_usd"),
            "pnl_pct": p.get("pnl_pct"), "dry_run": p.get("dry_run", False),
            "held_days": held,
            "days_to_cap": (TIME_CAP_DAYS - held) if held is not None else None,
            "profit_floor": profit_floor,
        })
    return out


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
