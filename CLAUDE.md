# CLAUDE.md — Project guidance for Claude Code agents

This file is read by Claude Code at the start of every session. Keep it short,
keep it true, keep it actionable. If you change build/run/test commands, update
this file in the same commit.

---

## What this project is

A Flask + Socket.IO web dashboard that paper-trades options through the Alpaca
API. The codebase began as an intraday options bot (ORB + VWAP momentum on 6
symbols); after rigorous backtesting **no validated edge was found** for that
strategy. The system is currently a research/advisory apparatus with a
**screener-driven options auto-execution** path added on top.

Default mode: **paper trading**. Real-money trading is gated behind explicit
flag flips (`paper=false` in `.env`) and is not approved on any symbol today.

For deep context see [`README.md`](README.md), [`ARCHITECTURE.md`](ARCHITECTURE.md),
[`CONTEXT.md`](CONTEXT.md), [`TODO.md`](TODO.md).

---

## Running the app

The server runs under launchd as the agent `com.alpacatrader` and auto-starts
on login. To start/stop manually:

```bash
# Stop
launchctl unload ~/Library/LaunchAgents/com.alpacatrader.plist

# Start
launchctl load ~/Library/LaunchAgents/com.alpacatrader.plist

# Check status (PID, exit code)
launchctl list | grep alpacatrader

# Verify health (includes logged_in flag)
curl -s http://localhost:5000/health
```

A separate watchdog (`com.spy_auto_trader.watchdog`) monitors `/health` and
kills the app if 3 consecutive checks fail, letting launchd restart it.

**Direct run (debugging only — bypasses launchd):**

```bash
PYTHONPATH=venv/lib/python3.11/site-packages \
  /usr/local/Cellar/python@3.11/3.11.15_1/Frameworks/Python.framework/Versions/3.11/bin/python3.11 \
  scripts/app.py --paper
```

The venv Python path + `PYTHONPATH` is **required** — plain `python3` won't find
the dependencies because Homebrew Python and the venv site-packages are split.

---

## How to test

```bash
# Install dev dependencies (one-time)
pip install -r requirements-dev.txt

# Run the full suite
PYTHONPATH=venv/lib/python3.11/site-packages \
  /usr/local/Cellar/python@3.11/3.11.15_1/Frameworks/Python.framework/Versions/3.11/bin/python3.11 \
  -m pytest tests/ -v

# Or with the venv activated:
source venv/bin/activate
pytest tests/ -v
```

The suite is hermetic — no network calls, no Alpaca, no real order placement.
It covers `security.py` validators + lockout, `screener_executor` fill
verification + risk constants, and the auto-exec dedup persistence layer. See
[`tests/README.md`](tests/README.md) for what's covered and what's still
manual-only. Whole suite should finish in under 25 seconds.

**Manual smoke checks** (post-deploy or post-restart):

```bash
# Server health (includes logged_in flag)
curl -s http://localhost:5000/health

# Module imports (catches syntax errors before reload)
PYTHONPATH=venv/lib/python3.11/site-packages \
  /usr/local/Cellar/python@3.11/3.11.15_1/Frameworks/Python.framework/Versions/3.11/bin/python3.11 \
  -c "import sys; sys.path.insert(0,'scripts'); import app; print('OK')"
```

---

## Credentials & secrets

- `.env` lives at project root, `chmod 600`, never committed (gitignored)
- See `.env.example` for the documented template
- `ALPACA_AUTO_KEY` / `ALPACA_AUTO_SECRET` — used by `_auto_login` to connect
  at server startup so the app trades headless
- `ALPACA_API_KEY` / `ALPACA_API_SECRET` — used by `screener_executor` for
  manual + auto-execution of options orders
- All three are typically the same paper-trading key pair; the duplication is
  a known smell tracked in the todo list

---

## Architecture in one paragraph

A single Flask + SocketIO process. `scripts/app.py` is the entry point and
wires together: `spy_auto_trader` (data fetch, indicators, signal generation,
order placement, position monitoring), `daily_trader` (Connors RSI(2) daily
strategy), `screener_engine` (multi-strategy live screener), `screener_executor`
(options order placement from screener picks), `news_filter`, `debate` (LLM
bull/bear gate), `trade_memory` (ChromaDB recall), `security` (validators,
headers, login lockout). Three background tasks run on boot: `price_ticker`
(5s), `scheduler` (15s, fires session start, EOD, screener refresh), and
`position_monitor` (10s, stop-loss/target execution). A fourth, `_auto_login`,
runs once after a 3s sleep to connect to Alpaca from `.env`.

For a fuller diagram see [`ARCHITECTURE.md`](ARCHITECTURE.md). For the new
headless auto-execution path see [`docs/AUTO_EXECUTE.md`](docs/AUTO_EXECUTE.md).

---

## Gotchas — things that have bitten past engineers

- **`_state_snapshot` lock contention**: trader I/O calls (`open_positions_snapshot`,
  `equity_curve_snapshot`, etc.) must run OUTSIDE `_state_lock`. Holding the
  lock across slow I/O blocks `price_ticker` and `position_monitor`.
- **`position_monitor` must NOT gate on `authenticated_sids`**. Open positions
  need stop-loss execution regardless of whether any browser tab is open. It
  gates only on `state["logged_in"]`.
- **`socket.io` client uses `io()` with no options** — `secure` is derived
  from the page protocol automatically. Passing `{secure:true,...}` does
  nothing in the browser and confuses connection state.
- **eventlet is the async mode** and the deprecation warning is acknowledged.
  Long-term migration: gevent or ASGI (FastAPI + python-socketio async).
- **`SocketIOHandler` broadcasts every log record to all connected clients.**
  Be careful what you log — API key prefixes and stack traces will hit the
  browser. Tracked as a todo item.
- **The watchdog (`com.spy_auto_trader.watchdog`) will kill the app after 3
  failed `/health` checks.** During long-running operations make sure
  `_beat("position_monitor")` and `_beat("scheduler")` are called inside any
  inner loops, not just at the top of the outer loop.

---

## Coding conventions

- **Python**: PEP 8, 4-space indent, type hints on public functions, f-strings
  for formatting, `log.info/warning/error` (never `print`).
- **JS**: 2-space indent, single-file `static/main.js` (modularization is a
  todo item), event-handler functions prefixed by feature (`scr*`, `bt*`).
- **HTML/CSS**: Single template + inline `<style>` block; classes prefixed
  by feature (`.bt-*` for backtest, `.scr-*` for screener).
- **Commits**: Conventional Commits style (`feat:`, `fix:`, `chore:`, etc.).
  Always include `Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>`
  when Claude wrote the change.

---

## Safety rails for trading code

When touching anything that places orders:

1. Default `dry_run=True` for new paths
2. Honor `state["paper_mode"]` — never hard-code `paper=False`
3. Cap risk per trade (`RISK_BUDGET = $400`, KB §4)
4. Cap orders per day (`MAX_AUTO_EXEC_PER_DAY = 3` for headless mode)
5. Persist any dedup / order-tracking state to disk (see `data/auto_exec_state.json`)
6. Provide a circuit breaker (see `DAILY_LOSS_LIMIT_PCT = 2.0`)
7. Roll back partial fills — never leave a naked leg (see
   `screener_executor.py` STO failure path)

If you can't honor all seven, ship behind a feature flag that defaults to off.
