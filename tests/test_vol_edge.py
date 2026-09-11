"""Tests for vol_edge — the KB §22 variance-risk-premium gate.

Context: KB §2 authorised buying premium at IVR < 30, but screener_engine was
feeding that threshold `round(hv20)` — an annualised REALISED-vol level, not a
percentile. SPY's HV20 sat under 30 on 100% of sessions over the trailing year,
so the router bought naked calls unconditionally and never tested whether
options were actually cheap. These tests pin the replacement test and, above
all, its fail-safe direction: unknown must never read as cheap.
"""
import math

import pytest

import config
import vol_edge
from trade_signal import Signal
from risk_brain import RiskBrain
from router import route_signal


def _rb():
    return RiskBrain(total_equity=107_846)


# ── hv_annualized ─────────────────────────────────────────────────────────────

class TestHvAnnualized:
    def test_flat_series_has_zero_vol(self):
        assert vol_edge.hv_annualized([100.0] * 30, 20) == pytest.approx(0.0)

    def test_known_series_matches_hand_calculation(self):
        # alternating +1%/-1% log moves → stdev of returns ≈ 0.01
        px = [100.0]
        for i in range(25):
            px.append(px[-1] * (math.exp(0.01) if i % 2 == 0 else math.exp(-0.01)))
        hv = vol_edge.hv_annualized(px, 20)
        assert hv == pytest.approx(0.01 * math.sqrt(252) * 100, rel=0.10)

    def test_more_volatile_series_scores_higher(self):
        calm = [100.0 * (1 + 0.001 * (-1) ** i) for i in range(40)]
        wild = [100.0 * (1 + 0.03 * (-1) ** i) for i in range(40)]
        assert vol_edge.hv_annualized(wild, 20) > vol_edge.hv_annualized(calm, 20)

    @pytest.mark.parametrize("series", [None, [], [100.0], [100.0] * 5])
    def test_insufficient_data_returns_none(self, series):
        assert vol_edge.hv_annualized(series, 20) is None

    def test_ignores_nonpositive_prices(self):
        assert vol_edge.hv_annualized([0, -5, None] + [100.0] * 25, 20) is not None


# ── iv_rank ───────────────────────────────────────────────────────────────────

class TestIvRank:
    def test_midpoint_is_fifty(self):
        assert vol_edge.iv_rank(15.0, [10.0, 20.0]) == pytest.approx(50.0)

    def test_clamps_outside_the_range(self):
        assert vol_edge.iv_rank(99.0, [10.0, 20.0]) == 100.0
        assert vol_edge.iv_rank(1.0, [10.0, 20.0]) == 0.0

    def test_flat_history_returns_none_not_fifty(self):
        """A flat history carries no ranking information. Returning a neutral 50
        would let a caller act on a number that means nothing."""
        assert vol_edge.iv_rank(15.0, [12.0, 12.0, 12.0]) is None

    @pytest.mark.parametrize("cur,hist", [(None, [10.0, 20.0]), (15.0, []), (15.0, [10.0])])
    def test_missing_inputs_return_none(self, cur, hist):
        assert vol_edge.iv_rank(cur, hist) is None


# ── expected_vol / long_premium_ok ────────────────────────────────────────────

class TestLongPremiumOk:
    def test_blend_matches_the_kb_formula(self):
        # 0.45*20 + 0.35*10 + 0.20*15 = 9 + 3.5 + 3 = 15.5
        assert vol_edge.expected_vol(hv5=20, iv30=10, hv30=15) == pytest.approx(15.5)

    def test_cheap_when_forecast_beats_implied(self):
        ok, why = vol_edge.long_premium_ok(hv5=26, hv30=18, iv30=15)
        assert ok and "cheap" in why

    def test_rich_when_implied_beats_forecast(self):
        """The realistic SPY case: calm tape, implied still rich. This is the
        trade the router was taking every day."""
        ok, why = vol_edge.long_premium_ok(hv5=8, hv30=10, iv30=14)
        assert not ok and "variance risk premium" in why

    def test_dead_heat_is_refused(self):
        """IV also carries spread and theta — breaking even on vol is not enough."""
        ok, _ = vol_edge.long_premium_ok(hv5=14, hv30=14, iv30=14)
        assert not ok

    @pytest.mark.parametrize("hv5,hv30,iv30", [
        (None, 18, 15), (26, None, 15), (26, 18, None), (None, None, None),
    ])
    def test_missing_inputs_refuse(self, hv5, hv30, iv30):
        """The whole point: unknown must never read as cheap."""
        ok, why = vol_edge.long_premium_ok(hv5, hv30, iv30)
        assert not ok and "incomplete" in why

    def test_zero_iv_is_refused_not_divided_by(self):
        assert not vol_edge.long_premium_ok(hv5=26, hv30=18, iv30=0)[0]


# ── vol_regime ────────────────────────────────────────────────────────────────

class TestVolRegime:
    def test_expansion_after_three_big_days(self):
        r, why = vol_edge.vol_regime([0.2, 1.4, 1.8, 2.1])
        assert r == "expansion" and "priced in" in why

    def test_compression_after_five_quiet_days(self):
        assert vol_edge.vol_regime([0.2, 0.3, 0.1, 0.35, 0.2])[0] == "compression"

    def test_mixed_tape_is_normal(self):
        assert vol_edge.vol_regime([0.2, 1.4, 0.3, 0.9, 0.5])[0] == "normal"

    def test_sign_is_ignored_only_magnitude_matters(self):
        assert vol_edge.vol_regime([-1.4, 1.8, -2.1])[0] == "expansion"

    @pytest.mark.parametrize("moves", [[], [1.5], [1.5, 1.6]])
    def test_thin_history_is_normal(self, moves):
        assert vol_edge.vol_regime(moves)[0] == "normal"

    def test_expansion_halves_size(self):
        assert vol_edge.size_multiplier("expansion") == 0.5
        assert vol_edge.size_multiplier("compression") == 1.0
        assert vol_edge.size_multiplier("normal") == 1.0


# ── router integration ────────────────────────────────────────────────────────

class TestRouterVrpGate:
    def _sig(self, **kw):
        base = dict(price=120, atr=3, has_vol_edge=True, ivr=22)
        base.update(kw)
        return Signal("SPY", "bull", "vol", **base)

    @pytest.fixture(autouse=True)
    def _on(self, monkeypatch):
        monkeypatch.setattr(config, "VOL_EDGE_REQUIRED_FOR_LONG_PREMIUM", True)

    def test_rich_premium_routes_to_shares_not_options(self):
        d = route_signal(self._sig(hv5=8, hv30=10, iv30=14), _rb())
        assert d.route == "stocks" and "variance risk premium" in d.reason

    def test_cheap_premium_still_routes_to_options(self):
        d = route_signal(self._sig(hv5=26, hv30=18, iv30=15), _rb())
        assert d.route == "options"

    def test_missing_vol_data_routes_to_shares(self):
        """Today's real state: no IV is plumbed onto the Signal, so the option
        lane stays shut until it can prove premium is cheap."""
        d = route_signal(self._sig(), _rb())
        assert d.route == "stocks" and "incomplete" in d.reason

    def test_flag_off_restores_previous_behaviour(self, monkeypatch):
        monkeypatch.setattr(config, "VOL_EDGE_REQUIRED_FOR_LONG_PREMIUM", False)
        d = route_signal(self._sig(), _rb())
        assert d.route == "options"

    def test_gate_does_not_disturb_directional_only_signals(self):
        sig = Signal("SPY", "bull", "connors_rsi2", price=200, atr=4, has_vol_edge=False)
        d = route_signal(sig, _rb())
        assert d.route == "stocks" and "§5" in d.reason
