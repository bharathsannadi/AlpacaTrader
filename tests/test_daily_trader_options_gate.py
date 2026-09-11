"""Tests for the options gates on the daily_trader lane.

daily_trader builds its own contracts and never calls router.route_signal, so
neither the SPY/QQQ whitelist nor the KB §22 variance-risk-premium gate reached
it — it was observed placing an NVDA call on the 2026-09-11 restart, after both
were live everywhere else. These pin the gates on this second lane.

No network: the whitelist rejection happens before any yfinance call, and the
§22 rejection is driven through a stubbed option chain.
"""
import numpy as np
import pandas as pd
import pytest

import config
import daily_trader


class TestWhitelistOnDailyTrader:
    def test_non_whitelisted_symbol_is_skipped_before_any_network(self, monkeypatch):
        def _boom(*a, **k):
            raise AssertionError("must reject before touching yfinance")
        monkeypatch.setattr(daily_trader, "yf", _boom, raising=False)
        import sys
        monkeypatch.setitem(sys.modules, "yfinance", _boom)
        assert daily_trader._get_option_context("NVDA", 120.0, 0.30) is None

    def test_empty_whitelist_does_not_block(self, monkeypatch):
        monkeypatch.setattr(config, "OPTIONS_UNDERLYINGS", ())
        # falls through the whitelist and fails later on the (absent) chain
        monkeypatch.setattr(config, "VOL_EDGE_REQUIRED_FOR_LONG_PREMIUM", False)
        assert daily_trader._get_option_context("NVDA", 120.0, 0.30) is None


class TestVrpGateOnDailyTrader:
    """Drive the §22 gate through a stubbed chain so no network is needed."""

    @pytest.fixture
    def chain(self, monkeypatch):
        from datetime import date, timedelta
        exp = (date.today() + timedelta(days=25)).isoformat()

        def _mk(iv):
            calls = pd.DataFrame({
                "strike": [95.0, 100.0, 105.0],
                "bid": [6.0, 3.0, 1.0], "ask": [6.2, 3.2, 1.1],
                "impliedVolatility": [iv, iv, iv],
                "openInterest": [5000, 5000, 5000],
                "contractSymbol": ["SPY_A", "SPY_B", "SPY_C"],
            })
            return calls, exp

        class FakeTicker:
            iv = 0.14

            def __init__(self, sym):
                self.options = [exp]

            def option_chain(self, e):
                calls, _ = _mk(FakeTicker.iv)
                return type("C", (), {"calls": calls, "puts": calls})()

        import sys
        monkeypatch.setitem(sys.modules, "yfinance",
                            type("M", (), {"Ticker": FakeTicker}))
        return FakeTicker

    def test_rich_premium_is_refused(self, chain, monkeypatch):
        monkeypatch.setattr(config, "VOL_EDGE_REQUIRED_FOR_LONG_PREMIUM", True)
        chain.iv = 0.14                     # IV30 14% vs forecast ~10% → refuse
        out = daily_trader._get_option_context("SPY", 100.0, 0.09, hv5=0.08)
        assert out is None

    def test_missing_vol_inputs_are_refused(self, chain, monkeypatch):
        monkeypatch.setattr(config, "VOL_EDGE_REQUIRED_FOR_LONG_PREMIUM", True)
        out = daily_trader._get_option_context("SPY", 100.0, float("nan"),
                                               hv5=float("nan"))
        assert out is None, "unknown must never read as cheap"

    def test_gate_off_restores_previous_behaviour(self, chain, monkeypatch):
        """With the gate off the rich-premium case is no longer rejected for vol
        reasons — proving the refusals above come from §22 and not the fixture."""
        monkeypatch.setattr(config, "VOL_EDGE_REQUIRED_FOR_LONG_PREMIUM", False)
        chain.iv = 0.14
        out = daily_trader._get_option_context("SPY", 100.0, 0.09, hv5=0.08)
        assert out is not None and out.get("long_occ")


class TestHv5:
    def test_annualises_from_log_returns(self):
        df = pd.DataFrame({"close": [100 * (1.01 ** i) for i in range(30)]})
        hv = daily_trader._get_hv5(df)
        assert hv == pytest.approx(0.0, abs=1e-6)   # constant growth → no vol

    def test_volatile_series_scores_higher(self):
        calm = pd.DataFrame({"close": [100 + 0.1 * (-1) ** i for i in range(30)]})
        wild = pd.DataFrame({"close": [100 + 5.0 * (-1) ** i for i in range(30)]})
        assert daily_trader._get_hv5(wild) > daily_trader._get_hv5(calm)

    def test_short_series_is_nan(self):
        assert np.isnan(daily_trader._get_hv5(pd.DataFrame({"close": [100, 101]})))
