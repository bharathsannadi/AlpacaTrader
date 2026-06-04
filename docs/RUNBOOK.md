# Runbook

Operational procedures for the running server. Pair with
[DEPLOYMENT.md](DEPLOYMENT.md) for first-time setup.

---

## Daily health check

```bash
curl -s http://localhost:5000/health | python3 -m json.tool   # main app
curl -s http://localhost:5001/health | python3 -m json.tool   # charts server
```

There are now **two ports**: `:5000` is the main trading app, `:5001` is the
standalone charts-only server (`charts_server.py`, yfinance, no Alpaca login).
The watchdog monitors both.

| Field | Healthy | Meaning |
|-------|---------|---------|
| `status` | `"ok"` | All critical loops have ticked recently |
| `logged_in` | `true` | `_auto_login` succeeded — server can place orders |
| `paper_mode` | `true` | Hitting the paper account, not live |
| `position_monitor_age_s` | < 60 | Last heartbeat was within 6× the 10s monitor interval |
| `price_ticker_age_s` | < 30 | Prices refreshing |
| `scheduler_age_s` | < 30 | Scheduler awake |

`status: "degraded"` returns HTTP 200 (won't trip the watchdog). HTTP 503 only
fires when `position_monitor` is stale AND has ticked at least once — i.e. it
actually hung. The watchdog kills on 3 consecutive 503s or connection timeouts.

---

## "The server isn't trading — why?"

Walk this list:

1. **Is the server alive?** `launchctl list | grep alpacatrader` — should show
   a PID and last exit code 0.
2. **Did auto-login succeed?** `curl -s http://localhost:5000/health` —
   `logged_in` must be `true`. If `false`, check `.env` credentials and the
   tail of `spy_trader.log` for `[auto-login]` lines.
3. **Is auto-execute armed?** Open the dashboard → Settings → Automation →
   Auto-Execute should be armed (default ON). The ⭐ Picks tab is the primary
   view — picks are "shown == traded".
4. **Is the market open?** Auto-execute only fires during market hours (9:30
   – 16:00 ET, weekdays).
5. **Did the daily cap hit?** Look for `Daily cap (5 filled) reached` in the
   log (`MAX_AUTO_EXEC_PER_DAY = 5`, was 3).
6. **Are 5 option positions already open?** `OPT_MAX_OPEN = 5` blocks new
   option entries; look for `max 5 option positions` in the log.
7. **Did the loss circuit breaker trip?** Look for `⛔ AUTO-EXEC HALTED` in
   the log. If so, auto-execute is disarmed for the rest of the day — by
   design. Re-arm it tomorrow.
8. **Did `data/auto_exec_state.json` already record the symbol today?** Open
   the file and check. Each symbol can fire at most once per calendar day.
9. **Did a transient equity read route ALL picks to skip?** `_build_picks`
   does a single `trader.account_value()` read; if it returns 0/errors, the
   RiskBrain isn't built and **every pick routes to `skip`** with reason
   `"no equity read — display only"`. Nothing trades that cycle. It self-heals
   on the next refresh once the equity read succeeds — only investigate if it
   persists (check `spy_trader.log` for repeated skip-all cycles).

---

## Caps, sizing, and exits (current values, 2026-06-04)

All reconciled to "same as paper". Verify against the named constants if in doubt.

| What | Value | Constant |
|------|-------|----------|
| Options HARD ceiling per trade (incl. ETFs) | **$600** | `screener_executor.OPT_HARD_MAX_USD` / `OPT_HARD_MAX_USD_ETF` |
| Options per-trade risk cap | **$600** | `risk_brain.OPT_PER_TRADE_MAX_USD` |
| Options rolling-week cap | **$3000** | `risk_brain.OPT_WEEK_MAX_USD` |
| Orders per calendar day | **5** | `app.MAX_AUTO_EXEC_PER_DAY` |
| Concurrent option positions | **5** | `screener_executor.OPT_MAX_OPEN` |
| Stock position size | **~$5000** | `app.STOCK_TARGET_USD` (`_stock_qty_for`) |
| Option position size | as many contracts as fit ~$600 | `qty = OPT_HARD_MAX_USD // per_contract` in `execute_screener_option` |

**Equal-dollar sizing** supersedes fixed-10-shares / fixed-1-contract: stocks
deploy ~$5000 each, options buy as many contracts as fit ~$600.

**Option exits** (`_manage_option_positions`): **+80% TP / −50% SL / 90-min
stall** (`OPT_TAKE_PROFIT_PCT=0.80`, `OPT_STOP_LOSS_PCT=0.50`,
`OPT_STALL_MINUTES=90`). If `screener_executor.OPT_DYNAMIC_EXIT_ENABLED` is
turned on (default OFF), the stop uses exit_engine's breakeven+trail ladder
instead of the flat −50%.

---

## Restarting the server

```bash
launchctl unload ~/Library/LaunchAgents/com.alpacatrader.plist
launchctl load   ~/Library/LaunchAgents/com.alpacatrader.plist
sleep 12   # _auto_login needs ~3s + Alpaca API latency
curl -s http://localhost:5000/health
```

If `logged_in: false` after 15 seconds, check `spy_trader.log` for the
`[auto-login]` lines — likely a bad credential in `.env` or Alpaca outage.

To restart the charts server: `launchctl unload`/`load`
`~/Library/LaunchAgents/com.alpacatrader.charts.plist`, then
`curl -s http://localhost:5001/health`.

### The watchdog / auto-restart

`com.spy_auto_trader.watchdog` runs `scripts/watchdog.sh` every 60s and checks
BOTH `:5000` and `:5001` via `check_service`. Three consecutive failed `/health`
checks → it kills the offending process → launchd (KeepAlive) relaunches it.
Together with `com.alpacatrader.caffeinate` (stops idle sleep, which previously
froze stop-loss monitoring) and each agent's KeepAlive + RunAtLoad, the stack
survives crash, hang, sleep, and reboot. Watch its decisions:
`tail -f /tmp/alpacatrader.watchdog.log`.

---

## Force-disarming auto-execute from CLI

If the browser is unreachable and you need to stop auto-execute fast:

```bash
# Fastest: kill the whole process. launchd restarts it without auto-execute
# re-armed (it defaults to false on boot).
launchctl unload ~/Library/LaunchAgents/com.alpacatrader.plist
```

Or edit `data/auto_exec_state.json` to add every symbol you don't want to fire:

```json
{"date":"2026-05-25","executed":["SPY","AAPL","NVDA","TSLA",...all 25...]}
```

This hits the per-symbol dedup but won't disarm globally — restart-safe but
ugly.

---

## Clearing today's auto-execute dedup

Don't normally need this. If you do (testing, the system fired on a symbol
you wanted to retry):

```bash
rm /Users/bsannadi/Desktop/bharath/AlpacaTrader/data/auto_exec_state.json
# next screener refresh re-initializes the dedup set as empty
```

---

## Reading the log

```bash
# Live tail
tail -f spy_trader.log

# Look for auto-execute events
grep "auto-exec" spy_trader.log | tail -30

# Closed trades (Notes/Closed-Trades panel retired — closes now show in the Log)
grep -E "CLOSED|OPTION EXIT" spy_trader.log | tail -30

# Recent errors only
tail -200 errors.log

# Watchdog kill decisions
tail -50 /tmp/alpacatrader.watchdog.log
```

---

## Common failure modes

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `logged_in: false` after 15s | Bad ALPACA_AUTO_KEY/SECRET in `.env` | Regenerate from Alpaca dashboard, update `.env`, restart |
| `status: degraded` for > 1 minute | `position_monitor` blocked on slow Alpaca call | Restart server |
| Browser shows login modal but `health` says `logged_in: true` | Per-tab auth — modal is expected; type your creds | (working as designed) |
| Watchdog repeatedly killing app | `/health` timing out | Check `top` for runaway CPU; investigate `spy_trader.log` for the slow path |
| Order says `success: false … rollback FAILED` | STO leg failed AND rollback failed | **CHECK ALPACA DASHBOARD IMMEDIATELY** — may have a naked long position |
| `[auto-exec] equity check failed` | `trader.account_value()` Alpaca call errored | Usually transient; investigate if persistent |

---

## Useful one-liners

```bash
# Are all five launchd agents loaded? (app, charts, caffeinate, polygon, watchdog)
launchctl list | grep -E "alpacatrader|spy_auto_trader"

# What are the server PIDs right now? (app + charts)
pgrep -f "scripts/app.py"
pgrep -f "scripts/charts_server.py"

# What's in today's dedup set?
cat data/auto_exec_state.json 2>/dev/null || echo "(empty)"

# How much equity did I start the day with?
grep "Day baseline equity" spy_trader.log | tail -1

# Full state snapshot (requires being logged in via browser first)
curl -sb "spy_session=$(cookie)" http://localhost:5000/api/status | python3 -m json.tool
```
