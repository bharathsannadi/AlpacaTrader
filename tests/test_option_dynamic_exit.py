"""REQ-608 — dynamic breakeven+trail ladder on the live option stop path.

Verifies app._manage_option_positions():
  * flag OFF  → behaviour unchanged (flat -50% stop; winners just hold)
  * flag ON   → the stop ratchets up so a winner that reverses exits at the
                locked floor instead of riding all the way down to -50%
  * flag ON   → a never-green loser still exits at the -50% initial stop
"""
import importlib
from types import SimpleNamespace

import pytest

app = importlib.import_module("app")
se  = importlib.import_module("screener_executor")


class _AssetClass:
    def __init__(self, value): self.value = value


def _opt(symbol, cost_basis, unrealized_pl):
    """A single option leg as the Alpaca SDK exposes it (string numerics)."""
    return SimpleNamespace(symbol=symbol, qty="1",
                           asset_class=_AssetClass("us_option"),
                           cost_basis=str(cost_basis),
                           unrealized_pl=str(unrealized_pl))


class _FakeClient:
    def __init__(self, positions):
        self._positions = positions
        self.closed = []
    def get_all_positions(self):
        return self._positions
    def close_position(self, symbol):
        self.closed.append(symbol)


@pytest.fixture
def harness(monkeypatch):
    """Isolate _manage_option_positions: fake Alpaca client, no journal/log I/O,
    clean per-underlying state, flag restored after the test."""
    leg = _opt("DIA260626C00510000", cost_basis=705, unrealized_pl=290)
    client = _FakeClient([leg])

    monkeypatch.setattr(app.trader, "TRADING_CLIENT", client, raising=False)
    monkeypatch.setattr(app.auto_engine, "_journal_add", lambda *a, **k: None)

    emitted = []
    monkeypatch.setattr(app, "_emit_log", lambda msg, **k: emitted.append(msg))

    app._opt_peak.clear()
    app._opt_exit_state.clear()
    saved = se.OPT_DYNAMIC_EXIT_ENABLED
    yield SimpleNamespace(leg=leg, client=client, emitted=emitted)
    se.OPT_DYNAMIC_EXIT_ENABLED = saved
    app._opt_peak.clear()
    app._opt_exit_state.clear()


def test_flag_off_winner_holds(harness):
    se.OPT_DYNAMIC_EXIT_ENABLED = False
    harness.leg.unrealized_pl = "290"      # +41% — below +80% TP, above -50% stop
    app._manage_option_positions()
    assert harness.client.closed == []     # nothing closed


def test_flag_off_loser_hits_flat_stop(harness):
    se.OPT_DYNAMIC_EXIT_ENABLED = False
    harness.leg.unrealized_pl = "-450"     # -64% — past the flat -50% stop
    app._manage_option_positions()
    assert harness.leg.symbol in harness.client.closed
    assert any("stop -50%" in m for m in harness.emitted)


def test_flag_on_winner_protected_after_reversal(harness):
    se.OPT_DYNAMIC_EXIT_ENABLED = True
    # tick 1: +41% gain → ladder ratchets the stop up to the +10% locked floor
    harness.leg.unrealized_pl = "290"
    app._manage_option_positions()
    assert harness.client.closed == []     # still holding, but floor now raised
    # tick 2: reverses to +6% (value 750) — below the locked floor (~775) → exit
    harness.leg.unrealized_pl = "45"
    app._manage_option_positions()
    assert harness.leg.symbol in harness.client.closed
    assert any("dynamic stop" in m for m in harness.emitted)


def test_flag_on_loser_still_exits_at_initial_stop(harness):
    se.OPT_DYNAMIC_EXIT_ENABLED = True
    harness.leg.unrealized_pl = "-450"     # never green → init stop = -50% still fires
    app._manage_option_positions()
    assert harness.leg.symbol in harness.client.closed
    assert any("dynamic stop" in m for m in harness.emitted)
