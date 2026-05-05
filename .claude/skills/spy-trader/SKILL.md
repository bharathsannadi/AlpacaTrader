---
name: spy-trader
description: >
  Guide for working on the SPY Auto Trader project at /Users/bsannadi/Desktop/alpaca_trader —
  a Flask + SocketIO options day-trading dashboard backed by the Alpaca API.
  Use this skill whenever the user asks to: run or start the dashboard; debug the all-day trading
  session; fix chart data or Alpaca feed issues; add or remove tradeable symbols;
  tune trading parameters (VIX max, stop loss, profit target, DTE); modify indicators or signal
  logic; investigate WebSocket auth or state-sync problems; review or harden the security layer;
  work on the news pre-filter, ChromaDB trade memory, or bull/bear debate layer.
  Invoke even if the user doesn't say "spy-trader" — any question touching session logic,
  Alpaca API, the dashboard UI, or the trading strategy belongs here.
---

# SPY Auto Trader — Developer Skill

## Project root
`/Users/bsannadi/Desktop/alpaca_trader`

## File map — read only what you need

| Task | Files to read |
|------|--------------|
| Start / run the app | `scripts/app.py` (entry point), `requirements.txt` |
| Trading logic, signals, indicators | `scripts/spy_auto_trader.py` |
| News pre-filter (veto bad-news sessions) | `scripts/news_filter.py` |
| ChromaDB trade memory | `scripts/trade_memory.py` |
| Bull/Bear debate layer | `scripts/debate.py` |
| WebSocket events, state, caches | `scripts/app.py` |
| Security: login lockout, validators | `scripts/security.py` |
| Dashboard UI, layout, tabs | `templates/index.html` |
| Chart, approval modal, JS logic | `static/main.js` |

Don't read the entire codebase speculatively. Start with the file most relevant to the task, then follow imports or cross-references only when you actually need to.

## How to run the app

```bash
cd /Users/bsannadi/Desktop/alpaca_trader
source venv/bin/activate
python scripts/app.py
```

Opens at **http://localhost:5000**. Logs go to `scripts/spy_trader.log` and `scripts/security.log`.

## Architecture at a glance

```
Browser (Flask + SocketIO)
  └── scripts/app.py          — web layer, state dict (RLock), TTL caches,
                                 auto-scheduler (9:30 ET), caffeinate

scripts/spy_auto_trader.py    — bars + indicators, ORB/gap-fade/VWAP evaluators,
                                 all_day_session(), option lookup + order placement

── Intelligence layer ────────────────────────────────────────────────
scripts/news_filter.py        — [DONE] Finnhub/yfinance headline scan → veto flag
                                 called before each session fires
scripts/trade_memory.py       — [DONE] ChromaDB: store trade outcomes, retrieve
                                 similar past setups as context (custom numpy embedder)
scripts/debate.py             — [DONE] Bull agent vs Bear agent LLM debate,
                                 judge returns (proceed, confidence, reason)

scripts/security.py           — validators, LoginTracker (5-fail / 15-min lockout)
```

- **`authenticated_sids` set** — WS auth source of truth (Flask sessions don't survive polling→WS upgrade)
- **`_state_lock = RLock()`** — re-entrant; `_state_snapshot()` is single source of truth for UI state
- **TTL caches** — VIX 120s, prior levels 1h, chart bars 30s (bypassable with `force_refresh=True`)
- **`stop_event.wait(timeout=N)`** — sessions interruptible within ~1s
- **caffeinate** — Mac sleep prevented while any session is active
- **Tabs are chart-only** — switching tabs changes the chart view; sessions run independently per symbol
- **VIX via yfinance** — Alpaca's free IEX feed doesn't support index symbols (`^VIX`)

## Session architecture (all-day, per-symbol)

### Key change (replaced morning/evening sessions)
The dashboard now uses a single **all-day session** (9:30–configurable end time ET) per symbol.
Multiple symbols can trade simultaneously — sessions are fully independent.

**State**:
```python
state["sessions"]    # {SPY: bool, AMZN: bool, GOOG: bool, ...}  — per-symbol running flag
state["session_end"] # "15:45" — configurable end time HH:MM ET
```

**Thread management** (in `app.py`):
```python
_session_threads:     dict[str, threading.Thread]
_session_stop_events: dict[str, threading.Event]   # one per symbol in _SYMBOLS_ORDERED
```

**Evaluator schedule inside `all_day_session()`** (`spy_auto_trader.py`):
- 9:30–10:30 ET (opening phase): ORB breakout + gap fade
- All day: VWAP momentum + gap fade as additional fallback
- 11:30–13:30 ET: lunch-hour block (no new signals)
- 5-minute cool-down between entries to avoid over-trading
- Multiple trades per day are allowed (unlike old single-trade sessions)

**Socket events**:
| Event | Description |
|-------|-------------|
| `start_session {symbol}` | Start session for one symbol (defaults to active_symbol) |
| `stop_session {symbol}` | Stop session for one symbol |
| `start_all_sessions` | Start sessions for all 6 symbols simultaneously |
| `stop_all_sessions` | Stop all running sessions |
| `set_session_end {session_end}` | Update end time (HH:MM ET) |

**Auto-scheduler**: fires at 9:30 ET on weekdays → starts sessions for **all** symbols.

## Coding patterns — always follow these

### State mutations
All reads/writes to `state`, `signal_history`, and `authenticated_sids` must be inside `with _state_lock:`. Use `_state_snapshot()` as the single source of truth for emitting state to clients.

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

1. **`scripts/app.py`** — add `"TSLA"` to `VALID_SYMBOLS` frozenset AND `_SYMBOLS_ORDERED` list; add a stop event: `_session_stop_events["TSLA"] = threading.Event()`.
2. **`scripts/spy_auto_trader.py`** — check `_strike_window()`: `max(5.0, price * 0.025)` is adaptive; verify the window makes sense for the symbol's price range.
3. **`templates/index.html`** — add tab button with dot: `<button class="symbol-tab" data-symbol="TSLA" onclick="setActiveSymbol('TSLA')"><span class="tab-dot" id="tab-dot-TSLA"></span>TSLA</button>`.
4. No other files need changing — the rest of the code is already symbol-agnostic.

### Debugging "chart shows no data / 0 bars"

The fetch chain in `fetch_chart_bars()` tries feeds in order: `iex → sip → None (SDK default) → yfinance`. Check the log for:
```
fetch_chart_bars(SPY, 1D): feed='iex' returned 0 bars ... trying next feed
fetch_chart_bars(SPY, 1D): Alpaca returned 0 bars — falling back to yfinance
```
The ↻ button passes `force_refresh: true` to bypass the 30s cache. The chart also auto-refreshes every 60s in 1D mode.

### Debugging all-day session not triggering signals

Evaluators live in `spy_auto_trader.py` inside `all_day_session()`:
- **Opening phase** (before 10:30 ET): `evaluate_orb()` + `evaluate_gap_fade()`
- **All day**: `evaluate_vwap_momentum()` + `evaluate_gap_fade()`

Common reasons a signal never fires:
- `vol_ratio` < `MIN_VOL_RATIO` (1.5) — volume too light
- `rsi` out of range — overbought/oversold filter blocked it
- `or_width_pct` < `MIN_ORB_WIDTH` (0.2%) — opening range too tight (ORB skipped; gap fade still runs)
- Inside lunch-hour block (11:30–13:30 ET)
- 5-minute cool-down after last trade still active
- **News pre-filter vetoed** — check log for `"News filter blocked"` lines
- **VIX too high** — check log for `"VIX too high"` line at session start

### VIX troubleshooting

VIX is fetched via **yfinance** (`^VIX`, 1-minute bars, last close price). Alpaca's free IEX feed doesn't support index symbols — do NOT revert to the Alpaca path. If VIX shows `—` in the header:
- Check log: `fetch_vix yfinance failed: ...`
- yfinance may be rate-limited — wait for the next 120s cache cycle

### News pre-filter (scripts/news_filter.py)

`check_news_sentiment(symbol, finnhub_key=None)` returns `(vetoed: bool, reason: str)`.

- Uses **Finnhub** if `FINNHUB_API_KEY` env var or `finnhub_key` arg is set; falls back to **yfinance** news (free, no key)
- Scans headlines from the last `NEWS_LOOKBACK_HOURS` (default 4h) for severity keywords
- Returns `vetoed=True` if any HIGH-severity keyword matches (halt, bankrupt, fraud, SEC charges, etc.)
- Returns `vetoed=True` if ≥ `NEWS_VETO_THRESHOLD` (default 3) MEDIUM-severity matches
- Called in `_launch_session()` in `app.py` before the session thread starts

### ChromaDB trade memory (scripts/trade_memory.py) — DONE

`TradeMemory` class wraps a ChromaDB PersistentClient at `~/.spy_trader/memory/`.

**Key design choices:**
- Custom `_IndicatorEmbedder` (pure numpy, 8-dim cosine vectors) — no onnxruntime needed
- `record()` called in `place_trade()` after order submit
- `retrieve_similar()` called in `all_day_session()` before option lookup; result is logged
- `init_memory(enabled=True/False)` replaces singleton; called on login/toggle

### Bull/Bear debate layer (scripts/debate.py) — DONE

`run_debate(symbol, direction, indicators, news_summary, memory_context)` → `(proceed: bool, confidence: float, summary: str)`.

- Bull agent → Bear agent → Judge, all Claude Haiku
- If `confidence < DEBATE_MIN_CONFIDENCE` (0.65) or `proceed=False`, signal suppressed
- Falls through as `(True, 1.0, "")` when `ANTHROPIC_API_KEY` is not set

**Wiring**: called in `all_day_session()` after `retrieve_similar()`, before option lookup.

**Enabling**: set `ANTHROPIC_API_KEY=sk-ant-...` in `.env`, then toggle "Bull/Bear LLM" pill in the dashboard.

### Modifying trade parameters at runtime

Parameters are mirrored between the `state` dict and module-level constants in `spy_auto_trader.py`. The `on_set_param()` handler in `app.py` keeps both in sync. When adding a new parameter:
1. Add constant to `spy_auto_trader.py`
2. Add to `state` dict in `app.py`
3. Add to `_state_snapshot()`
4. Add `elif field == "my_param":` branch in `on_set_param()` with a validator
5. Add stepper widget in `templates/index.html`

### Chart auto-refresh

- 1D timeframe auto-refreshes every 60s via `startChartAutoRefresh()` in `main.js`
- Other timeframes only refresh on user action (tab switch, ↻, login)
- ↻ button passes `force_refresh: true` → bypasses the 30s server-side cache
- `stopChartAutoRefresh()` called when switching to non-1D timeframes

### Investigating Alpaca auth / login failures

Login flow: `on_login()` in `app.py` → `validate_api_key()` + `validate_api_secret()` in `security.py` → `trader.init_clients()` in `spy_auto_trader.py`. Check `scripts/security.log` for the full error.

### Troubleshooting WebSocket auth / state-sync

`authenticated_sids` is the authoritative WS auth store. If a client action is rejected with `login_required`:
- The SID was never added (login didn't complete) or was discarded on disconnect
- Check `scripts/security.log` for "Unauthenticated socket event from …"

If state appears stale on reconnect: `on_connect()` always pushes a fresh `_state_snapshot()` with `logged_in` reflecting whether that SID is in `authenticated_sids`.
