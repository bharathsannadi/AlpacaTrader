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
    """Arm both lanes: logged-in, market open, not dry — so only the caps gate."""
    monkeypatch.setitem(app.state, "auto_execute_options", True)
    monkeypatch.setitem(app.state, "logged_in", True)
    monkeypatch.setitem(app.state, "dry_run", False)
    monkeypatch.setattr(app.screener, "_is_market_open", lambda: True)


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
