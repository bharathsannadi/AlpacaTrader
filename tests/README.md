# tests/

The starter test suite. Designed to be **fast** (no network calls, no Alpaca),
**hermetic** (uses tmp directories, mocks the order client), and **safe**
(can't accidentally place a real order even if you point it at production).

## What's covered

| File | Coverage |
|------|----------|
| `test_security.py` | All input validators in `security.py` (api key/secret/risk/vix/stop/profit/dte/time/bool) + `LoginTracker` lockout + per-IP isolation + sliding-window pruning |
| `test_screener_executor.py` | `_normalize_alpaca_status` enum mapping, `_verify_fill` polling logic (immediate-fill / rejected / timeout / pending-then-fill / API errors / malformed responses), risk-budget constants |
| `test_auto_exec_persistence.py` | `_load_auto_exec_state` and `_save_auto_exec_state`: roundtrip, stale-file discard, missing-file noop, corrupt-JSON noop, atomic temp-file rename, parent-dir creation, dedup constants guard |
| `test_daily_trader_options_gate.py` | The SECOND options lane: daily_trader builds its own contracts and never calls the router, so it needed the SPY/QQQ whitelist and the §22 gate enforced separately (it was observed opening an NVDA call after both were live elsewhere). Covers whitelist-before-network, §22 refusal on rich/missing vol, and `_get_hv5` |
| `test_vol_edge.py` | KB §22 variance-risk-premium gate: HV annualisation, TRUE IV rank (flat history → None, never a neutral 50), the §22 forecast blend, GARCH regime reads, and the router integration — above all that missing vol inputs REFUSE rather than reading as "cheap" |
| `test_protective_stop.py` | Broker-resting GTC stop: dry-run default, GTC/SELL order shape, cancel-before-replace, refusal to rest a stop at/above market (would liquidate instantly), `close()` cancelling reserved shares first, `held_quantities` returning None (not `{}`) on API failure, ratchet semantics (up only, threshold, give-up after 3 failures), `_reap_vanished` never fabricating a closed-trade row, and `manage_exits` reconciliation incl. the dead-price-feed warning |

## What's NOT covered (yet)

- The full screener-executor live path (would require Alpaca + yfinance mocks)
- `_auto_exec_options` end-to-end flow in `app.py` (would require booting Flask)
- `screener_engine` indicator math
- The JavaScript frontend
- Any actual order-placement logic

These are tracked as follow-up items in [`../TODO.md`](../TODO.md).

## Running

From the repo root:

```bash
PYTHONPATH=venv/lib/python3.11/site-packages \
  /usr/local/Cellar/python@3.11/3.11.15_1/Frameworks/Python.framework/Versions/3.11/bin/python3.11 \
  -m pytest tests/ -v
```

Or, simpler, after activating the venv:

```bash
source venv/bin/activate
pytest tests/ -v
```

Single file:

```bash
pytest tests/test_security.py -v
```

Single test:

```bash
pytest tests/test_security.py::TestValidateApiKey::test_accepts_typical_paper_key -v
```

## Adding tests

`conftest.py` puts `scripts/` on `sys.path`, so `from security import ...` and
`import screener_executor` just work. Match the pattern:

- One file per module under test (`test_<module>.py`)
- Group related cases in a `TestSomething:` class
- Use `pytest.mark.parametrize` for the same shape with varying inputs
- Use `tmp_path` and `monkeypatch` fixtures for anything that touches disk or
  module globals — never write to real files in tests

Aim to keep the whole suite < 5 seconds end-to-end. If something is slow, mock
it; if you can't mock it, mark it `@pytest.mark.slow` and exclude by default.
