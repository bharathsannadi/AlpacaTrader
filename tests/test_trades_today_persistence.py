"""Tests for trades_today persistence (#17).

Same pattern as test_auto_exec_persistence.py. The goal is restart-safety:
if the server bounces mid-day, the UI and the 15:35 ET EOD review should
still see every close that happened earlier in the session.
"""
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest


@pytest.fixture
def app_module(tmp_path, monkeypatch):
    """Fresh import of app with persistence files pointed at tmp_path."""
    sys.modules.pop("app", None)
    monkeypatch.setenv("PYTEST_RUNNING", "1")
    import app as _app
    monkeypatch.setattr(_app, "_TRADES_TODAY_FILE",
                        str(tmp_path / "trades_today.json"))
    monkeypatch.setattr(_app, "_AUTO_EXEC_STATE_FILE",
                        str(tmp_path / "auto_exec_state.json"))
    with _app._state_lock:
        _app.state["trades_today"] = []
    return _app


def _sample_trade(symbol="NVDA", pnl=2.5):
    return {
        "symbol":       symbol,
        "direction":    "CALL",
        "pnl_pct":      pnl,
        "reason":       "T1 partial close",
        "time":         "13:45",
        "is_partial":   False,
        "signal_class": "breakout",
    }


def test_save_then_load_roundtrip(app_module):
    with app_module._state_lock:
        app_module.state["trades_today"] = [
            _sample_trade("NVDA", 2.5),
            _sample_trade("AAPL", -1.2),
        ]
    app_module._save_trades_today()

    # Wipe and reload
    with app_module._state_lock:
        app_module.state["trades_today"] = []
    app_module._load_trades_today()

    with app_module._state_lock:
        loaded = list(app_module.state["trades_today"])
    assert len(loaded) == 2
    assert loaded[0]["symbol"] == "NVDA"
    assert loaded[1]["pnl_pct"] == -1.2


def test_load_discards_stale_file(app_module):
    """Yesterday's trades should NOT show up in today's UI."""
    state_file = Path(app_module._TRADES_TODAY_FILE)
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps({
        "date":   "2020-01-01",
        "trades": [_sample_trade("GOOG"), _sample_trade("META")],
    }))

    with app_module._state_lock:
        app_module.state["trades_today"] = []
    app_module._load_trades_today()

    with app_module._state_lock:
        loaded = list(app_module.state["trades_today"])
    assert loaded == []


def test_load_missing_file_is_noop(app_module):
    with app_module._state_lock:
        app_module.state["trades_today"] = []
    app_module._load_trades_today()   # no file
    with app_module._state_lock:
        assert list(app_module.state["trades_today"]) == []


def test_load_corrupt_file_is_noop(app_module):
    state_file = Path(app_module._TRADES_TODAY_FILE)
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text("[not valid json")

    with app_module._state_lock:
        app_module.state["trades_today"] = []
    app_module._load_trades_today()   # should not raise
    with app_module._state_lock:
        assert list(app_module.state["trades_today"]) == []


def test_save_is_atomic(app_module):
    with app_module._state_lock:
        app_module.state["trades_today"] = [_sample_trade()]
    app_module._save_trades_today()

    state_file = Path(app_module._TRADES_TODAY_FILE)
    tmp_file   = Path(str(state_file) + ".tmp")
    assert state_file.exists()
    assert not tmp_file.exists()


def test_save_creates_parent_dir(app_module, tmp_path, monkeypatch):
    nested = tmp_path / "fresh" / "data" / "trades_today.json"
    monkeypatch.setattr(app_module, "_TRADES_TODAY_FILE", str(nested))

    with app_module._state_lock:
        app_module.state["trades_today"] = [_sample_trade()]
    app_module._save_trades_today()
    assert nested.exists()


def test_save_handles_non_json_serialisable(app_module):
    """default=str lets us serialise datetime/Decimal etc. without crashing."""
    from datetime import datetime
    weird_trade = {
        "symbol":  "NVDA",
        "pnl_pct": 1.5,
        "opened":  datetime.now(),   # not JSON serialisable by default
    }
    with app_module._state_lock:
        app_module.state["trades_today"] = [weird_trade]
    # Must not raise
    app_module._save_trades_today()
    assert Path(app_module._TRADES_TODAY_FILE).exists()


def test_save_empty_list_is_safe(app_module):
    """A day with zero closes should still produce a valid file (no errors)."""
    with app_module._state_lock:
        app_module.state["trades_today"] = []
    app_module._save_trades_today()
    data = json.loads(Path(app_module._TRADES_TODAY_FILE).read_text())
    assert data["trades"] == []
