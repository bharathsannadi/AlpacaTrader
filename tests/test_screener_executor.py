"""Tests for screener_executor pure logic.

We do NOT call Alpaca here. The dry-run path covers the contract-selection +
risk-gate logic without placing real orders. _normalize_alpaca_status and
_verify_fill (with a fake client) cover the fill verification added in #6.
"""
import pytest
from unittest.mock import MagicMock

from screener_executor import (
    _normalize_alpaca_status,
    _verify_fill,
    OPT_MIN_OI, OPT_MAX_BID_ASK_PCT, RISK_BUDGET,
    OPT_SPREAD_RATIO_LO, OPT_SPREAD_RATIO_HI,
)


# ── _normalize_alpaca_status ──────────────────────────────────────────────────

class TestNormalizeAlpacaStatus:
    @pytest.mark.parametrize("raw,expected", [
        ("filled", "filled"),
        ("FILLED", "filled"),
        ("OrderStatus.FILLED", "filled"),
        ("done_for_day", "filled"),
        ("partially_filled", "partial"),
        ("canceled", "rejected"),
        ("cancelled", "rejected"),
        ("rejected", "rejected"),
        ("expired", "rejected"),
        ("suspended", "rejected"),
        ("new", "pending"),
        ("accepted", "pending"),
        ("pending_new", "pending"),
        ("accepted_for_bidding", "pending"),
        ("", "pending"),
        (None, "pending"),
        ("unknown_future_status", "pending"),
    ])
    def test_status_categories(self, raw, expected):
        assert _normalize_alpaca_status(raw) == expected


# ── _verify_fill ──────────────────────────────────────────────────────────────

def _fake_order(status: str, filled_qty: int = 0, filled_avg_price=None):
    """Build a MagicMock that quacks like an Alpaca Order."""
    o = MagicMock()
    o.status = status
    o.filled_qty = filled_qty
    o.filled_avg_price = filled_avg_price
    return o


class TestVerifyFill:
    def test_returns_filled_immediately(self):
        tc = MagicMock()
        tc.get_order_by_id.return_value = _fake_order("filled", 1, "2.34")
        result = _verify_fill(tc, "abc123", timeout_sec=5, poll_interval=0.1)
        assert result["status"]            == "filled"
        assert result["filled_qty"]        == 1
        assert result["filled_avg_price"]  == 2.34
        # Only polled once because terminal state was hit immediately
        assert tc.get_order_by_id.call_count == 1

    def test_returns_rejected_on_rejected(self):
        tc = MagicMock()
        tc.get_order_by_id.return_value = _fake_order("rejected", 0, None)
        result = _verify_fill(tc, "abc123", timeout_sec=5, poll_interval=0.1)
        assert result["status"]     == "rejected"
        assert result["filled_qty"] == 0

    def test_returns_pending_on_timeout(self):
        tc = MagicMock()
        tc.get_order_by_id.return_value = _fake_order("new", 0, None)
        result = _verify_fill(tc, "abc123", timeout_sec=0.3, poll_interval=0.1)
        # Non-terminal status — we should give up and return pending
        assert result["status"] == "pending"
        # Polled multiple times before giving up
        assert tc.get_order_by_id.call_count >= 2

    def test_transitions_pending_then_filled(self):
        """Order sits in 'new' for one poll, then fills."""
        tc = MagicMock()
        tc.get_order_by_id.side_effect = [
            _fake_order("new", 0, None),
            _fake_order("filled", 1, "2.50"),
        ]
        result = _verify_fill(tc, "abc123", timeout_sec=5, poll_interval=0.05)
        assert result["status"]           == "filled"
        assert result["filled_avg_price"] == 2.50

    def test_handles_api_errors_gracefully(self):
        """If get_order_by_id raises, we should keep polling, not crash."""
        tc = MagicMock()
        tc.get_order_by_id.side_effect = [
            Exception("transient API error"),
            _fake_order("filled", 1, "1.00"),
        ]
        result = _verify_fill(tc, "abc123", timeout_sec=5, poll_interval=0.05)
        assert result["status"] == "filled"

    def test_invalid_filled_qty_defaults_to_zero(self):
        """Some Alpaca responses come back with string/None values."""
        tc = MagicMock()
        bad = _fake_order("filled", "not_a_number", "garbage")
        tc.get_order_by_id.return_value = bad
        result = _verify_fill(tc, "abc123", timeout_sec=5, poll_interval=0.05)
        assert result["filled_qty"] == 0
        assert result["filled_avg_price"] is None


# ── Risk-budget constants ─────────────────────────────────────────────────────

class TestRiskConstants:
    """Guard rail: someone bumping RISK_BUDGET from $400 to $4000 should
    have to update this test deliberately."""
    def test_risk_budget_is_400_dollars(self):
        assert RISK_BUDGET == 400.0

    def test_min_oi_gate_is_200(self):
        assert OPT_MIN_OI == 200

    def test_max_bid_ask_is_5_percent(self):
        assert OPT_MAX_BID_ASK_PCT == 0.05

    def test_spread_debit_ratio_range(self):
        assert OPT_SPREAD_RATIO_LO == 0.25
        assert OPT_SPREAD_RATIO_HI == 0.45
