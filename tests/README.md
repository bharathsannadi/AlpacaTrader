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
