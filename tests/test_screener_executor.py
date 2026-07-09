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


# ── _marketable_limit ─────────────────────────────────────────────────────────

from screener_executor import _marketable_limit, _make_clients, _is_paper


class TestMarketableLimit:
    def test_buy_crosses_quarter_half_spread(self):
        q = {"bid": 4.90, "ask": 5.10, "mid": 5.00, "source": "alpaca"}
        # half-spread 0.10 → step 0.025 → min step floor keeps ≥ 0.01
        assert _marketable_limit(q, 0.0, "buy") == round(min(5.00 + 0.025, 5.10), 2)

    def test_buy_capped_at_ask(self):
        q = {"bid": 5.00, "ask": 5.01, "mid": 5.005, "source": "alpaca"}
        assert _marketable_limit(q, 0.0, "buy") <= 5.01

    def test_sell_floored_at_bid(self):
        q = {"bid": 3.00, "ask": 3.40, "mid": 3.20, "source": "alpaca"}
        lim = _marketable_limit(q, 0.0, "sell")
        assert 3.00 <= lim <= 3.20

    def test_fallback_without_quote_buy(self):
        assert _marketable_limit(None, 2.00, "buy") == 2.05

    def test_fallback_without_quote_sell(self):
        assert _marketable_limit(None, 2.00, "sell") == 1.95


# ── Shared-client resolution (executor must trade the app's account) ──────────

class TestSharedClientResolution:
    def _fake_trader(self, tc, oc, paper):
        m = MagicMock()
        m.TRADING_CLIENT = tc
        m.OPTION_CLIENT = oc
        m.PAPER_MODE = paper
        return m

    def test_prefers_app_authenticated_clients(self, monkeypatch):
        import sys
        tc, oc = MagicMock(), MagicMock()
        monkeypatch.setitem(sys.modules, "spy_auto_trader",
                            self._fake_trader(tc, oc, paper=True))
        got_tc, got_oc, got_paper = _make_clients()
        assert got_tc is tc and got_oc is oc and got_paper is True

    def test_is_paper_follows_live_client_mode(self, monkeypatch):
        import sys
        monkeypatch.setitem(sys.modules, "spy_auto_trader",
                            self._fake_trader(MagicMock(), MagicMock(), paper=False))
        assert _is_paper() is False   # live client → strict, no relaxations

    def test_is_paper_ignores_disconnected_trader(self, monkeypatch):
        import sys
        stub = self._fake_trader(None, None, paper=True)
        stub.TRADING_CLIENT = None
        monkeypatch.setitem(sys.modules, "spy_auto_trader", stub)
        import screener_executor as se
        monkeypatch.setattr(se, "_PAPER_CACHE", False)
        assert _is_paper() is False   # falls back to cached .env resolution


# ── MLEG spread execution ─────────────────────────────────────────────────────

import pandas as pd
import screener_executor as se


def _fake_yf_module(spot=100.0):
    """A yfinance stand-in whose chain yields a valid KB §5/§9 debit spread:
    ATM 100C mid 5.10, short 105C bid 3.00 → net 2.10 / width 5 = 42% ratio."""
    calls = pd.DataFrame([
        {"contractSymbol": "TST260814C00100000", "strike": 100.0,
         "bid": 5.00, "ask": 5.20, "openInterest": 500},
        {"contractSymbol": "TST260814C00105000", "strike": 105.0,
         "bid": 3.00, "ask": 3.20, "openInterest": 500},
        {"contractSymbol": "TST260814C00110000", "strike": 110.0,
         "bid": 1.80, "ask": 2.00, "openInterest": 500},
    ])
    chain = MagicMock()
    chain.calls = calls
    chain.puts = calls
    ticker = MagicMock()
    ticker.history.return_value = pd.DataFrame({"Close": [spot]})
    ticker.option_chain.return_value = chain
    ticker.options = ("2026-08-14",)
    yf = MagicMock()
    yf.Ticker.return_value = ticker
    return yf


def _spread_row():
    return {"sym": "TST", "structure": "Debit Call Spread",
            "expiry": "2026-08-14", "opt_type": "Call", "max_risk": 400}


def _quotes(long_wide=False):
    lq = ({"bid": 4.00, "ask": 6.20, "mid": 5.10, "source": "alpaca"} if long_wide
          else {"bid": 5.00, "ask": 5.20, "mid": 5.10, "source": "alpaca"})
    return {"TST260814C00100000": lq,
            "TST260814C00105000": {"bid": 3.00, "ask": 3.20, "mid": 3.10,
                                   "source": "alpaca"}}


class TestMlegSpreadExecution:
    def _run(self, monkeypatch, fill_status="filled", long_wide=False):
        import sys
        monkeypatch.setitem(sys.modules, "yfinance", _fake_yf_module())
        tc, oc = MagicMock(), MagicMock()
        order = _fake_order(fill_status, 1 if fill_status == "filled" else 0,
                            "2.15" if fill_status == "filled" else None)
        order.id = "mleg-1"
        tc.submit_order.return_value = order
        tc.get_order_by_id.return_value = order
        monkeypatch.setattr(se, "_make_clients", lambda: (tc, oc, True))
        quotes = _quotes(long_wide=long_wide)
        monkeypatch.setattr(se, "_live_option_quote",
                            lambda _oc, occ: quotes.get(occ))
        result = se.execute_screener_option(_spread_row(), dry_run=False)
        return result, tc

    def test_spread_goes_out_as_single_atomic_order(self, monkeypatch):
        result, tc = self._run(monkeypatch)
        assert result["success"] is True
        assert tc.submit_order.call_count == 1          # ONE order, not BTO+STO
        req = tc.submit_order.call_args[0][0]
        assert str(getattr(req, "order_class", "")).lower().endswith("mleg")
        assert len(req.legs) == 2
        assert result["long_order_id"] == result["short_order_id"] == "mleg-1"
        assert result["order_class"] == "mleg"

    def test_rejected_mleg_fails_without_rollback_orders(self, monkeypatch):
        result, tc = self._run(monkeypatch, fill_status="rejected")
        assert result["success"] is False
        # Atomic rejection leaves nothing to flatten: exactly one submit, no
        # cancel, no market-sell rollback.
        assert tc.submit_order.call_count == 1
        assert tc.cancel_order_by_id.call_count == 0

    def test_live_wide_spread_blocks_at_order_time(self, monkeypatch):
        # Chain (stale) passes §9, but the LIVE long-leg quote is wide → abort
        # before ANY order is submitted.
        result, tc = self._run(monkeypatch, long_wide=True)
        assert result["success"] is False
        assert "§9" in (result["error"] or "")
        assert tc.submit_order.call_count == 0

    def test_dry_run_places_no_orders(self, monkeypatch):
        import sys
        monkeypatch.setitem(sys.modules, "yfinance", _fake_yf_module())
        tc = MagicMock()
        monkeypatch.setattr(se, "_make_clients",
                            lambda: (_ for _ in ()).throw(AssertionError("no clients in dry run")))
        result = se.execute_screener_option(_spread_row(), dry_run=True)
        assert result["success"] is True
        assert result["long_order_id"] == "dry_run"
        assert tc.submit_order.call_count == 0
