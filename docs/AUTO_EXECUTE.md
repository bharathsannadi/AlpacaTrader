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
 ├── _build_picks() → ONE merged KB-ranked pick list (data["picks"])
 └── _refresh_screener_bg() invokes both auto-exec lanes over the picks
                                              │
                                              ▼
                                each lane checks:
                                 1. auto_execute_options armed?
                                 2. market open?
                                 3. daily cap not hit (5/day)?
                                 4. <5 option positions already open?
                                 5. daily loss limit not breached?
                                 6. symbol not already executed today?
                                 │
                                 ▼
                            route == "options" → screener_executor.execute_screener_option
                            route == "stocks"  → stock order (_stock_qty_for)
                                 │
                                 ▼
                            Alpaca order(s) placed
```

### Merged picks — "shown == traded" (2026-06-04)

With `app.MERGED_PICKS_ENABLED = True`, the screener is ONE KB-ranked pick list
(`data["picks"]`, built by `app._build_picks`) that drives BOTH the UI display
and both auto-exec lanes. Each unique underlying collapses to ONE pick that is
ROUTED to **stock OR option** via `router.route_for_pick` (KB §5/§2) and trades
once via that route. The displayed `kb_match` % is the score of the *routed*
instrument — so the % shown is the % the executor gates on. Ranking is by
KB-match descending; the UI surfaces a **⭐ Picks** tab as the primary view (the
legacy Stocks/Options tabs remain). Flip the flag to `False` to restore the old
two-list behavior.

> `_build_picks` does a single `trader.account_value()` read (kept outside
> `_state_lock`). If that read returns 0 or errors, no RiskBrain is built and
> **every pick routes to `skip`** (`"no equity read — display only"`) — nothing
> trades that cycle. It self-heals on the next refresh.

The control surface in the browser is the **Auto-Execute** toggle in
**Settings → Automation** (default armed). `§9` liquidity now affects ranking:
`kb_principles.score_option_candidate` hard-floors a confirmed-illiquid contract
below the 60% KB gate (one-sided gate) so it never ranks or shows as a top BUY.

---

## Safety rails

All option-dollar caps were reconciled to "same as paper" on 2026-06-04.

| Rail | Default | Source |
|------|---------|--------|
| Option HARD ceiling per trade (incl. ETFs) | **$600** | `screener_executor.OPT_HARD_MAX_USD` / `OPT_HARD_MAX_USD_ETF` (was 1500 for ETFs) |
| Option per-trade risk cap | **$600** | `risk_brain.OPT_PER_TRADE_MAX_USD` (was 500) |
| Option rolling-week cap | **$3000** | `risk_brain.OPT_WEEK_MAX_USD` (was 1500) |
| Orders per calendar day | **5** | `app.py:MAX_AUTO_EXEC_PER_DAY` (was 3) |
| Concurrent option positions | **5** | `screener_executor.OPT_MAX_OPEN` (was 3) |
| Same symbol twice/day | blocked | `_auto_exec_today` set, persisted to `data/auto_exec_state.json` |
| Outside market hours | blocked | `screener._is_market_open()` |
| Server not authenticated | blocked | `state["logged_in"]` |
| Auto-exec disarmed | blocked | `state["auto_execute_options"]` (default armed) |
| Daily loss circuit breaker | -2% equity | `app.py:DAILY_LOSS_LIMIT_PCT` |
| Naked-leg rollback | on STO failure | `screener_executor.py` — cancels unfilled BTO or flattens with market sell |

### Equal-dollar position sizing (2026-06-04)

Supersedes fixed-10-shares / fixed-1-contract:

- **Options** are sized to as many contracts as fit ~$600:
  `qty = OPT_HARD_MAX_USD // per_contract_cost` in `execute_screener_option`
  (≥1 guaranteed — the HARD ceiling already blocks contracts that can't fit one).
- **Stocks** are sized to ~$5000/position via `app._stock_qty_for`
  (`STOCK_TARGET_USD = 5000`), in both auto-exec and manual execute.

### Option exits

Live option exits (`_manage_option_positions`): **+80% TP / −50% SL / 90-min
stall** (`OPT_TAKE_PROFIT_PCT` / `OPT_STOP_LOSS_PCT` / `OPT_STALL_MINUTES`).
`OPT_DYNAMIC_EXIT_ENABLED` (default OFF) swaps the flat −50% stop for
exit_engine's breakeven+trail ladder.

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

The most direct path: toggle **Auto-Execute** off in **Settings → Automation**
(it toggles `state["auto_execute_options"]`).

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
