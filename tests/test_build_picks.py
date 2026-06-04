"""Tests for app._build_picks — the merged, KB-ranked pick list that becomes the
single source of truth for the display and both auto-exec lanes."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import app


def _data():
    return {
        "dt": [
            {"sym": "AAPL", "price": 200, "atr": 4, "kb_match": 80, "valid": True,
             "is_top": True, "action": "✅ BUY", "setup": "Breakout", "bt_dir": 51.5, "bt_pf": 1.88},
            {"sym": "NVDA", "price": 120, "atr": 3, "kb_match": 70, "valid": True,
             "is_top": False, "setup": "Gap+Vol", "bt_dir": 50.6},
        ],
        "options": [
            {"sym": "NVDA", "direction": "bull", "ivr": "IVR 22", "kb_match": 85,
             "action": "✅ BUY", "source": "Connors RSI(2) Daily", "dir_pct": 66.4,
             "pf": 1.32, "expiry": "2099-01-15", "structure": "ATM Call"},
            {"sym": "XLF", "direction": "bull", "ivr": "IVR 22", "spot": 50, "kb_match": 59,
             "action": "⚠ Illiquid", "liquidity": {"ok": False}, "source": "intraday", "dir_pct": 50.6},
        ],
    }


def test_symbol_in_both_lists_collapses_to_one_pick(monkeypatch):
    monkeypatch.setattr(app.trader, "account_value", lambda: 107_846.0, raising=False)
    picks = app._build_picks(_data(), [], vix=18)
    syms = [p["sym"] for p in picks]
    assert len(picks) == 3 and syms.count("NVDA") == 1   # NVDA was in dt AND options


def test_canonical_kb_match_is_routed_instrument(monkeypatch):
    monkeypatch.setattr(app.trader, "account_value", lambda: 107_846.0, raising=False)
    by = {p["sym"]: p for p in app._build_picks(_data(), [], vix=18)}
    # NVDA has an option (low IVR) → routes options → kb_match == option score (85)
    assert by["NVDA"]["route"] == "options" and by["NVDA"]["kb_match"] == 85
    # AAPL has no option → routes shares → kb_match == stock score (80)
    assert by["AAPL"]["route"] == "stocks" and by["AAPL"]["kb_match"] == 80


def test_illiquid_pick_is_not_a_buy_and_ranks_last(monkeypatch):
    monkeypatch.setattr(app.trader, "account_value", lambda: 107_846.0, raising=False)
    picks = app._build_picks(_data(), [], vix=18)
    by = {p["sym"]: p for p in picks}
    assert by["XLF"]["kb_match"] == 59 and by["XLF"]["action"] != "✅ BUY"
    # BUY rows (by kb_match desc) first, non-BUY last
    assert picks[0]["sym"] == "NVDA" and picks[-1]["sym"] == "XLF"


def test_no_equity_degrades_to_display_only(monkeypatch):
    monkeypatch.setattr(app.trader, "account_value", lambda: 0.0, raising=False)
    picks = app._build_picks(_data(), [], vix=18)
    # no risk brain → every pick routes "skip" (display only, no auto-exec)
    assert all(p["route"] == "skip" for p in picks)
