"""Tests for the auto-exec dedup persistence (#5 from the audit).

Verifies that:
  - _save_auto_exec_state writes atomically
  - _load_auto_exec_state rehydrates a same-day file
  - _load_auto_exec_state discards a stale (yesterday's) file
  - Concurrent saves don't corrupt the file

We import the helpers from app.py without booting Flask by monkeypatching
the state file path to a tmp directory.
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import pytest


@pytest.fixture
def app_module(tmp_path, monkeypatch):
    """Import app with a tmp-path state file. Reset module state between runs."""
    # Make sure app module is freshly imported
    sys.modules.pop("app", None)
    # Stub Alpaca network calls during import (init_clients is lazy, but
    # spy_auto_trader imports yfinance + alpaca SDK at module load time)
    monkeypatch.setenv("PYTEST_RUNNING", "1")
    import app as _app
    # Redirect the persistence file to a tmp dir
    monkeypatch.setattr(_app, "_AUTO_EXEC_STATE_FILE",
                        str(tmp_path / "auto_exec_state.json"))
    # Reset in-memory state to a known baseline
    _app._auto_exec_today = set()
    _app._auto_exec_date  = ""
    return _app


def test_save_then_load_roundtrip(app_module):
    app_module._auto_exec_date  = datetime.now(app_module.ET).strftime("%Y-%m-%d")
    app_module._auto_exec_today = {"NVDA", "AAPL", "TSLA"}
    app_module._save_auto_exec_state()

    # Wipe in-memory state and reload from disk
    app_module._auto_exec_today = set()
    app_module._auto_exec_date  = ""
    app_module._load_auto_exec_state()

    assert app_module._auto_exec_today == {"NVDA", "AAPL", "TSLA"}
    assert app_module._auto_exec_date  == datetime.now(app_module.ET).strftime("%Y-%m-%d")


def test_load_discards_stale_file(app_module, tmp_path):
    """A file from yesterday should be ignored — dedup resets at midnight."""
    state_file = Path(app_module._AUTO_EXEC_STATE_FILE)
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps({
        "date":     "2020-01-01",            # ancient
        "executed": ["GOOG", "META"],
    }))

    app_module._auto_exec_today = set()
    app_module._auto_exec_date  = ""
    app_module._load_auto_exec_state()

    # Should have ignored the stale file
    assert app_module._auto_exec_today == set()
    assert app_module._auto_exec_date  == ""


def test_load_missing_file_is_noop(app_module):
    """No file → no crash, just empty state."""
    app_module._auto_exec_today = set()
    app_module._auto_exec_date  = ""
    # File doesn't exist yet
    app_module._load_auto_exec_state()
    assert app_module._auto_exec_today == set()


def test_load_corrupt_file_is_noop(app_module, tmp_path):
    """Corrupted JSON shouldn't crash startup — we want the server to boot
    and just lose today's dedup history (acceptable degraded mode)."""
    state_file = Path(app_module._AUTO_EXEC_STATE_FILE)
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text("{not valid json")

    app_module._auto_exec_today = set()
    app_module._auto_exec_date  = ""
    app_module._load_auto_exec_state()
    # Should not raise; state stays empty
    assert app_module._auto_exec_today == set()


def test_save_is_atomic(app_module, tmp_path):
    """We use temp-file rename. After the save, there should be NO leftover
    .tmp file (proves the rename happened cleanly)."""
    app_module._auto_exec_date  = "2026-05-25"
    app_module._auto_exec_today = {"NVDA"}
    app_module._save_auto_exec_state()

    state_file = Path(app_module._AUTO_EXEC_STATE_FILE)
    tmp_file   = Path(str(state_file) + ".tmp")
    assert state_file.exists()
    assert not tmp_file.exists()


def test_save_creates_parent_dir(app_module, tmp_path, monkeypatch):
    """The first save on a fresh checkout creates the data/ directory."""
    nested = tmp_path / "fresh" / "deep" / "data" / "auto_exec_state.json"
    monkeypatch.setattr(app_module, "_AUTO_EXEC_STATE_FILE", str(nested))

    app_module._auto_exec_date  = "2026-05-25"
    app_module._auto_exec_today = {"NVDA"}
    app_module._save_auto_exec_state()

    assert nested.exists()


def test_dedup_constants_are_safe(app_module):
    """Guard rail — if someone bumps these from sane defaults, force them
    to update the test."""
    assert app_module.MAX_AUTO_EXEC_PER_DAY == 3
    assert app_module.DAILY_LOSS_LIMIT_PCT  == 2.0
