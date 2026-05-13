# Session Context — Pick Up Here

Quick-resume doc for Claude (and humans). Keep it current. Read this first; deep-dive into [ARCHITECTURE.md](ARCHITECTURE.md) or [TODO.md](TODO.md) as needed.

---

## 🧭 The 30-second handoff

- **Project:** SPY Auto Trader — Flask + SocketIO options day-trading bot. Paper mode.
- **Working directory:** `/Users/bsannadi/Desktop/AlpacaTrader`
- **Launch:** `nohup /Users/bsannadi/Desktop/AlpacaTrader/venv/bin/python3.11 /Users/bsannadi/Desktop/AlpacaTrader/scripts/app.py > /tmp/alpacatrader.log 2>&1 &` → http://localhost:5000
- ⚠️ **Use `python3.11`, not `python`** (the latter is 3.9 with missing deps)
- **Three reference docs in repo root:** [ARCHITECTURE.md](ARCHITECTURE.md) (system design), [TODO.md](TODO.md) (prioritized work), [CONTEXT.md](CONTEXT.md) (this file).

---

## 📌 Last session: 2026-05-12 (mid-market)

### What we did

1. **Launched the dashboard** — confirmed running on port 5000.
2. **Audited current state pre-trade** — gave expert read on timing/risk. System was using safe defaults (auto_trade off, news_filter on, debate disabled because `ANTHROPIC_API_KEY` missing).
3. **Investigated frozen dashboard header** — found root cause: `price_ticker` updated prices but never refreshed account/buying power. Only fills triggered a refresh.
4. **Shipped fix:** added `ACCOUNT_REFRESH_TICKS = 3` so account refreshes every ~15 s. Restarted app.
5. **Reviewed the one signal that fired today** — SPY 737P, May 19 expiry, 2x @ $5.75 at 10:15 ET (DRY RUN). Estimated ~+25-28% mid-session.
6. **Did a full code audit** — system is genuinely well-built. Identified 21 gaps, P0–P3, in [TODO.md](TODO.md).
7. **Wrote [ARCHITECTURE.md](ARCHITECTURE.md)** — high-level doc for reviewing with others.

### Pending decisions for end-of-day or next session

- [ ] Apply P0 fixes from [TODO.md](TODO.md) (#1–4: dry-run bugs)
- [ ] Pick top P1 fixes — recommendation: **#6 Friday/expiry-week gamma throttle**, **#7 correlation-adjusted delta cap**
- [ ] Set `ANTHROPIC_API_KEY` to enable debate gate + LLM EOD review
- [ ] Decide whether to flip `DRY_RUN = False` (real paper orders) or keep simulated for more data
- [ ] Score the SPY 737P hypothetical at EOD

---

## 🟢 What's running right now (verify before assuming)

- **App PID:** 3997 (restarted 18:31 CDT = 19:31 ET, 2026-05-12, post-market-close)
- **Now running on eventlet WSGI** (not Werkzeug dev server) — `_ASYNC_MODE = "eventlet"` in app.py with deprecation warning suppressed.
- Outlier-bar filter active ([spy_auto_trader.py:723](scripts/spy_auto_trader.py:723)) — drops yfinance pre/post-market data glitches.
- PID 11314 died earlier — root cause not investigated.
- **DRY_RUN: False** in code default. Real Alpaca paper orders will be sent on the next signal.
- **All P1+P2+P3 fixes shipped.** Log timestamps now in ET. Gates: FOMC blackout, gap-day delay, Friday gamma, weekly DD, portfolio delta, VIX RoC. Position management: trailing stop after T1. Observability: fees in P&L, slippage tracking, expanded EOD metrics, separate errors.log, webhook alerts.
- Verify with: `ps -p 4474 -o pid,stat,command` and `curl -s -o /dev/null -w "%{http_code}\n" http://localhost:5000/`
- If dead, relaunch with the command above
- **Log files:** `/tmp/alpacatrader.log` (stdout from current run) + `spy_trader.log` (file logger) + `security.log`

---

## ⚙️ Recent code changes (this session, uncommitted)

| File | Change |
|---|---|
| [scripts/app.py:44](scripts/app.py:44) | Added `ACCOUNT_REFRESH_TICKS = 3` constant |
| [scripts/app.py:445-465](scripts/app.py:445) | `price_ticker` now calls `refresh_account()` every 3rd tick |
| [scripts/spy_auto_trader.py:90](scripts/spy_auto_trader.py:90) | `DRY_RUN = False` (was True). User preference: paper-mode is already simulated, dry-run is redundant. |
| [scripts/spy_auto_trader.py:17](scripts/spy_auto_trader.py:17) | Updated module docstring to clarify PAPER_MODE vs DRY_RUN safety layers. |
| [scripts/spy_auto_trader.py:3129](scripts/spy_auto_trader.py:3129) | TimeInForce.IOC → DAY (Alpaca options reject IOC). Killed 1,313 ERROR/run spam. |
| [scripts/spy_auto_trader.py:278](scripts/spy_auto_trader.py:278) | Replaced basicConfig with explicit RotatingFileHandlers + ERROR-level errors.log + dedup filter. |
| [scripts/spy_auto_trader.py:2938](scripts/spy_auto_trader.py:2938) | `register_trade` accepts `is_dry_run` param; position dict carries it through restarts and close path. |
| [scripts/spy_auto_trader.py:2984](scripts/spy_auto_trader.py:2984) | New `_save_positions` / `_load_positions` to persist `_open_positions` to `~/.spy_trader/open_positions.json`. |
| [scripts/spy_auto_trader.py:3170](scripts/spy_auto_trader.py:3170) | `reconcile_positions` now loads persisted file first, then queries Alpaca for orphans. |
| [scripts/spy_auto_trader.py:3439](scripts/spy_auto_trader.py:3439) | Close branch checks `pos["is_dry_run"]` not global `DRY_RUN`. |
| [scripts/trade_memory.py:140](scripts/trade_memory.py:140) | `TradeMemory.record` accepts `is_dry_run`; `retrieve_similar` filters out dry-runs unless `include_dry_run=True`. |
| [scripts/app.py:180](scripts/app.py:180) | Removed duplicate basicConfig; security.log now uses RotatingFileHandler. |

No commits made. `git status` should show these two edits in one file.

---

## 🧠 Project gotchas to remember

- **Timezone:** log timestamps are in **system local time (CDT)**, but all trading logic uses **ET**. A log line at "09:15:00" actually happened at 10:15 ET. Don't misread timing of trades.
- **`ANTHROPIC_API_KEY` not set** in the environment → debate gate disabled and EOD review falls back to plain stats. Set this if you want either feature back.
- **AUTO-TRADE was enabled** today at 09:11. Will reset to False on next app restart.
- **Dry-run positions DO NOT survive an app restart** (gap #3 in [TODO.md](TODO.md)). The current hypothetical SPY 737P will vanish if the process dies.
- **`refresh_account()` does NOT auto-refresh on its own** without an authenticated client connected — gated by `should_run` flag including `streaming` + `authenticated_sids`. If header still looks stale, check you're logged in.

---

## 📁 Where to look in the codebase

| Need | Go here |
|---|---|
| Signal logic | [scripts/spy_auto_trader.py](scripts/spy_auto_trader.py) — `scheduler`/`generate_signal`/`opening_range` |
| Risk checks | [spy_auto_trader.py:1591–1750](scripts/spy_auto_trader.py:1591) — `size_contracts`, `daily_loss_check`, etc. |
| Option selection | [spy_auto_trader.py:1446](scripts/spy_auto_trader.py:1446) — `find_atm_option` |
| Position management | [spy_auto_trader.py:3148](scripts/spy_auto_trader.py:3148) — `check_positions` |
| Flask + SocketIO | [scripts/app.py](scripts/app.py) — handlers + background tasks |
| Tuning constants | [spy_auto_trader.py:90–155](scripts/spy_auto_trader.py:90) |
| Trade memory (ChromaDB) | [scripts/trade_memory.py](scripts/trade_memory.py) |
| Debate gate (LLM) | [scripts/debate.py](scripts/debate.py) |
| News filter | [scripts/news_filter.py](scripts/news_filter.py) |
| Auth / security | [scripts/security.py](scripts/security.py) |

---

## ✏️ Maintaining this file

When something meaningful happens (fix shipped, decision made, mode changed, key constant changed), update:
- "Last session" section with date + bullet of what happened
- "Pending decisions" — check off completed, add new
- "What's running" — PID, log location, current mode
- "Recent code changes" — drop edits once committed

Goal: a future-me reading this should reach the same situational awareness in 2 minutes that the prior session took an hour to build.
