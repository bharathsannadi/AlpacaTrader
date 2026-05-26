# Headless options auto-execution

The server can connect to Alpaca on boot and place options orders without any
browser interaction. This document explains what gets executed, what the safety
rails are, and how to turn it on/off.

> **Status:** paper-trading only. Live trading is not approved on any symbol.
> The auto-execute path respects `state["paper_mode"]` and `state["dry_run"]`.

---

## How it works

```
boot
 │
 ▼
_auto_login()             reads ALPACA_AUTO_* from .env, calls trader.init_clients()
 │
 ▼
state["logged_in"] = True
 │
 ▼
scheduler                 every 15s, during market hours:
 ├── refreshes screener_engine every 90s
 └── _refresh_screener_bg() invokes _auto_exec_options(data)
                                              │
                                              ▼
                                _auto_exec_options checks:
                                 1. auto_execute_options armed?
                                 2. market open?
                                 3. daily cap not hit?
                                 4. daily loss limit not breached?
                                 5. symbol not already executed today?
                                 │
                                 ▼
                            screener_executor.execute_screener_option(payload)
                                 │
                                 ▼
                            Alpaca limit order(s) placed
```

The control surface in the browser is the **⬛ Auto-Execute** button in the
screener topbar. Click it once to arm (turns 🔴 with `Armed (0/3 today)`).
Click again to disarm.

---

## Safety rails

| Rail | Default | Source |
|------|---------|--------|
| Per-trade max risk | $400 | `screener_executor.RISK_BUDGET` (KB §4) |
| Orders per calendar day | 3 | `app.py:MAX_AUTO_EXEC_PER_DAY` |
| Same symbol twice/day | blocked | `_auto_exec_today` set, persisted to `data/auto_exec_state.json` |
| Outside market hours | blocked | `screener._is_market_open()` |
| Server not authenticated | blocked | `state["logged_in"]` |
| Auto-exec disarmed | blocked | `state["auto_execute_options"]` (default `False`) |
| Daily loss circuit breaker | -2% equity | `app.py:DAILY_LOSS_LIMIT_PCT` |
| Naked-leg rollback | on STO failure | `screener_executor.py` — cancels unfilled BTO or flattens with market sell |

If the loss circuit breaker trips, the system **auto-disarms** auto-execute
for the rest of the day and emits a `⛔ HALTED` log message. You have to
explicitly re-arm tomorrow.

---

## Persistence

Symbols already executed today live in `data/auto_exec_state.json`:

```json
{"date":"2026-05-25","executed":["NVDA","AAPL"]}
```

This file is written atomically (temp-file rename) after every successful
execution. On startup, `_load_auto_exec_state()` rehydrates the in-memory
set if the date matches today. A mid-day restart cannot re-execute symbols
that already fired.

The `data/` directory is gitignored.

---

## Turning it off temporarily

The most direct path: click **🔴 Armed → ⬛ Auto-Execute** in the screener
topbar (it toggles `state["auto_execute_options"]`).

You can also kill the server entirely (`launchctl unload …`). Position
monitoring will stop when the process exits — open positions still need
manual management via the Alpaca dashboard until the server is back up.

---

## Turning it off permanently

Set `ALPACA_AUTO_PAPER=false-paper-disabled` (or any unrecognized value)
in `.env` and restart. The server will still boot, but `_auto_login` will
log a credential validation failure and skip the headless connect. Browser
login will still work.

---

## Adding your own safety rule

Add the check to `_auto_exec_options()` in `scripts/app.py` (search for
`# ── Circuit breaker:`). Keep the pattern:

```python
if your_check_fails():
    _emit_log("⛔ AUTO-EXEC HALTED — {reason}", level="WARNING")
    with _state_lock:
        state["auto_execute_options"] = False
    emit_state()
    return
```

Update this doc + the table above in the same commit.
