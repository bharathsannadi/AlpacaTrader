"""CI guards for the 2026-06-04 hardening: shared sizing (AH-2/CR-6), slippage (OB-1),
alerting (OB-2), reconcile loop (OB-4). Locks the behaviour we verified by hand into CI."""
import sys, os, json, datetime as dt
from types import SimpleNamespace
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import config
import screener_executor as se
import app


# ── AH-2 / CR-6: one shared size_position ────────────────────────────────────
def test_size_position_stocks_equal_dollar():
    assert config.size_position("stocks", 200) == 25      # ~$5000
    assert config.size_position("stocks", 50) == 100
    assert config.size_position("stocks", 0) == 0         # unusable price → caller skips


def test_size_position_options_fills_ceiling():
    assert config.size_position("options", per_contract_cost=200, ceiling=600) == 3   # ~$600
    assert config.size_position("options", per_contract_cost=580, ceiling=600) == 1
    assert config.size_position("options", per_contract_cost=700, ceiling=600) == 0   # 1 won't fit


# ── OB-1: slippage ledger (model mid vs fill, bps) ───────────────────────────
def test_record_slippage_bps_and_skip(monkeypatch, tmp_path):
    path = tmp_path / "slippage.jsonl"
    monkeypatch.setattr(se, "_SLIPPAGE_PATH", str(path))
    se._record_slippage("NVDA", "long", 5.00, 5.10, 2)    # paid up → +200 bps
    se._record_slippage("XLF", "short", 4.00, 3.90, 1)    # got less → +250 bps
    se._record_slippage("X", "long", 0, 1.0, 1)           # no expected → skip
    rows = [json.loads(l) for l in open(path)]
    assert len(rows) == 2
    assert rows[0]["slip_bps"] == 200.0 and rows[1]["slip_bps"] == 250.0


# ── OB-2: alert helper (always logs; posts only when webhook configured) ──────
def test_alert_logs_and_optional_webhook(monkeypatch):
    logs = []
    monkeypatch.setattr(app, "_emit_log", lambda m, **k: logs.append(m))
    monkeypatch.delenv("ALERT_WEBHOOK_URL", raising=False)
    app._alert("BREAKER", "tripped")
    assert any("🚨 ALERT — BREAKER" in m for m in logs)
    posted = {}
    monkeypatch.setenv("ALERT_WEBHOOK_URL", "http://hook")
    import urllib.request as u
    monkeypatch.setattr(u, "urlopen",
                        lambda req, timeout=5: (posted.update(url=req.full_url),
                                                SimpleNamespace(read=lambda: b"ok"))[1])
    app._alert("X", "y")
    assert posted.get("url") == "http://hook"


# ── OB-4: reconcile cancels stale unfilled orders, alerts phantom positions ───
def test_reconcile_cancels_stale_and_alerts_phantom(monkeypatch):
    now = dt.datetime.now(dt.timezone.utc)

    class Client:
        def __init__(self): self.cancelled = []
        def get_orders(self, req=None):
            return [SimpleNamespace(id="O1", symbol="AMZNc", filled_qty=0,
                                    created_at=now - dt.timedelta(minutes=20)),
                    SimpleNamespace(id="O2", symbol="NVDAc", filled_qty=0,
                                    created_at=now - dt.timedelta(minutes=1))]
        def cancel_order_by_id(self, i): self.cancelled.append(i)

    c = Client()
    monkeypatch.setattr(app.trader, "TRADING_CLIENT", c, raising=False)
    logs = []
    monkeypatch.setattr(app, "_emit_log", lambda m, **k: logs.append(m))
    monkeypatch.setattr(app, "_account_equity_positions", lambda: [])
    monkeypatch.setattr(app, "_account_option_positions", lambda: [])
    monkeypatch.setattr(app.dtrad, "_load_positions",
                        lambda: [{"sym": "AMZN", "status": "pending"},
                                 {"sym": "GOOG", "status": "signal"}])
    app._reconcile_orders_positions()
    assert c.cancelled == ["O1"]                                   # only the 20-min stale one
    assert any("phantom" in m and "AMZN" in m for m in logs)       # pending, not in account
    assert not any("GOOG" in m for m in logs)                      # 'signal' is not a phantom


# ── Concentration cap (2026-06-05): total open positions across BOTH lanes ─────
def test_concentration_cap_constant():
    assert config.MAX_PORTFOLIO_POSITIONS == 12
    assert app.MAX_PORTFOLIO_POSITIONS == config.MAX_PORTFOLIO_POSITIONS


def test_portfolio_position_count_sums_both_lanes(monkeypatch):
    monkeypatch.setattr(app, "_account_equity_positions", lambda: [1, 2, 3])
    monkeypatch.setattr(app, "_account_option_positions", lambda: [4, 5])
    assert app._portfolio_position_count() == 5


def test_portfolio_position_count_fails_safe_on_error(monkeypatch):
    def boom(): raise RuntimeError("api down")
    monkeypatch.setattr(app, "_account_equity_positions", boom)
    assert app._portfolio_position_count() == -1   # -1 → caller opens nothing


def _arm(monkeypatch):
    """Arm both lanes: logged-in, market open, not dry — so only the caps gate.
    Also lifts the option-lane kill-switch (off by default since the 2026-06-12
    edge review) so the option-lane cap tests reach the guard they exercise."""
    monkeypatch.setitem(app.state, "auto_execute_options", True)
    monkeypatch.setitem(app.state, "logged_in", True)
    monkeypatch.setitem(app.state, "dry_run", False)
    monkeypatch.setattr(app.screener, "_is_market_open", lambda: True)
    monkeypatch.setattr(app, "AUTO_EXEC_OPTIONS_ENABLED", True)
    # Neutralize the entry-time window (edge review 2026-06-27) so cap tests aren't
    # wall-clock dependent — _arm's job is to leave only the caps gating.
    monkeypatch.setattr(app, "ENTRY_WINDOW_END_MIN", 24 * 60)


def _write_ledger(tmp_path, monkeypatch, rows):
    """Point the cooldown at a temp REAL ledger of {sym, pnl_usd} rows (timestamped
    now so they fall inside the trailing window). A losing close = pnl_usd < 0."""
    p = tmp_path / "real_trades.jsonl"
    now = dt.datetime.now().isoformat()
    with open(p, "w") as fh:
        for r in rows:
            fh.write(json.dumps({"ts": now, "dry_run": False, **r}) + "\n")
    monkeypatch.setattr(app, "_REAL_TRADES_FILE", str(p))
    return p


def test_cooldown_blocks_repeat_loser(tmp_path, monkeypatch):
    """A name with >= MIN_STOPS losing real closes AND net negative is blocked."""
    n = config.SYMBOL_COOLDOWN_MIN_STOPS
    _write_ledger(tmp_path, monkeypatch, [{"sym": "GLD", "pnl_usd": -300.0}] * n)
    assert "GLD" in app._cooldown_blocked_symbols()


def test_cooldown_passes_net_positive_churner(tmp_path, monkeypatch):
    """A high-churn name that loses often but still nets positive keeps trading."""
    n = config.SYMBOL_COOLDOWN_MIN_STOPS
    rows = [{"sym": "HOOD", "pnl_usd": -100.0}] * n
    rows += [{"sym": "HOOD", "pnl_usd": 100.0 * n + 500.0}]
    _write_ledger(tmp_path, monkeypatch, rows)
    assert "HOOD" not in app._cooldown_blocked_symbols()


def test_cooldown_ignores_dry_run_rows(tmp_path, monkeypatch):
    """Simulated rows must never trigger a cooldown — real fills only."""
    n = config.SYMBOL_COOLDOWN_MIN_STOPS
    p = tmp_path / "real_trades.jsonl"
    now = dt.datetime.now().isoformat()
    p.write_text("".join(
        json.dumps({"ts": now, "sym": "SIM", "pnl_usd": -500.0, "dry_run": True}) + "\n"
        for _ in range(n + 2)))
    monkeypatch.setattr(app, "_REAL_TRADES_FILE", str(p))
    assert "SIM" not in app._cooldown_blocked_symbols()


def test_cooldown_fails_open_without_ledger(tmp_path, monkeypatch):
    """Missing ledger must never block entries (fail-open)."""
    monkeypatch.setattr(app, "_REAL_TRADES_FILE", str(tmp_path / "nope.jsonl"))
    assert app._cooldown_blocked_symbols() == set()


def test_classify_exit_reason_bands():
    """Realized % maps to truthful labels against the stock stop/target bands."""
    assert app._classify_exit_reason(-5.0, False).startswith("stop")
    assert app._classify_exit_reason(7.0, False).startswith("target")
    assert app._classify_exit_reason(1.0, False).startswith("gain")
    assert app._classify_exit_reason(-1.0, False).startswith("loss")
    assert app._classify_exit_reason(-5.0, True).startswith("partial stop")


# ── Real closed-trade ledger — single source of truth (2026-06-16) ───────────
def _ledger_rows(tmp_path):
    p = tmp_path / "real_trades.jsonl"
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def _arm_ledger(tmp_path, monkeypatch, positions):
    """Point the real-ledger writer at temp files and feed it a position snapshot.
    TRADING_CLIENT is forced None so the exit-fill lookup deterministically falls
    back to the last observed mark."""
    monkeypatch.setattr(app, "_REAL_TRADES_FILE", str(tmp_path / "real_trades.jsonl"))
    monkeypatch.setattr(app, "_REAL_POS_SNAP_FILE", str(tmp_path / "real_pos_snapshot.json"))
    monkeypatch.setattr(app, "_real_pos_prev", {})
    monkeypatch.setattr(app, "_real_pos_seeded", False)
    monkeypatch.setattr(app.trader, "TRADING_CLIENT", None, raising=False)
    state = {"positions": list(positions)}
    monkeypatch.setattr(app, "_account_equity_positions", lambda: state["positions"])
    return state


def _pos(sym, qty, entry=100.0, last=102.0, pnl_usd=20.0, pnl_pct=2.0):
    return {"sym": sym, "qty": qty, "entry": entry, "last": last,
            "pnl_usd": pnl_usd, "pnl_pct": pnl_pct}


def test_real_ledger_records_one_row_on_close(tmp_path, monkeypatch):
    """A position that leaves the account writes exactly one real fill row, with
    P&L computed from entry→exit and a classified reason."""
    s = _arm_ledger(tmp_path, monkeypatch, [_pos("AAPL", 10, entry=100.0, last=102.0)])
    app._detect_real_stock_closes()          # seed tick — no closes emitted
    assert _ledger_rows(tmp_path) == []
    s["positions"] = []                       # AAPL gone → real close
    app._detect_real_stock_closes()
    rows = _ledger_rows(tmp_path)
    assert len(rows) == 1
    assert rows[0]["sym"] == "AAPL" and rows[0]["qty"] == 10
    assert rows[0]["dry_run"] is False
    assert rows[0]["pnl_usd"] == 20.0         # (102 - 100) * 10
    assert rows[0]["reason"].startswith("gain")


def test_real_ledger_no_churn_while_position_open(tmp_path, monkeypatch):
    """Re-ticking with the position still held must NOT fabricate a close (anti-churn)."""
    s = _arm_ledger(tmp_path, monkeypatch, [_pos("MSFT", 5)])
    for _ in range(5):
        app._detect_real_stock_closes()       # position never leaves the account
    assert _ledger_rows(tmp_path) == []


def test_real_ledger_partial_close(tmp_path, monkeypatch):
    """A qty reduction records a partial close pro-rated by the closed fraction."""
    s = _arm_ledger(tmp_path, monkeypatch, [_pos("NVDA", 10, entry=100.0, last=102.0)])
    app._detect_real_stock_closes()           # seed
    s["positions"] = [_pos("NVDA", 4, entry=100.0, last=102.0)]   # closed 6 of 10
    app._detect_real_stock_closes()
    rows = _ledger_rows(tmp_path)
    assert len(rows) == 1 and rows[0]["qty"] == 6
    assert rows[0]["reason"].startswith("partial")


def test_real_ledger_idempotent_on_restart_reemit(tmp_path, monkeypatch):
    """Regression for the 2026-06-18 double-log: a watchdog kill before the snapshot
    save left the snapshot showing a closed position, so the next boot re-diffed and
    re-emitted it. The ledger must refuse the duplicate, never double-counting P&L."""
    monkeypatch.setattr(app, "_real_trade_keys", None)   # force re-seed from temp file
    s = _arm_ledger(tmp_path, monkeypatch, [_pos("AAPL", 10, entry=100.0, last=95.0)])
    app._detect_real_stock_closes()           # seed
    s["positions"] = []                        # AAPL leaves the account → one close
    app._detect_real_stock_closes()
    assert len(_ledger_rows(tmp_path)) == 1
    # Simulate the crash/restart: snapshot reverts to AAPL-still-open, account empty.
    monkeypatch.setattr(app, "_real_pos_prev", {"AAPL": _pos("AAPL", 10, entry=100.0, last=95.0)})
    monkeypatch.setattr(app, "_real_pos_seeded", True)
    app._detect_real_stock_closes()           # would re-emit the same close
    rows = _ledger_rows(tmp_path)
    assert len(rows) == 1                       # duplicate suppressed, not double-counted
    assert rows[0]["sym"] == "AAPL"


def test_sector_cap_blocks_fourth_correlated_name(tmp_path, monkeypatch):
    """With MAX_POSITIONS_PER_SECTOR semis already held, a 4th semi is blocked even
    though the portfolio-count cap has room (correlation, not count)."""
    _arm(monkeypatch)
    monkeypatch.setattr(app, "MAX_POSITIONS_PER_SECTOR", 3)
    monkeypatch.setattr(app, "_portfolio_position_count", lambda: 3)   # room on the count cap
    monkeypatch.setattr(app, "_free_cash", lambda: 1_000_000.0)
    monkeypatch.setattr(app, "_account_equity_positions",
                        lambda: [{"sym": s} for s in ("NVDA", "AMD", "MU")])  # 3 semis
    monkeypatch.setattr(app, "_cooldown_blocked_symbols", lambda: set())
    logs = []
    monkeypatch.setattr(app, "_emit_log", lambda m, **k: logs.append(m))
    import shares_executor
    bought = []
    monkeypatch.setattr(shares_executor, "buy",
                        lambda *a, **k: bought.append(a) or {"success": True})
    app._auto_exec_stocks({"dt": [{"sym": "AMAT", "action": "✅ BUY", "price": 100,
                                   "sector": "Semi Equip"}]})
    assert bought == []
    assert any("sector cap" in m for m in logs)


def test_price_cap_blocks_expensive_name(tmp_path, monkeypatch):
    """A fresh entry priced above MAX_STOCK_ENTRY_PRICE is skipped (gap-risk)."""
    _arm(monkeypatch)
    monkeypatch.setattr(app, "MAX_STOCK_ENTRY_PRICE", 300.0)
    monkeypatch.setattr(app, "_portfolio_position_count", lambda: 0)
    monkeypatch.setattr(app, "_free_cash", lambda: 1_000_000.0)
    monkeypatch.setattr(app, "_account_equity_positions", lambda: [])
    monkeypatch.setattr(app, "_cooldown_blocked_symbols", lambda: set())
    logs = []
    monkeypatch.setattr(app, "_emit_log", lambda m, **k: logs.append(m))
    import shares_executor
    bought = []
    monkeypatch.setattr(shares_executor, "buy",
                        lambda *a, **k: bought.append(a) or {"success": True})
    app._auto_exec_stocks({"dt": [{"sym": "MU", "action": "✅ BUY", "price": 500}]})
    assert bought == []
    assert any("gap-risk cap" in m for m in logs)


def test_risk_guards_live_retune_and_clamp(monkeypatch):
    """The UI handler mutates the same module globals _auto_exec_stocks reads,
    and clamps out-of-range values so a guard can never be fully disabled."""
    monkeypatch.setattr(app, "MAX_POSITIONS_PER_SECTOR", 3)
    monkeypatch.setattr(app, "MAX_STOCK_ENTRY_PRICE", 300.0)
    monkeypatch.setattr(app, "ENTRY_WINDOW_END_MIN", 90)
    monkeypatch.setattr(app, "SYMBOL_COOLDOWN_MIN_STOPS", 2)
    app._apply_risk_guards({"max_per_sector": 2, "max_entry_price": 250,
                            "entry_window_min": 120, "cooldown_stops": 3})
    assert app.MAX_POSITIONS_PER_SECTOR == 2
    assert app.MAX_STOCK_ENTRY_PRICE == 250.0
    assert app.ENTRY_WINDOW_END_MIN == 120
    assert app.SYMBOL_COOLDOWN_MIN_STOPS == 3
    # Out-of-range values clamp to safe minimums (guard stays active)
    app._apply_risk_guards({"max_per_sector": 0, "entry_window_min": 1})
    assert app.MAX_POSITIONS_PER_SECTOR == 1
    assert app.ENTRY_WINDOW_END_MIN == 5


def test_analyze_trades_skips_dry_run_rows(tmp_path, monkeypatch):
    """analyze_trades must ignore any dry_run row so shadow P&L is never reported."""
    import analyze_trades
    led = tmp_path / "real_trades.jsonl"
    led.write_text(
        json.dumps({"ts": "2026-06-16T10:00:00", "sym": "X", "kind": "stock",
                    "pnl_usd": 999.0, "dry_run": True}) + "\n" +
        json.dumps({"ts": "2026-06-16T11:00:00", "sym": "Y", "kind": "stock",
                    "pnl_usd": 10.0, "dry_run": False}) + "\n")
    monkeypatch.setattr(analyze_trades, "LEDGER", led)
    rows = analyze_trades._load(None, None)
    assert [r["sym"] for r in rows] == ["Y"]   # dry_run row dropped


# ── Per-strategy validated exits — live-vs-backtest gap fix (2026-06-18) ──────
def _stk_pos(strategy, entry=100.0, qty=10, atr=5.0, stop=90.0, days_ago=0):
    from datetime import date, timedelta
    return {"sym": "TEST", "strategy": strategy, "route": "stocks", "qty": qty,
            "entry_price": entry, "atr": atr,
            "entry_date": (date.today() - timedelta(days=days_ago)).isoformat(),
            "exit_state": {"entry": entry, "hwm": entry, "stop": stop, "tier": 0},
            "dry_run": True}


def _run_manage_exits(monkeypatch, position, price, rsi2_atr=None, close_ok=True):
    import auto_engine
    import shares_executor
    saved = {"still_open": []}
    journaled = []
    closes = []
    monkeypatch.setattr(auto_engine, "_load_positions", lambda: [dict(position)])
    monkeypatch.setattr(auto_engine, "_save_positions",
                        lambda ps: saved.__setitem__("still_open", ps))
    monkeypatch.setattr(auto_engine, "_journal_add",
                        lambda *a, **k: journaled.append(a))
    monkeypatch.setattr(auto_engine, "_record_realized", lambda *a, **k: None)
    monkeypatch.setattr(auto_engine, "_log_closed_trade", lambda *a, **k: None)
    monkeypatch.setattr(shares_executor, "current_price", lambda s: price)
    monkeypatch.setattr(shares_executor, "close",
                        lambda s, dry_run=False: closes.append(s) or {"success": close_ok})
    if rsi2_atr is not None:
        monkeypatch.setattr(auto_engine, "_daily_rsi2_atr", lambda s: rsi2_atr)
    auto_engine.manage_exits(dry_run=True)
    reason = journaled[0][2] if journaled else None
    return {"closed": bool(closes), "reason": reason, "still_open": saved["still_open"]}


def test_mean_rev_exits_on_rsi_target(monkeypatch):
    """Connors position banks the bounce when daily RSI(2) >= 70 (validated exit)."""
    r = _run_manage_exits(monkeypatch, _stk_pos("connors_rsi2"),
                          price=101.0, rsi2_atr=(75.0, 5.0))   # only +1%, but RSI hot
    assert r["closed"] and "mean-rev target" in r["reason"]


def test_mean_rev_does_not_fixed_stop_at_minus3(monkeypatch):
    """At -3% with RSI low and inside the 2xATR stop, a mean-rev position is HELD —
    proving the premature fixed -3% stop (the gap's cause) no longer applies."""
    r = _run_manage_exits(monkeypatch, _stk_pos("connors_rsi2", atr=5.0),
                          price=97.0, rsi2_atr=(30.0, 5.0))    # -3%, but 2xATR=10 not hit
    assert not r["closed"] and len(r["still_open"]) == 1


def test_mean_rev_exits_on_2atr_stop(monkeypatch):
    """Mean-rev position stops out at the validated 2xATR distance."""
    r = _run_manage_exits(monkeypatch, _stk_pos("connors_rsi2", atr=5.0),
                          price=89.0, rsi2_atr=(30.0, 5.0))    # entry-px=11 >= 2x5
    assert r["closed"] and "ATR stop" in r["reason"]


def test_trend_lets_winner_run_no_fixed_target(monkeypatch):
    """A trend position at +7% is NOT force-closed by a fixed +6% target — the
    trailing ladder lets high-payoff winners run."""
    r = _run_manage_exits(monkeypatch, _stk_pos("trend_pullback", stop=92.0),
                          price=107.0)
    assert not r["closed"] and len(r["still_open"]) == 1


def test_unknown_strategy_uses_fixed_fallback(monkeypatch):
    """An untagged/manual position keeps the safe legacy +6% fixed-band exit."""
    r = _run_manage_exits(monkeypatch, _stk_pos("screener/manual"), price=106.5)
    assert r["closed"] and "take-profit" in r["reason"]


def test_strategy_hint_propagates_to_position(monkeypatch):
    """_protect_untracked_stocks tags a new position with its REAL screener strategy."""
    recorded = []
    monkeypatch.setattr(app, "_account_equity_positions",
                        lambda: [{"sym": "AAPL", "qty": 10, "entry": 100.0}])
    monkeypatch.setattr(app.auto_engine, "_load_positions", lambda: [])
    monkeypatch.setattr(app.auto_engine, "record_stock_position",
                        lambda *a, **k: recorded.append((a, k)))
    monkeypatch.setitem(app._strategy_hint, "AAPL", "Connors RSI(2)")
    monkeypatch.setitem(app._atr_hint, "AAPL", 4.2)
    app._protect_untracked_stocks()
    assert recorded and recorded[0][1]["strategy"] == "Connors RSI(2)"
    assert recorded[0][1]["atr"] == 4.2


def test_option_lane_kill_switch_blocks_entries(monkeypatch):
    """Edge review 2026-06-12: when AUTO_EXEC_OPTIONS_ENABLED is False the option
    lane must place nothing, even fully armed with a wide-open portfolio."""
    _arm(monkeypatch)
    monkeypatch.setattr(app, "AUTO_EXEC_OPTIONS_ENABLED", False)   # the kill-switch
    monkeypatch.setattr(app, "_portfolio_position_count", lambda: 0)
    monkeypatch.setattr(app, "_free_cash", lambda: 1_000_000.0)
    monkeypatch.setattr(app.trader, "TRADING_CLIENT", None, raising=False)
    import screener_executor as _se
    placed = []
    monkeypatch.setattr(_se, "execute_screener_option",
                        lambda *a, **k: placed.append(a) or {"success": True})
    app._auto_exec_options({"options": [{"sym": "QQQ", "action": "✅ BUY"}]})
    assert placed == []   # paused → nothing opened


def test_stocks_lane_blocked_when_portfolio_full(monkeypatch):
    _arm(monkeypatch)
    monkeypatch.setattr(app, "_portfolio_position_count",
                        lambda: config.MAX_PORTFOLIO_POSITIONS)   # exactly full
    monkeypatch.setattr(app, "_free_cash", lambda: 1_000_000.0)   # cash is NOT the limiter
    monkeypatch.setattr(app, "_account_equity_positions", lambda: [])
    logs = []
    monkeypatch.setattr(app, "_emit_log", lambda m, **k: logs.append(m))
    import shares_executor
    bought = []
    monkeypatch.setattr(shares_executor, "buy",
                        lambda *a, **k: bought.append(a) or {"success": True})
    data = {"dt": [{"sym": "NVDA", "action": "✅ BUY", "price": 100}]}
    app._auto_exec_stocks(data)
    assert bought == []                                           # nothing opened
    assert any("portfolio full" in m for m in logs)


def test_options_lane_blocked_when_portfolio_full(monkeypatch):
    _arm(monkeypatch)
    monkeypatch.setattr(app, "_portfolio_position_count",
                        lambda: config.MAX_PORTFOLIO_POSITIONS + 3)   # over the cap
    monkeypatch.setattr(app, "_free_cash", lambda: 1_000_000.0)
    monkeypatch.setattr(app.trader, "TRADING_CLIENT", None, raising=False)
    logs = []
    monkeypatch.setattr(app, "_emit_log", lambda m, **k: logs.append(m))
    import screener_executor as _se
    placed = []
    monkeypatch.setattr(_se, "execute_screener_option",
                        lambda *a, **k: placed.append(a) or {"success": True})
    data = {"options": [{"sym": "QQQ", "action": "✅ BUY"}]}
    app._auto_exec_options(data)
    assert placed == []                                          # nothing opened
    assert any("portfolio full" in m for m in logs)
