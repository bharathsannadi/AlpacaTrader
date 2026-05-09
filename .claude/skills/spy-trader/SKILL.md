---
name: spy-trader
description: >
  Guide for working on the SPY Auto Trader project at /Users/bsannadi/Desktop/alpaca_trader —
  a Flask + SocketIO options day-trading dashboard backed by the Alpaca API.
  Use this skill whenever the user asks to: run or start the dashboard; debug the all-day trading
  session; fix chart data or Alpaca feed issues; add or remove tradeable symbols;
  tune trading parameters (VIX max, stop loss, profit target, DTE); modify indicators or signal
  logic; investigate WebSocket auth or state-sync problems; review or harden the security layer;
  work on the news pre-filter, ChromaDB trade memory, bull/bear debate layer, or EOD review.
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
                                 auto-scheduler (9:30 / 15:35 ET), caffeinate,
                                 position monitor (30s), EOD review trigger

scripts/spy_auto_trader.py    — bars + indicators, signal evaluators,
                                 all_day_session(), option lookup + order placement,
                                 12-layer risk/signal filter stack

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
- **TTL caches** — VIX 120s, prior levels 1h, chart bars 30s
- **`stop_event.wait(timeout=N)`** — sessions interruptible within ~1s
- **caffeinate** — Mac sleep prevented while any session is active
- **VIX via yfinance** — Alpaca's free IEX feed doesn't support index symbols (`^VIX`)

## Session architecture (all-day, per-symbol)

Single **all-day session** per symbol (9:30–configurable end time ET). All 6 symbols can trade simultaneously; sessions are fully independent threads.

**Evaluator schedule inside `all_day_session()`**:
- 9:30–10:30 ET (opening phase): `evaluate_orb()` + `evaluate_gap_fade()`
- All day: `evaluate_vwap_momentum()` + `evaluate_gap_fade()` as fallback
- 11:30–13:30 ET: lunch-hour block (no new signals)
- Cool-down between entries: 5 min normally; **20 min after a stop hit**

**Socket events**:
| Event | Description |
|-------|-------------|
| `start_session {symbol}` | Start session for one symbol |
| `stop_session {symbol}` | Stop session for one symbol |
| `start_all_sessions` | Start sessions for all 6 symbols simultaneously |
| `stop_all_sessions` | Stop all running sessions |
| `set_session_end {session_end}` | Update end time (HH:MM ET) |

**Auto-scheduler** (in `app.py`):
- **9:30 ET** weekdays → starts all-day sessions for all symbols
- **15:35 ET** weekdays → triggers EOD learning review (one per day)

## Risk filter stack (order of checks, all in `all_day_session`)

Every signal that fires passes through these gates in sequence before an order is placed:

| # | Gate | Constant | Blocks when |
|---|------|----------|-------------|
| 1 | Cool-down | `300s` / `STOP_COOLDOWN_SEC=1200s` | < 5 min since last entry (20 min after stop) |
| 2 | Same-direction block | `STOP_COOLDOWN_SEC=1200s` | Last stop was same direction, within 20 min |
| 3 | HTF trend filter | `fetch_30min_trend()` | 30-min EMA9/21 trend opposes signal direction |
| 4 | IV rank gate | `IV_RANK_MAX=50`, `IV_RANK_WARN=35` | IVR > 50% (options too expensive) |
| 5 | Daily loss limit | `DAILY_LOSS_LIMIT_PCT=0.015` | Day P&L down ≥ 1.5% from open |
| 6 | Portfolio risk cap | `MAX_PORTFOLIO_RISK=0.03` | Total deployed premium ≥ 3% of account |
| 7 | Sector cap | `MAX_SECTOR_POSITIONS=2` | ≥ 2 open positions in same sector already |
| 8 | News veto | `news_filter.py` | Bad news headline at session start |
| 9 | Debate suppress | `DEBATE_MIN_CONFIDENCE=0.65` | LLM debate returns proceed=False or conf < 0.65 |

Gates 1–7 are in `spy_auto_trader.py`. Gate 8 runs in `app.py` before the session thread starts.

## Key constants (`spy_auto_trader.py`)

```python
# Risk
MAX_RISK_PCT         = 0.005   # 0.5% account per trade (sized on stop-based risk)
STOP_LOSS_PCT        = 0.50    # -50% option premium triggers stop
PROFIT_TARGET        = 0.75    # +75% → close remaining
MAX_PORTFOLIO_RISK   = 0.03    # 3% total deployed premium cap (enforced pre-entry)
DAILY_LOSS_LIMIT_PCT = 0.015   # 1.5% daily drawdown circuit-breaker
MAX_SECTOR_POSITIONS = 2       # max concurrent positions per sector

# Signals
MIN_VOL_RATIO        = 1.5     # volume must be 1.5× historical baseline
RSI_OVERBOUGHT       = 70
RSI_OVERSOLD         = 30
MIN_ORB_WIDTH        = 0.002   # 0.2% min opening range width

# Options
DTE_MIN              = 7       # minimum days to expiry
DTE_MAX              = 14      # maximum days to expiry
MAX_SPREAD           = 0.30    # max bid-ask spread ($)
MIN_OPTION_OI        = 100     # minimum open interest
DELTA_TARGET_MIN     = 0.40    # preferred delta range
DELTA_TARGET_MAX     = 0.65
IV_RANK_MAX          = 50      # IVR > 50% → skip entry
IV_RANK_WARN         = 35      # IVR 35–50% → log caution
IV_RANK_REFRESH_MIN  = 60      # re-fetch IV rank every 60 min in session

# Stop-hit behaviour
STOP_COOLDOWN_SEC    = 1200    # 20-min cooldown + direction block after stop hit

# Execution
POSITION_CLOSE_TIME  = (15, 50) # hard-close all option positions at 3:50 ET
FILL_TIMEOUT_MINS    = 3        # cancel unfilled order after 3 min
```

## Position sizing

`size_contracts(acct_val, mid_price)` — sizes on **stop-based risk**, not full premium:

```
risk_per_contract = mid_price × STOP_LOSS_PCT × 100
n = int((acct_val × MAX_RISK_PCT) / risk_per_contract)
```

A $100K account with `MAX_RISK_PCT=0.005` and `STOP_LOSS_PCT=0.50` risks $250 per contract at stop
(not $500 as it would be if sizing on full premium).

## Option selection (`find_atm_option`)

1. Filters contracts by OI ≥ `MIN_OPTION_OI` (falls back to full list with warning if all fail)
2. Scores remaining contracts by `|BS_delta − 0.50|` using **actual current IV** from `fetch_iv_rank` (not hardcoded 25%)
3. Picks the contract closest to 0.50 delta
4. Entry limit = `ask × 1.002` (not `mid + $0.02`) — ensures fill through the spread

## Session-start data fetches

Called once when `all_day_session()` begins, refreshed every `IV_RANK_REFRESH_MIN` minutes:

| Function | Returns | Used for |
|----------|---------|---------|
| `fetch_daily_ema200(symbol)` | scalar float | Broadcast into every intraday bar; macro trend filter |
| `fetch_iv_rank(symbol)` | `(current_iv, iv_rank)` | IV gate + delta scoring |
| `fetch_30min_trend(symbol)` | `"bull"/"bear"/"neutral"` | HTF trend filter |
| `fetch_futures_context()` | dict with ES/NQ bias | Logged; opposition warning if opposes signal |
| `fetch_market_breadth()` | dict with PCR + QQQ/IWM | Logged; opposition warning if opposes signal |
| `check_earnings_risk(symbol)` | `(risky, reason)` | Warning if earnings fall in DTE window |
| `fetch_historical_vol_baseline(symbol)` | dict by HH:MM | Patch NaN vol_ratio during opening phase |

**IV rank and 30-min trend are refreshed every 60 minutes** inside the session loop (IV can spike intraday on macro events).

## Stop-hit tracking (`_last_stop` registry)

When `check_positions()` detects a stop hit, it calls `record_stop_hit(symbol, direction)`.
`all_day_session()` reads `get_last_stop(symbol)` to:
1. Extend cool-down to 20 minutes (vs 5 min normally)
2. Block re-entry in the **same direction** for 20 minutes after the stop

## EOD learning review

At **15:35 ET** the scheduler triggers `_run_eod_review()` in `app.py`:
1. Parses today's `spy_trader.log` with regex patterns (signals fired, gates/vetoes, exits)
2. Calls `trader.eod_review(log_path, trades_snapshot)` in `spy_auto_trader.py`
3. If `ANTHROPIC_API_KEY` is set: sends structured stats to Claude Haiku for coaching insights + one concrete parameter suggestion
4. Falls back to plain stats summary when no API key
5. Streams result line-by-line to the dashboard log panel

`TradeMemory.update_outcome()` is now wired: the position monitor calls it for every full close (stop/T2/hard-close), storing P&L% and hold-time in ChromaDB for future similar-setup retrieval.

## Debugging all-day session not triggering signals

Common reasons a signal never fires (check log in order):

1. `HTF filter: 30-min trend=BEAR opposes BULL signal` — counter-trend blocked
2. `IV Rank gate: IVR=XX > 50%` — options overpriced
3. `⛔ Daily loss limit reached` — down ≥ 1.5% today
4. `Portfolio risk XX% >= max 3%` — too much open exposure
5. `Sector cap: X open tech positions` — sector concentration limit hit
6. `Same-direction block: last stop was BULL` — stop-hit direction lock
7. `Cool-down active (< 20 min since last entry)` — post-stop cooldown
8. `Debate suppressed signal` — LLM debate confidence too low
9. `News filter blocked` — bad-news veto
10. `vol_ratio < 1.5` — volume too light (check `vol_ratio` in bar log line)
11. `OR width too tight` — OR < 0.2% (gap fade still runs)
12. `Lunch-hour block` — 11:30–13:30 ET

## Sector map (`SECTOR_MAP`)

```python
SECTOR_MAP = {
    "SPY": "index", "QQQ": "index", "IWM": "index", "DIA": "index",
    "AMZN": "tech",  "GOOG": "tech",  "META": "tech",
    "MSFT": "tech",  "NVDA": "tech",  "AAPL": "tech",
}
```

When adding a new symbol, add it to `SECTOR_MAP` with the appropriate sector. Symbols not in the map use the symbol itself as the sector key (effectively no cap sharing).

## Coding patterns — always follow these

### State mutations
All reads/writes to `state`, `signal_history`, and `authenticated_sids` must be inside `with _state_lock:`. Use `_state_snapshot()` as the single source of truth for emitting state to clients.

### Interruptible waits
Use `stop_event.wait(timeout=N)` instead of `time.sleep(N)` inside session loops.

### Input validation
Every value arriving from the UI must pass through a `validate_*` function in `security.py` before touching `state` or module-level trader constants.

### Named constants
Add new tunables as module-level named constants, not magic numbers inline.

### New SocketIO event handlers
Decorate with `@require_auth` and call `emit_state()` at the end so the UI stays in sync.

## Common task playbooks

### Adding a new tradeable symbol (e.g. TSLA)

1. **`scripts/app.py`** — add `"TSLA"` to `VALID_SYMBOLS` frozenset AND `_SYMBOLS_ORDERED` list; add `_session_stop_events["TSLA"] = threading.Event()`.
2. **`scripts/spy_auto_trader.py`** — add `"TSLA": "tech"` (or correct sector) to `SECTOR_MAP`.
3. **`scripts/spy_auto_trader.py`** — verify `_strike_window()`: `max(5.0, price * 0.025)` is adaptive.
4. **`templates/index.html`** — add tab button with dot.
5. No other files need changing — the code is symbol-agnostic.

### Debugging "chart shows no data / 0 bars"

The fetch chain in `fetch_chart_bars()` tries: `iex → sip → None (SDK default) → yfinance`. Check the log for:
```
fetch_chart_bars(SPY, 1D): feed='iex' returned 0 bars ... trying next feed
fetch_chart_bars(SPY, 1D): Alpaca returned 0 bars — falling back to yfinance
```

### VIX troubleshooting

VIX is fetched via **yfinance** (`^VIX`). Alpaca's free IEX feed doesn't support index symbols — do NOT revert to the Alpaca path.

### News pre-filter (scripts/news_filter.py)

`check_news_sentiment(symbol, finnhub_key=None)` returns `(vetoed: bool, reason: str)`.
- Uses **Finnhub** if `FINNHUB_API_KEY` env var set; falls back to yfinance news
- HIGH-severity keywords → immediate veto; ≥3 MEDIUM-severity → veto
- Called in `_launch_session()` in `app.py` before the session thread starts

### ChromaDB trade memory (scripts/trade_memory.py)

`TradeMemory` wraps a ChromaDB PersistentClient at `~/.spy_trader/memory/`.
- `record()` called in `place_trade()` after order submit (uses `order.id` as trade_id)
- `update_outcome()` now called from position monitor on every full close (stop/T2/hard-close)
- `retrieve_similar()` called in `all_day_session()` before option lookup
- Custom `_IndicatorEmbedder` (pure numpy, 8-dim) — no onnxruntime needed

### Bull/Bear debate layer (scripts/debate.py)

`run_debate(symbol, direction, indicators, memory_context)` → `(proceed, confidence, summary)`.
- Bull → Bear → Judge, all Claude Haiku
- If `confidence < 0.65` or `proceed=False` → signal suppressed, wait 60s, re-evaluate
- Falls through as `(True, 1.0, "")` when `ANTHROPIC_API_KEY` not set

**Enabling**: set `ANTHROPIC_API_KEY=sk-ant-...` in `.env`, toggle "Bull/Bear LLM" pill in dashboard.

### Modifying trade parameters at runtime

Parameters are mirrored between `state` dict and module-level constants in `spy_auto_trader.py`. When adding a new tunable:
1. Add constant to `spy_auto_trader.py`
2. Add to `state` dict in `app.py`
3. Add to `_state_snapshot()`
4. Add `elif field == "my_param":` branch in `on_set_param()` with a validator
5. Add stepper widget in `templates/index.html`

### Investigating Alpaca auth / login failures

Login flow: `on_login()` → `validate_api_key()` + `validate_api_secret()` in `security.py` → `trader.init_clients()`. Check `scripts/security.log`.

### Troubleshooting WebSocket auth / state-sync

`authenticated_sids` is the authoritative WS auth store. If a client action is rejected with `login_required`:
- The SID was never added (login didn't complete) or was discarded on disconnect
- Check `scripts/security.log` for "Unauthenticated socket event from …"
