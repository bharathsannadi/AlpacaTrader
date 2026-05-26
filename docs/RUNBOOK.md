# Runbook

Operational procedures for the running server. Pair with
[DEPLOYMENT.md](DEPLOYMENT.md) for first-time setup.

---

## Daily health check

```bash
curl -s http://localhost:5000/health | python3 -m json.tool
```

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
3. **Is auto-execute armed?** Open the dashboard → screener tab → button
   should say `🔴 Armed`. If it says `⬛ Auto-Execute`, click it.
4. **Is the market open?** Auto-execute only fires during market hours (9:30
   – 16:00 ET, weekdays).
5. **Did the daily cap hit?** Look for `Daily cap (3) reached` in the log.
6. **Did the loss circuit breaker trip?** Look for `⛔ AUTO-EXEC HALTED` in
   the log. If so, auto-execute is disarmed for the rest of the day — by
   design. Re-arm it tomorrow.
7. **Did `data/auto_exec_state.json` already record the symbol today?** Open
   the file and check. Each symbol can fire at most once per calendar day.

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
# Are both launchd agents loaded?
launchctl list | grep -E "alpacatrader|spy_auto_trader"

# What is the server PID right now?
pgrep -f "scripts/app.py"

# What's in today's dedup set?
cat data/auto_exec_state.json 2>/dev/null || echo "(empty)"

# How much equity did I start the day with?
grep "Day baseline equity" spy_trader.log | tail -1

# Full state snapshot (requires being logged in via browser first)
curl -sb "spy_session=$(cookie)" http://localhost:5000/api/status | python3 -m json.tool
```
