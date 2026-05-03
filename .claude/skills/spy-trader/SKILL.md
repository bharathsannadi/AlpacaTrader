---
name: spy-trader
description: >
  Guide for working on the SPY Auto Trader project at /Users/bsannadi/Desktop/alpaca_trader —
  a Flask + SocketIO options day-trading dashboard backed by the Alpaca API.
  Use this skill whenever the user asks to: run or start the dashboard; debug morning ORB or
  evening VWAP sessions; fix chart data or Alpaca feed issues; add or remove tradeable symbols;
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
                                 auto-scheduler (9:30 / 15:00 ET), caffeinate

scripts/spy_auto_trader.py    — bars + indicators, ORB/gap-fade/VWAP evaluators,
                                 option lookup + order placement

── Intelligence layer (being built) ──────────────────────────────────
scripts/news_filter.py        — [DONE] Finnhub/yfinance headline scan → veto flag
                                 called before morning/evening session fires
scripts/trade_memory.py       — [DONE] ChromaDB: store trade outcomes, retrieve
                                 similar past setups as context (custom numpy embedder)
scripts/debate.py             — [DONE] Bull agent vs Bear agent LLM debate,
                                 judge returns (proceed, confidence, reason)

scripts/security.py           — validators, LoginTracker (5-fail / 15-min lockout)
```

- **`authenticated_sids` set** — WS auth source of truth (Flask sessions don't survive polling→WS upgrade)
- **`_state_lock = RLock()`** — re-entrant; `_state_snapshot()` is single source of truth for UI state
- **TTL caches** — VIX 120s, prior levels 1h, chart bars 30s
- **`stop_event.wait(timeout=N)`** — sessions interruptible within ~1s
- **caffeinate** — Mac sleep prevented while any session is active

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

1. **`scripts/app.py`** — add `"TSLA"` to `VALID_SYMBOLS` frozenset.
2. **`scripts/spy_auto_trader.py`** — check `_strike_window()`: `max(5.0, price * 0.025)` is adaptive; verify the window makes sense for the symbol's price range.
3. **`templates/index.html`** — add a new `<button class="tab-btn" data-symbol="TSLA">TSLA</button>` in the tab bar.
4. No other files need changing — the rest of the code is already symbol-agnostic.

### Debugging "chart shows no data / 0 bars"

The fetch chain in `fetch_chart_bars()` tries feeds in order: `iex → sip → None (SDK default) → yfinance`. Check the log for:
```
fetch_chart_bars(SPY, 1D): feed='iex' returned 0 bars ... trying next feed
fetch_chart_bars(SPY, 1D): Alpaca returned 0 bars — falling back to yfinance
```
`fetch_bars()` (used by sessions) uses the same fallback chain since the fix.

### Debugging morning/evening session not triggering signals

Session evaluators live in `spy_auto_trader.py`:
- **Morning**: `evaluate_orb()` (ORB breakout) and `evaluate_gap_fade()` (gap reversal)
- **Evening**: `evaluate_vwap_momentum()`

Common reasons a signal never fires:
- `vol_ratio` < `MIN_VOL_RATIO` (1.5) — volume too light
- `rsi` out of range — overbought/oversold filter blocked it
- `or_width_pct` < `MIN_ORB_WIDTH` (0.2%) — opening range too tight, falls back to gap-fade only
- Session end time already passed before enough bars accumulated
- **News pre-filter vetoed** — check log for `"News veto"` lines

### News pre-filter (scripts/news_filter.py)

`check_news_sentiment(symbol, finnhub_key=None)` returns `(vetoed: bool, reason: str)`.

- Uses **Finnhub** if `FINNHUB_API_KEY` env var or `finnhub_key` arg is set; falls back to **yfinance** news (free, no key)
- Scans headlines from the last `NEWS_LOOKBACK_HOURS` (default 4h) for severity keywords
- Returns `vetoed=True` if any HIGH-severity keyword matches (halt, bankrupt, fraud, SEC charges, etc.)
- Returns `vetoed=True` if ≥ `NEWS_VETO_THRESHOLD` (default 3) MEDIUM-severity matches
- Called in `_launch_morning()` and `_launch_evening()` in `app.py` before the session thread starts
- Can be bypassed per-session from the UI (checkbox `news_filter_enabled` in state)

**Adding / changing keywords:**
Keywords live in `NEWS_HIGH_SEVERITY` and `NEWS_MEDIUM_SEVERITY` lists at the top of `news_filter.py`. They are checked case-insensitively against headline text.

**Finnhub key setup:**
Set `FINNHUB_API_KEY=your_key` in a `.env` file in the project root, or enter it in the UI (TODO: add to login modal). Free tier at finnhub.io covers ~60 req/min.

### ChromaDB trade memory (scripts/trade_memory.py) — DONE

`TradeMemory` class wraps a ChromaDB PersistentClient at `~/.spy_trader/memory/`.

**Key design choices:**
- Uses a custom `_IndicatorEmbedder` (pure numpy, 8-dim cosine vectors) — **no onnxruntime needed** (onnxruntime has no Python 3.14 wheels; install chromadb with `pip install chromadb --no-deps` then install deps manually on Python 3.14)
- Relative deviations (vwap_dev, ema9_dev) not absolute prices → similarity is market-structure-based
- `record()` called in `place_trade()` after order submit (uses `order.id` as trade_id)
- `retrieve_similar()` called in `run_session()` before option lookup; result is logged
- `update_outcome()` should be called after exit (TODO: wire into exit logic)
- `init_memory(enabled=True/False)` replaces singleton; called in `on_login()` and `on_toggle_trade_memory()`
- Toggled via `trade_memory_enabled` in state → `toggle_trade_memory` socket event → Trade Memory ON/OFF pill in UI

**chromadb install on Python 3.14:**
```bash
pip install chromadb --no-deps
pip install overrides typing_extensions pydantic posthog opentelemetry-api opentelemetry-sdk \
    opentelemetry-exporter-otlp-proto-grpc grpcio httpx bcrypt build importlib-resources \
    jsonschema mmh3 orjson pybase64 "pydantic-settings>=2.0" pypika pyyaml tenacity \
    tokenizers tqdm typer "uvicorn[standard]"
```

### Bull/Bear debate layer (scripts/debate.py) — DONE

`run_debate(symbol, direction, indicators, news_summary, memory_context)` → `(proceed: bool, confidence: float, summary: str)`.

**How it works:**
- Step 1 — Bull agent: makes the strongest bull case (Claude Haiku, ~100 tokens)
- Step 2 — Bear agent: makes the strongest bear case (Claude Haiku, ~100 tokens)
- Step 3 — Judge: weighs both and returns JSON `{"proceed": bool, "confidence": 0–1, "reason": "..."}` (Claude Haiku)
- If `confidence < DEBATE_MIN_CONFIDENCE` (0.65) or `proceed=False`, signal is suppressed; session waits 60s then re-evaluates
- Falls through as `(True, 1.0, "")` when `ANTHROPIC_API_KEY` is not set — safe by default

**Wiring in spy_auto_trader.py:**
- `DEBATE_ENABLED` flag (False by default, set by `init_debate()`)
- `init_debate(enabled)` checks `ANTHROPIC_API_KEY` and sets the flag
- Called after `TRADE_MEMORY.retrieve_similar()` in `run_session()`, before option lookup
- Called in `on_login()` and `on_toggle_debate()` socket handler in `app.py`

**Enabling:**
1. Set `ANTHROPIC_API_KEY=sk-ant-...` in `.env` in project root
2. Toggle "Bull/Bear debate" pill to ON in the dashboard
3. Debate starts immediately on the next signal

### Modifying trade parameters at runtime

Parameters are mirrored between the `state` dict and module-level constants in `spy_auto_trader.py`. The `on_set_param()` handler in `app.py` keeps both in sync. When adding a new parameter:
1. Add constant to `spy_auto_trader.py`
2. Add to `state` dict in `app.py`
3. Add to `_state_snapshot()`
4. Add `elif field == "my_param":` branch in `on_set_param()` with a validator
5. Add stepper widget in `templates/index.html`

### Adding a new indicator

All indicators are computed in `_add_indicators(df)` in `spy_auto_trader.py`. Add a new column using vectorized pandas/numpy operations. The new column is available to all evaluator functions via `bar["my_indicator"]`.

### Investigating Alpaca auth / login failures

Login flow: `on_login()` in `app.py` → `validate_api_key()` + `validate_api_secret()` in `security.py` → `trader.init_clients()` in `spy_auto_trader.py`. Check `scripts/security.log` for the full error. Common causes:
- Wrong key/secret → Alpaca returns 403
- Using live keys with `paper=True` or vice versa
- IP locked out after 5 failures (`LoginTracker` in `security.py`)

### Troubleshooting WebSocket auth / state-sync

`authenticated_sids` is the authoritative WS auth store. If a client action is rejected with `login_required`:
- The SID was never added (login didn't complete) or was discarded on disconnect
- Check `scripts/security.log` for "Unauthenticated socket event from …"
- Client should re-login to get a fresh SID

If state appears stale on reconnect: `on_connect()` always pushes a fresh `_state_snapshot()` with `logged_in` reflecting whether that SID is in `authenticated_sids`.
