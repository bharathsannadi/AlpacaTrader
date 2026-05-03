---
name: spy-trader
description: >
  Guide for working on the SPY Auto Trader project at /Users/bsannadi/Desktop/alpaca_trader —
  a Flask + SocketIO options day-trading dashboard backed by the Alpaca API.
  Use this skill whenever the user asks to: run or start the dashboard; debug morning ORB or
  evening VWAP sessions; fix chart data or Alpaca feed issues; add or remove tradeable symbols;
  tune trading parameters (VIX max, stop loss, profit target, DTE); modify indicators or signal
  logic; investigate WebSocket auth or state-sync problems; review or harden the security layer.
  Invoke even if the user doesn't say "spy-trader" — any question touching session logic,
  Alpaca API, the dashboard UI, or the trading strategy belongs here.
---

# SPY Auto Trader — Developer Skill

## Project root
`/Users/bsannadi/Desktop/alpaca_trader`

## File map — read only what you need

| Task | Files to read |
|------|--------------|
| Start / run the app | `app.py` (entry point), `requirements.txt` |
| Trading logic, signals, indicators | `spy_auto_trader.py` |
| WebSocket events, state, caches | `app.py` |
| Security: login lockout, validators | `security.py` |
| Dashboard UI, layout, tabs | `templates/index.html` |
| Chart, approval modal, JS logic | `static/main.js` |

Don't read the entire codebase speculatively. Start with the file most relevant to the task, then follow imports or cross-references only when you actually need to.

## How to run the app

```bash
cd /Users/bsannadi/Desktop/alpaca_trader
source venv/bin/activate
python app.py
```

Opens at **http://localhost:5000**. Logs go to `spy_trader.log` and `security.log`.

## Architecture at a glance

- **`app.py`** owns the web layer: Flask routes, SocketIO events, a single `state` dict guarded by `_state_lock = RLock()`, TTL caches for VIX/prior-levels/chart-bars, a `TradeApproval` class for the UI approval modal, and `authenticated_sids` (a set of socket IDs) as the WS auth source of truth.
- **`spy_auto_trader.py`** owns the trading layer: Alpaca client init, bar fetching + indicator stack, ORB/gap-fade/VWAP-momentum evaluators, option lookup, order placement. Sessions run in daemon threads started from `app.py`.
- **`security.py`** owns validators and the `LoginTracker` lockout (5 failures → 15-min lockout per IP).

## Coding patterns — always follow these

### State mutations
All reads/writes to `state`, `signal_history`, and `authenticated_sids` must be inside `with _state_lock:`. Use `_state_snapshot()` as the single source of truth for emitting state to clients; never hand-roll a partial state dict (except the special `stop_stream` path which already exists).

### Interruptible waits
Use `stop_event.wait(timeout=N)` instead of `time.sleep(N)` inside session loops. This keeps sessions responsive to the Stop button within ~1 second.

### Input validation
Every value arriving from the UI must pass through a `validate_*` function in `security.py` before touching `state` or module-level trader constants. Raise `ValueError` with a user-friendly message; the handler catches it and emits a `"log"` event.

### Named constants
Add new tunables as module-level named constants (e.g. `TICKER_INTERVAL_SEC = 15`), not magic numbers inline.

### New SocketIO event handlers
Decorate with `@require_auth` and call `emit_state()` at the end so the UI stays in sync.

## Common task playbooks

### Adding a new tradeable symbol (e.g. TSLA)

1. **`app.py`** — add `"TSLA"` to `VALID_SYMBOLS` frozenset (line ~49).
2. **`spy_auto_trader.py`** — check `_strike_window()`: the formula `max(5.0, price * 0.025)` is adaptive, but verify the resulting window makes sense for TSLA's typical price range (TSLA ~$200 → ~$5 window, which is fine; adjust the multiplier if needed).
3. **`templates/index.html`** — add a new `<button class="tab-btn" data-symbol="TSLA">TSLA</button>` in the tab bar alongside the existing 6 symbols.
4. No other files need changing — the rest of the code is already symbol-agnostic.

### Debugging "chart shows no data / 0 bars"

The fetch chain in `fetch_chart_bars()` tries feeds in order: `iex → sip → None (SDK default) → yfinance`. Check the log output for lines like:
```
fetch_chart_bars(SPY, 1D): feed='iex' returned 0 bars ... trying next feed
fetch_chart_bars(SPY, 1D): Alpaca returned 0 bars — falling back to yfinance
```
- If all Alpaca feeds return 0: confirm the `DATA_CLIENT` is initialized (user must be logged in).
- If yfinance also fails: the symbol may not be recognized by yfinance or the internet is unavailable.
- 1D mode filters to the most recent ET date with bars — on weekends/holidays this rolls back to the last trading day automatically.

### Debugging morning/evening session not triggering signals

Session evaluators live in `spy_auto_trader.py`:
- **Morning**: `evaluate_orb()` (ORB breakout) and `evaluate_gap_fade()` (gap reversal)
- **Evening**: `evaluate_vwap_momentum()`

Each has multi-condition gates. Common reasons a signal never fires:
- `vol_ratio` < `MIN_VOL_RATIO` (1.5) — volume too light
- `rsi` out of range — overbought/oversold filter blocked it
- `or_width_pct` < `MIN_ORB_WIDTH` (0.2%) — opening range too tight, falls back to gap-fade only
- Session end time already passed before enough bars accumulated

Add a temporary `log.info(f"  eval: direction={direction} reason={reason}")` after each evaluator call in `run_session()` to trace what's being evaluated.

### Modifying trade parameters at runtime

Parameters are mirrored between the `state` dict (for UI display) and module-level constants in `spy_auto_trader.py` (used by trading logic). The `on_set_param()` handler in `app.py` keeps both in sync via `validate_*` functions. When adding a new parameter:
1. Add the constant to `spy_auto_trader.py` (e.g. `MY_PARAM = 10`).
2. Add it to `state` dict in `app.py`.
3. Add it to `_state_snapshot()`.
4. Add a new `elif field == "my_param":` branch in `on_set_param()` with a validator.
5. Add a stepper widget in `templates/index.html`.

### Adding a new indicator

All indicators are computed in `_add_indicators(df)` in `spy_auto_trader.py`. The function operates on a pandas DataFrame with columns: `close_price`, `high_price`, `low_price`, `volume`, `begins_at`. Add a new column using vectorized pandas/numpy operations. Return `df` at the end (it already does). The new column is then available to all evaluator functions via `bar["my_indicator"]`.

### Investigating Alpaca auth / login failures

Login flow: `on_login()` in `app.py` → `validate_api_key()` + `validate_api_secret()` in `security.py` → `trader.init_clients()` in `spy_auto_trader.py`. If `init_clients()` raises, the error string is truncated to 120 chars and sent back as `login_result.error`. Check `security.log` for the full error. Common causes:
- Wrong key/secret → Alpaca returns 403
- Using live keys with `paper=True` or vice versa → account mismatch
- IP is locked out after 5 failures (see `LoginTracker` in `security.py`)

### Troubleshooting WebSocket auth / state-sync

`authenticated_sids` is the authoritative WS auth store — Flask sessions alone are not reliable across the polling→WebSocket transport upgrade. If a client action is rejected with `login_required`:
- The SID was never added (login didn't complete) or was discarded on disconnect.
- Check `security.log` for "Unauthenticated socket event from …".
- The client should re-login to get a fresh SID added to `authenticated_sids`.

If state appears stale on reconnect: `on_connect()` always pushes a fresh `_state_snapshot()` to the new SID, with `logged_in` reflecting whether that SID is in `authenticated_sids`. Verify the client is calling `socket.connect()` and listening for the `"state"` event on reconnect.
