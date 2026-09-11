"""Tests for the broker-resting protective stop (ledger review 2026-09-11).

Background: manage_exits only POLLS the stop on the position_monitor tick, so an
overnight hold was unprotected — 17 of 40 real stop exits realised worse than
-3.5% ($2,878 past a clean -3%), 10 of them filling in the first 20 minutes after
an open. The fix rests a GTC SELL stop at the broker and ratchets it with the
ladder. These tests pin the safety-critical behaviour of that path.

No Alpaca calls: shares_executor._client is monkeypatched with a fake client.
"""
import datetime

import pytest
from unittest.mock import MagicMock

import config
import shares_executor
import auto_engine


# ── fakes ─────────────────────────────────────────────────────────────────────

class FakeOrder:
    def __init__(self, oid="oid-1", fill=None):
        self.id = oid
        self.filled_avg_price = fill


class FakeClient:
    """Minimal stand-in for Alpaca's TradingClient."""

    def __init__(self, open_sells=(), positions=(), sell_fills=()):
        self._open_sells = list(open_sells)
        self._positions = list(positions)
        self._sell_fills = list(sell_fills)
        self.submitted = []
        self.cancelled = []
        self.closed = []

    def submit_order(self, req):
        self.submitted.append(req)
        return FakeOrder(oid=f"oid-{len(self.submitted)}")

    def cancel_order_by_id(self, oid):
        self.cancelled.append(oid)

    def get_orders(self, req):
        # CLOSED lookups ask for prior sell fills; OPEN lookups ask for resting stops
        if "closed" in str(getattr(req, "status", "")).lower():
            return list(self._sell_fills)
        return list(self._open_sells)

    def get_all_positions(self):
        return list(self._positions)

    def close_position(self, sym):
        self.closed.append(sym)
        return FakeOrder(oid="close-1")


class FakePos:
    def __init__(self, symbol, qty, asset_class="us_equity"):
        self.symbol = symbol
        self.qty = qty
        self.asset_class = asset_class


@pytest.fixture
def client(monkeypatch):
    c = FakeClient()
    monkeypatch.setattr(shares_executor, "_client", lambda: c)
    return c


# ── place_protective_stop ─────────────────────────────────────────────────────

class TestPlaceProtectiveStop:
    def test_dry_run_places_nothing(self, client):
        res = shares_executor.place_protective_stop("AAPL", 10, 100.0, dry_run=True)
        assert res["success"] and res["order_id"] == "dry_run"
        assert client.submitted == []

    def test_defaults_to_dry_run(self, client):
        """Safety rail 1: a new order-placing path defaults to dry_run."""
        shares_executor.place_protective_stop("AAPL", 10, 100.0)
        assert client.submitted == []

    def test_places_gtc_sell_stop(self, client):
        res = shares_executor.place_protective_stop("AAPL", 10, 99.5, dry_run=False)
        assert res["success"] and res["order_id"] == "oid-1"
        req = client.submitted[0]
        assert req.symbol == "AAPL" and req.qty == 10
        assert float(req.stop_price) == 99.5
        assert "sell" in str(req.side).lower()
        assert "gtc" in str(req.time_in_force).lower()

    def test_cancels_existing_resting_stop_first(self, client):
        """A symbol must never carry two claims on the same shares."""
        client._open_sells = [FakeOrder(oid="old-stop")]
        shares_executor.place_protective_stop("AAPL", 10, 99.5, dry_run=False)
        assert client.cancelled == ["old-stop"]

    @pytest.mark.parametrize("qty,stop", [(0, 100.0), (-5, 100.0), (10, 0.0), (10, -1.0)])
    def test_rejects_bad_inputs(self, client, qty, stop):
        res = shares_executor.place_protective_stop("AAPL", qty, stop, dry_run=False)
        assert not res["success"]
        assert client.submitted == []

    def test_refuses_stop_at_or_above_market(self, client, monkeypatch):
        """A sell stop above the last price fills instantly — that is a liquidation,
        not protection. Hits real positions when an underwater book is first brought
        under management on a restart."""
        monkeypatch.setattr(shares_executor, "current_price", lambda s: 95.0)
        res = shares_executor.place_protective_stop("AAPL", 10, 97.0, dry_run=False)
        assert not res["success"] and "market" in res["message"]
        assert client.submitted == []

    def test_allows_stop_below_market(self, client, monkeypatch):
        monkeypatch.setattr(shares_executor, "current_price", lambda s: 100.0)
        res = shares_executor.place_protective_stop("AAPL", 10, 97.0, dry_run=False)
        assert res["success"] and len(client.submitted) == 1

    def test_uses_supplied_last_price_without_refetching(self, client, monkeypatch):
        monkeypatch.setattr(shares_executor, "current_price",
                            lambda s: pytest.fail("should not refetch"))
        res = shares_executor.place_protective_stop("AAPL", 10, 97.0, dry_run=False,
                                                    last_price=100.0)
        assert res["success"]

    def test_failure_is_reported_not_raised(self, client):
        client.submit_order = MagicMock(side_effect=RuntimeError("rejected"))
        res = shares_executor.place_protective_stop("AAPL", 10, 99.5, dry_run=False)
        assert not res["success"] and "rejected" in res["message"]


class TestCloseCancelsRestingStop:
    def test_close_frees_reserved_shares_first(self, client):
        """close_position fails with 'insufficient qty' while a stop reserves the
        shares, so the cancel must happen before the close."""
        client._open_sells = [FakeOrder(oid="resting")]
        res = shares_executor.close("AAPL", dry_run=False)
        assert res["success"]
        assert client.cancelled == ["resting"]
        assert client.closed == ["AAPL"]

    def test_dry_run_close_cancels_nothing(self, client):
        shares_executor.close("AAPL", dry_run=True)
        assert client.cancelled == [] and client.closed == []


# ── held_quantities: the reap guard ───────────────────────────────────────────

class TestHeldQuantities:
    def test_maps_symbol_to_qty(self, client):
        client._positions = [FakePos("AAPL", "10"), FakePos("MSFT", "4")]
        assert shares_executor.held_quantities() == {"AAPL": 10, "MSFT": 4}

    def test_excludes_option_legs(self, client):
        client._positions = [FakePos("AAPL", "10"),
                             FakePos("AAPL260101C00100000", "1", asset_class="us_option")]
        assert shares_executor.held_quantities() == {"AAPL": 10}

    def test_returns_none_on_failure_never_empty(self, client):
        """None means 'unknown'. An empty dict would reap every managed position on
        a transient API blip."""
        client.get_all_positions = MagicMock(side_effect=RuntimeError("503"))
        assert shares_executor.held_quantities() is None


# ── _sync_protective_stop: ratchet semantics ──────────────────────────────────

class TestSyncProtectiveStop:
    @pytest.fixture(autouse=True)
    def _on(self, monkeypatch):
        monkeypatch.setattr(config, "PROTECTIVE_STOP_ENABLED", True)

    def _pos(self, **kw):
        p = {"sym": "AAPL", "qty": 10, "entry_price": 100.0,
             "exit_state": {"entry": 100.0, "hwm": 110.0, "stop": 105.0, "tier": 1},
             "dry_run": False}
        p.update(kw)
        return p

    def test_places_when_none_resting(self, monkeypatch):
        calls = []
        monkeypatch.setattr(auto_engine, "_rest_protective_stop",
                            lambda *a, **k: calls.append(a) or "oid-9")
        p = self._pos(stop_resting_at=None)
        auto_engine._sync_protective_stop(p, dry_run=False)
        assert p["stop_order_id"] == "oid-9" and p["stop_resting_at"] == 105.0

    def test_ratchets_up_past_threshold(self, monkeypatch):
        monkeypatch.setattr(auto_engine, "_rest_protective_stop", lambda *a, **k: "oid-9")
        p = self._pos(stop_resting_at=100.0)          # ladder lifted 100 → 105
        auto_engine._sync_protective_stop(p, dry_run=False)
        assert p["stop_resting_at"] == 105.0

    def test_ignores_sub_threshold_move(self, monkeypatch):
        """The 10s tick must not churn cancel/replace pairs for sub-cent moves."""
        called = []
        monkeypatch.setattr(auto_engine, "_rest_protective_stop",
                            lambda *a, **k: called.append(a) or "x")
        p = self._pos(stop_resting_at=104.9)          # 0.1% < 0.25% threshold
        auto_engine._sync_protective_stop(p, dry_run=False)
        assert called == [] and p["stop_resting_at"] == 104.9

    def test_never_lowers_a_resting_stop(self, monkeypatch):
        called = []
        monkeypatch.setattr(auto_engine, "_rest_protective_stop",
                            lambda *a, **k: called.append(a) or "x")
        p = self._pos(stop_resting_at=108.0)          # resting ABOVE the ladder stop
        auto_engine._sync_protective_stop(p, dry_run=False)
        assert called == [] and p["stop_resting_at"] == 108.0

    def test_gives_up_after_repeated_failures(self, monkeypatch):
        called = []
        monkeypatch.setattr(auto_engine, "_rest_protective_stop",
                            lambda *a, **k: called.append(a) or None)
        p = self._pos(stop_resting_at=None)
        for _ in range(6):
            auto_engine._sync_protective_stop(p, dry_run=False)
        assert len(called) == 3 and p["stop_rest_attempts"] == 3

    def test_noop_when_flag_off(self, monkeypatch):
        monkeypatch.setattr(config, "PROTECTIVE_STOP_ENABLED", False)
        called = []
        monkeypatch.setattr(auto_engine, "_rest_protective_stop",
                            lambda *a, **k: called.append(a) or "x")
        auto_engine._sync_protective_stop(self._pos(stop_resting_at=None), dry_run=False)
        assert called == []


# ── _reap_vanished ────────────────────────────────────────────────────────────

class TestReapVanished:
    def test_records_realized_from_the_real_fill(self, monkeypatch):
        monkeypatch.setattr(shares_executor, "last_sell_fill", lambda s: 95.0)
        seen = []
        monkeypatch.setattr(auto_engine, "_record_realized", lambda v: seen.append(v))
        auto_engine._reap_vanished({"sym": "AAPL", "qty": 10, "entry_price": 100.0})
        assert seen == [-50.0]

    def test_never_fabricates_a_closed_trade_row(self, monkeypatch):
        """The real-fill ledger in app.py is the single source of truth for closes
        (2026-06-16 fabrication bug). The engine must not invent one here."""
        monkeypatch.setattr(shares_executor, "last_sell_fill", lambda s: 95.0)
        monkeypatch.setattr(auto_engine, "_record_realized", lambda v: None)
        logged = []
        monkeypatch.setattr(auto_engine, "_log_closed_trade", lambda d: logged.append(d))
        monkeypatch.setattr(auto_engine, "_journal_add",
                            lambda *a, **k: logged.append(a))
        auto_engine._reap_vanished({"sym": "AAPL", "qty": 10, "entry_price": 100.0})
        assert logged == []

    def test_survives_unknown_fill(self, monkeypatch):
        monkeypatch.setattr(shares_executor, "last_sell_fill", lambda s: None)
        seen = []
        monkeypatch.setattr(auto_engine, "_record_realized", lambda v: seen.append(v))
        auto_engine._reap_vanished({"sym": "AAPL", "qty": 10, "entry_price": 100.0})
        assert seen == []          # no fill price → no invented P&L


# ── manage_exits reconciliation ───────────────────────────────────────────────

class TestManageExitsReconciliation:
    """A resting stop can fill BETWEEN ticks, so manage_exits must notice the
    position is gone. Otherwise the poll keeps trying to close a position that
    isn't there, the churn guard keeps it in the store forever, and the stale
    entry blocks re-entry on that symbol."""

    @pytest.fixture
    def store(self, monkeypatch):
        saved = {}
        # Relative, not a literal date — a fixed one would age past TIME_CAP_DAYS
        # and start force-closing the position, silently changing what we assert.
        entry_date = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        saved["v"] = [{"sym": "AAPL", "route": "stocks", "qty": 10, "entry_price": 100.0,
                       "entry_date": entry_date, "dry_run": False,
                       "stop_resting_at": 97.0, "stop_order_id": "oid-1",
                       "exit_state": {"entry": 100.0, "hwm": 100.0, "stop": 97.0,
                                      "tier": 0}}]
        # Round-trips through `saved` so per-position counters persist across calls,
        # the way the real on-disk store does.
        monkeypatch.setattr(auto_engine, "_load_positions",
                            lambda: [dict(p) for p in saved["v"]])
        monkeypatch.setattr(auto_engine, "_save_positions",
                            lambda v: saved.__setitem__("v", v))
        monkeypatch.setattr(auto_engine, "_record_realized", lambda v: None)
        return saved

    def test_reaps_position_gone_from_account(self, store, monkeypatch):
        monkeypatch.setattr(shares_executor, "held_quantities", lambda: {})
        monkeypatch.setattr(shares_executor, "last_sell_fill", lambda s: 97.0)
        closed = []
        monkeypatch.setattr(shares_executor, "close",
                            lambda s, dry_run=False: closed.append(s))
        auto_engine.manage_exits(dry_run=False)
        assert store["v"] == []          # dropped from the store
        assert closed == []              # and NOT re-closed

    def test_keeps_position_when_lookup_fails(self, store, monkeypatch):
        """None means 'unknown' — a transient API failure must not empty the store."""
        monkeypatch.setattr(shares_executor, "held_quantities", lambda: None)
        monkeypatch.setattr(shares_executor, "current_price", lambda s: 100.0)
        auto_engine.manage_exits(dry_run=False)
        assert [p["sym"] for p in store["v"]] == ["AAPL"]

    def test_keeps_position_still_held(self, store, monkeypatch):
        monkeypatch.setattr(shares_executor, "held_quantities", lambda: {"AAPL": 10})
        monkeypatch.setattr(shares_executor, "current_price", lambda s: 100.0)
        auto_engine.manage_exits(dry_run=False)
        assert [p["sym"] for p in store["v"]] == ["AAPL"]

    def test_resizes_stop_when_account_qty_drifted(self, store, monkeypatch):
        """record_stock_position no-ops on an already-tracked symbol, so adding to
        a position left the managed qty stale. Harmless for close_position, but it
        SIZES the resting stop — the 2026-09-11 rollout rested a stop on 1 share
        of HOOD's 40."""
        placed = []
        monkeypatch.setattr(shares_executor, "held_quantities", lambda: {"AAPL": 40})
        monkeypatch.setattr(shares_executor, "current_price", lambda s: 100.0)
        monkeypatch.setattr(auto_engine, "_rest_protective_stop",
                            lambda sym, qty, stop, dry, px=None:
                            placed.append(qty) or "oid-new")
        auto_engine.manage_exits(dry_run=False)
        assert placed == [40], "stop must be re-placed at the ACCOUNT quantity"
        assert store["v"][0]["qty"] == 40

    def test_no_resize_when_qty_matches(self, store, monkeypatch):
        placed = []
        monkeypatch.setattr(shares_executor, "held_quantities", lambda: {"AAPL": 10})
        monkeypatch.setattr(shares_executor, "current_price", lambda s: 100.0)
        monkeypatch.setattr(auto_engine, "_rest_protective_stop",
                            lambda *a, **k: placed.append(a) or "x")
        auto_engine.manage_exits(dry_run=False)
        assert placed == []

    def test_missing_price_counts_and_warns(self, store, monkeypatch, caplog):
        """A dead price feed used to skip the stop check SILENTLY, leaving the
        position unmanaged with nothing in the log to say so."""
        monkeypatch.setattr(shares_executor, "held_quantities", lambda: {"AAPL": 10})
        monkeypatch.setattr(shares_executor, "current_price", lambda s: None)
        with caplog.at_level("WARNING"):
            for _ in range(3):
                auto_engine.manage_exits(dry_run=False)
        assert [p["sym"] for p in store["v"]] == ["AAPL"]   # still managed
        assert any("BLIND" in r.message for r in caplog.records)


# ── cooldown window regression ────────────────────────────────────────────────

def test_cooldown_window_spans_observed_reentry_gaps():
    """The 5-day window caught ZERO of the 165 real closes — repeat-loser re-entries
    were spaced 7-14 days apart (ORCL 7x/-$1,355, NVDA 10x/-$543, INTC 5x/-$565)."""
    assert config.SYMBOL_COOLDOWN_WINDOW_DAYS >= 15


# ── Stale-order sweep must not eat protective stops ───────────────────────────

class TestReconcilerExemptsProtectiveStops:
    """_reconcile_orders_positions cancels OPEN orders unfilled for >10 minutes,
    to clean up entry orders whose fill timeout didn't fire. A protective stop is
    unfilled and long-lived BY DESIGN and matched that rule exactly: on
    2026-09-11 it cancelled all 8 protective stops, and had been silently killing
    daily_trader's GTC stops since that path was written."""

    def _order(self, otype):
        return type("O", (), {"order_type": otype, "side": "sell",
                              "symbol": "AAPL", "id": "x", "filled_qty": 0})()

    @pytest.mark.parametrize("otype", ["stop", "OrderType.STOP", "stop_limit",
                                       "trailing_stop"])
    def test_stop_orders_are_protected(self, otype):
        import app
        assert app._is_protective_order(self._order(otype)) is True

    @pytest.mark.parametrize("otype", ["limit", "market", "OrderType.LIMIT"])
    def test_entry_orders_are_still_sweepable(self, otype):
        import app
        assert app._is_protective_order(self._order(otype)) is False

    def test_missing_type_is_not_treated_as_protective(self):
        """Fail toward the old behaviour rather than silently disabling the sweep
        for orders we can't classify."""
        import app
        assert app._is_protective_order(type("O", (), {})()) is False


# ── Self-healing: verify the stop against the broker, don't trust the store ────

class TestStopVerification:
    """A stored stop_order_id is not proof the stop exists. The stale-order sweep
    cancelled all 8 on 2026-09-11 and the app carried on believing they were
    there — a stale id is worse than none, because it suppresses the re-place."""

    @pytest.fixture
    def store(self, monkeypatch):
        saved = {}
        entry_date = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        saved["v"] = [{"sym": "AAPL", "route": "stocks", "qty": 10,
                       "entry_price": 100.0, "entry_date": entry_date,
                       "dry_run": False, "stop_resting_at": 97.0,
                       "stop_order_id": "gone",
                       "exit_state": {"entry": 100.0, "hwm": 100.0, "stop": 97.0,
                                      "tier": 0}}]
        monkeypatch.setattr(auto_engine, "_load_positions",
                            lambda: [dict(p) for p in saved["v"]])
        monkeypatch.setattr(auto_engine, "_save_positions",
                            lambda v: saved.__setitem__("v", v))
        monkeypatch.setattr(shares_executor, "held_quantities", lambda: {"AAPL": 10})
        monkeypatch.setattr(shares_executor, "current_price", lambda s: 100.0)
        return saved

    def test_replaces_a_stop_that_vanished(self, store, monkeypatch):
        placed = []
        monkeypatch.setattr(shares_executor, "resting_sell_quantities", lambda: {})
        monkeypatch.setattr(auto_engine, "_rest_protective_stop",
                            lambda sym, qty, stop, dry, px=None:
                            placed.append(qty) or "oid-new")
        auto_engine.manage_exits(dry_run=False)
        assert placed == [10]
        assert store["v"][0]["stop_order_id"] == "oid-new"

    def test_replaces_an_undersized_resting_stop(self, store, monkeypatch):
        placed = []
        monkeypatch.setattr(shares_executor, "resting_sell_quantities",
                            lambda: {"AAPL": 1})       # 1 of 10 — the HOOD case
        monkeypatch.setattr(auto_engine, "_rest_protective_stop",
                            lambda sym, qty, stop, dry, px=None:
                            placed.append(qty) or "oid-new")
        auto_engine.manage_exits(dry_run=False)
        assert placed == [10]

    def test_leaves_a_correct_stop_alone(self, store, monkeypatch):
        placed = []
        monkeypatch.setattr(shares_executor, "resting_sell_quantities",
                            lambda: {"AAPL": 10})
        monkeypatch.setattr(auto_engine, "_rest_protective_stop",
                            lambda *a, **k: placed.append(a) or "x")
        auto_engine.manage_exits(dry_run=False)
        assert placed == [], "a healthy stop must not be churned every tick"

    def test_failed_lookup_does_not_churn(self, store, monkeypatch):
        """None means unknown — re-placing every stop on an API blip would cancel
        and resubmit real protection for no reason."""
        placed = []
        monkeypatch.setattr(shares_executor, "resting_sell_quantities", lambda: None)
        monkeypatch.setattr(auto_engine, "_rest_protective_stop",
                            lambda *a, **k: placed.append(a) or "x")
        auto_engine.manage_exits(dry_run=False)
        assert placed == []
