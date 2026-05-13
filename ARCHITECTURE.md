# SPY Auto Trader — Architecture & Design

A reviewer-friendly overview of what's in the codebase, how the pieces fit, and what trading logic actually runs. Pair this with [TODO.md](TODO.md) for known gaps.

---

## 1. What it does

A Flask + Socket.IO web dashboard that paper-trades **options** (calls/puts) on a watchlist (SPY, AMZN, GOOG, MSFT, NVDA, META) using two intraday strategies — **Opening Range Breakout (ORB)** and **VWAP Momentum** — through the [Alpaca](https://alpaca.markets) brokerage API. The system is fully self-contained: signal generation, risk checks, order routing, position monitoring, and end-of-day learning review all live in one process.

**Default mode:** paper-trading (no real money). DRY_RUN can be layered on top so even paper orders are simulated.

---

## 2. High-level architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Browser (templates/, static/)                                  │
│  Socket.IO ↔ dashboard: login, toggles, charts, trade approval  │
└──────────────────────────────▲──────────────────────────────────┘
                               │ WebSocket
┌──────────────────────────────┴──────────────────────────────────┐
│  app.py  — Flask + Socket.IO server                             │
│  • Auth (session login), rate limits, CSRF/headers (security.py)│
│  • State machine (sessions, toggles, _open_positions ref)       │
│  • Background tasks: price_ticker, scheduler, position_monitor  │
│  • Approval callback wired into trader (manual or auto-trade)   │
└──────┬─────────────────────┬────────────────────────┬───────────┘
       │                     │                        │
       ▼                     ▼                        ▼
┌──────────────┐    ┌────────────────────┐    ┌──────────────────┐
│ news_filter  │    │  spy_auto_trader   │    │     debate       │
│ (Finnhub +   │    │  (the engine —     │    │  (Claude Haiku   │
│  yfinance,   │    │   ~3500 LOC, all   │    │   bull/bear      │
│  veto on bad │    │   trading logic)   │    │   confirmation)  │
│  headlines)  │    └─────────┬──────────┘    └──────────────────┘
└──────────────┘              │
                              ▼
                    ┌──────────────────┐         ┌──────────────────┐
                    │  Alpaca API      │         │  trade_memory    │
                    │  (bars, quotes,  │◀────────│  (ChromaDB —     │
                    │   options chain, │         │   retrieve       │
                    │   orders)        │         │   similar past   │
                    └──────────────────┘         │   trades + score)│
                                                 └──────────────────┘
```

---

## 3. Modules

| File | Lines | Role |
|---|---|---|
| [scripts/app.py](scripts/app.py) | 1070 | Flask + Socket.IO server. Auth, dashboard, sessions, background tasks. Thin layer over `spy_auto_trader`. |
| [scripts/spy_auto_trader.py](scripts/spy_auto_trader.py) | 3533 | **The engine.** All signal logic, risk checks, order execution, position management. |
| [scripts/news_filter.py](scripts/news_filter.py) | 172 | Headline sentiment veto. Finnhub primary, yfinance fallback. Cached. |
| [scripts/debate.py](scripts/debate.py) | 166 | LLM bull/bear debate gate. Runs Claude Haiku 4.5 as bull, bear, and judge agents. |
| [scripts/trade_memory.py](scripts/trade_memory.py) | 261 | ChromaDB vector store of past trades + outcomes. Embeds indicator state; retrieves similar setups. |
| [scripts/security.py](scripts/security.py) | 203 | Login lockout, key validation, secret-key persistence, security headers. |
| [scripts/analyze_session.py](scripts/analyze_session.py) | 176 | Standalone post-session log analyzer (CLI utility). |
| `templates/`, `static/` | — | Dashboard UI (Chart.js, vanilla JS, Socket.IO client). |

---

## 4. Trading strategy

### 4a. Two signal types

**ORB (Opening Range Breakout)** — active 9:30–10:00 ET
- Compute the high/low of the first 30 minutes of the session.
- **Bull:** close breaks above ORB high + above VWAP + EMA9 > EMA21 + MACD > 0 + volume ≥ 1.5× baseline.
- **Bear:** close breaks below ORB low + below EMA200d + same volume/MACD conditions.

**VWAP Momentum** — active mid-day and afternoon
- **Bull:** price above VWAP, ≥ 50% of recent bars above VWAP, EMA9 > EMA21, MACD > 0, volume ≥ 1.0× baseline, closing up.
- **Bear:** mirror of bull.

Both strategies share the same option selection, risk sizing, and exit rules.

### 4b. Option selection (`find_atm_option` at [spy_auto_trader.py:1446](scripts/spy_auto_trader.py:1446))

- DTE window: **7–14 days**
- Strike: ATM ± a small window scaled to underlying price
- Liquidity floor: OI ≥ 500 (ETFs) / ≥ 200 (single stocks), volume ≥ 10 today
- Spread filter: ≤ 5% of mid (or absolute $0.05 floor)
- Delta target: 0.40–0.65 (uses Black-Scholes approximation, [`bs_delta`](scripts/spy_auto_trader.py:237))
- **IV Rank filter:** skip entry if 52-week IVR > 70% (overpriced premium)

### 4c. Entry execution (`place_order` flow)

1. Submit at **mid** as a limit order (10 s to fill).
2. If not filled → cancel + resubmit at **walk_limit** (ask × 1.002).
3. Both orders share a base `client_order_id` for broker-side dedup.
4. On fill → register position with stop/T1/T2 + record to ChromaDB.

### 4d. Position management (`check_positions` at [spy_auto_trader.py:3148](scripts/spy_auto_trader.py:3148))

Background `position_monitor` task evaluates every **10 seconds**:

| Trigger | Action |
|---|---|
| Bid ≤ stop_price for 2 consecutive cycles | Full close at ask |
| Up +30% from entry | Move stop to entry price (breakeven ratchet) |
| Up +50% | Close 25% (partial profit) — flag T1 done |
| Up +100% | Close remainder (T2) |
| Time stop: 60 min in [-15%, +10%] | Close — stalled trade |
| 15:50 ET | Hard-close all positions |

Stop trigger uses **bid** (worst case fill), targets use **mid** (fair value).

---

## 5. Risk controls (the whole stack)

Every entry passes through this gauntlet. Failing any one → no trade.

| # | Check | Where |
|---|---|---|
| 1 | News headline sentiment | [news_filter.py](scripts/news_filter.py) |
| 2 | Earnings inside DTE window | [check_earnings_risk](scripts/spy_auto_trader.py:650) |
| 3 | IV Rank ≤ 70% | [fetch_iv_rank](scripts/spy_auto_trader.py:1099) |
| 4 | VIX absolute ≤ 30 | [vix_check](scripts/spy_auto_trader.py:1653) |
| 5 | Not in lunch hour (11:30–13:30 ET) | [is_lunch_hour](scripts/spy_auto_trader.py:1613) |
| 6 | Not in chop regime (1H ATR < 0.5× 5-day avg) | [is_chop_regime](scripts/spy_auto_trader.py:1215) |
| 7 | Sector cap (max 2 open per sector) | [sector_risk_check](scripts/spy_auto_trader.py:1628) |
| 8 | PDT counter (paper-account quirk) | [pdt_check](scripts/spy_auto_trader.py:1645) |
| 9 | Daily loss halt at −1.5% from open equity | [daily_loss_check](scripts/spy_auto_trader.py:1685) |
| 10 | Daily profit lock at +2% from open equity | [daily_profit_check](scripts/spy_auto_trader.py:1710) |
| 11 | Portfolio risk cap (3% total deployed) | [deployed_risk_pct](scripts/spy_auto_trader.py) |
| 12 | Per-trade risk sizing at 0.5% of equity | [size_contracts](scripts/spy_auto_trader.py:1591) |
| 13 | Global cooldown: ≥ 60 s between any two entries | [global_cooldown_ok](scripts/spy_auto_trader.py:1741) |
| 14 | Whipsaw cooldown: 15 min before opposite-direction signal | (same area) |
| 15 | Max 8 entries per day | (same area) |
| 16 | No new entries after 14:00 ET | (same area) |
| 17 | Spread filter (≤ 5% of mid) | [spread_acceptable](scripts/spy_auto_trader.py:1554) |
| 18 | LLM bull/bear debate (optional, if API key set) | [debate.py](scripts/debate.py) |
| 19 | Manual approval (unless AUTO-TRADE on) | [app.py callback](scripts/app.py) |

---

## 6. Data flow — anatomy of a trade

```
[scheduler]                 every 60s during session window
    │
    ▼
fetch_bars(symbol) ──────► add_indicators (EMA, VWAP, RSI, MACD, ATR)
    │
    ▼
detect signal (ORB or VWAP momentum)
    │  pass → continue, fail → log "no-fire" with reasons
    ▼
news_filter.check_news_sentiment   ──── fail → veto
earnings / IV rank / VIX / regime  ──── fail → skip
    │
    ▼
find_atm_option(direction, expiry) ──► liquidity, spread, delta filters
    │
    ▼
trade_memory.retrieve_similar       (informs debate prompt)
    │
    ▼
debate.run_debate (if enabled)      ──── judge says no → skip
    │
    ▼
size_contracts (acct × 0.5% / stop_distance)
    │
    ▼
[approval]   AUTO-TRADE on?  ──► immediate
             AUTO-TRADE off? ──► UI modal → user clicks Allow/Skip
    │
    ▼
DRY_RUN?  ──► register simulated position, log [DRY RUN]
NOT DRY?  ──► submit at mid (10s) → walk to ask if unfilled
    │
    ▼
register_trade(occ, entry, qty, direction, symbol, order_id)
    │       └─► _open_positions[]   (in-memory list)
    │       └─► TRADE_MEMORY.record (ChromaDB)
    ▼
position_monitor (every 10s) ──► stop / T1 / T2 / breakeven / time stop / hard close
    │
    ▼
on close: update_outcome to ChromaDB + emit close event to UI + refresh account
```

---

## 7. Key tunable parameters (top of [spy_auto_trader.py](scripts/spy_auto_trader.py))

| Constant | Default | Meaning |
|---|---|---|
| `MAX_RISK_PCT` | 0.5% | Per-trade risk as fraction of account |
| `MAX_PORTFOLIO_RISK` | 3% | Total deployed risk ceiling |
| `DAILY_LOSS_LIMIT_PCT` | 1.5% | Circuit breaker (halt new entries) |
| `DAILY_PROFIT_LOCK_PCT` | 2% | Profit lock (halt new entries when up X%) |
| `STOP_LOSS_PCT` | 40% | Stop = entry × (1 − this) |
| `PROFIT_TARGET` | 100% | T2 = entry × 2 |
| `PARTIAL_TRIGGER_PCT` | 50% | T1 fires here |
| `PARTIAL_QTY_FRAC` | 25% | Fraction closed at T1 |
| `BREAKEVEN_TRIGGER_PCT` | 30% | Where stop ratchets to entry |
| `DTE_MIN` / `DTE_MAX` | 7 / 14 | Days-to-expiry window |
| `IV_RANK_MAX` | 70 | Skip entries above this IVR |
| `VIX_MAX` | 30 | Skip if VIX absolute above this |
| `DELTA_TARGET_MIN/MAX` | 0.40 / 0.65 | Preferred option delta band |
| `MAX_DAILY_ENTRIES` | 8 | Hard cap on entries per day |
| `LAST_ENTRY_HOUR` | 14:00 ET | Cutoff for new entries |
| `MIN_OPTION_OI_ETF/STOCK` | 500 / 200 | Liquidity floor |
| `MAX_SPREAD_PCT` | 5% | Spread filter |
| `GLOBAL_COOLDOWN_SEC` | 60 s | Min gap between any two entries |
| `WHIPSAW_COOLDOWN_SEC` | 900 s | Min wait before opposite signal |

---

## 8. Concurrency model

- **Single Python process.** Flask served via `socketio.run` (Werkzeug dev server). Not production-grade WSGI.
- Three background tasks via `socketio.start_background_task`:
  - `price_ticker` — every 5 s: refresh prices, refresh account every 3rd tick (~15 s)
  - `position_monitor` — every 10 s: evaluate open positions
  - `scheduler` — every 60 s: per-symbol signal evaluation
- Per-symbol session threads spawned via the Stop events `STOP_MORNING` / `STOP_EVENING`.
- Thread safety:
  - `_state_lock` (Flask state dict)
  - `_positions_lock` (open positions list)
  - `_equity_lock` (day-start equity + halt flags)
  - `_freshness_lock` (stale-data tracker)

---

## 9. State & persistence

| What | Where | Persisted? |
|---|---|---|
| Open positions | `_open_positions` (in-memory) | ❌ — re-derived from Alpaca on restart via `reconcile_positions` (real only, dry-runs lost) |
| Trade memory (past trades + outcomes) | ChromaDB on disk (`~/.spy_trader/memory`) | ✅ |
| Login session | Flask session cookie | ✅ (until expiry) |
| Day-start equity / halt flags | Module globals | ❌ — resets on restart |
| Logs | `spy_trader.log`, `security.log` (current dir) | ✅ (no rotation) |
| API keys | Provided via UI on login or `.env` | `.env` only if used |

---

## 10. Modes (the safety matrix)

| `PAPER_MODE` | `DRY_RUN` | `auto_trade` | Effect |
|:---:|:---:|:---:|---|
| True | True | False | Simulated orders, manual approval. **Safest learning mode.** |
| True | True | True | Simulated orders, auto-approved. Backtest-like. |
| True | False | False | Real paper orders at Alpaca, manual approval. |
| True | False | True | Real paper orders, auto-approved. **Default after testing.** |
| False | False | True | **REAL MONEY, AUTO-PLACED.** Require explicit operator intent. |

---

## 11. Observability

- **Dashboard:** live equity, buying power, deployed risk %, open positions table, signal feed, chart, trade log.
- **EOD Review:** auto-runs after `EVENING_END`. Parses today's log + closed trades, computes win/loss stats, calls Claude Haiku for "what worked / what didn't / one parameter to tune" (falls back to plain stats if no API key).
- **Logs:** `spy_trader.log` (engine + Flask), `security.log` (auth events).

---

## 12. What's NOT in the system (known gaps)

See [TODO.md](TODO.md) for the full prioritized list. Highlights:
- No FOMC/CPI macro-event blackout (earnings only)
- No Friday/expiry-week gamma throttle
- No trailing stop after T1 partial (static T2 only)
- No correlation-adjusted portfolio delta cap
- Commissions/fees not in P&L calc
- No log rotation, no auto-restart supervision, no kill switch
- Dry-run positions not persisted across restart

---

## 13. Glossary (for non-trader reviewers)

- **OCC symbol** — the standard option ticker format, e.g. `SPY260519P00737000` = SPY put, May 19 2026 expiry, strike $737.000.
- **ORB** — Opening Range Breakout. Trade the first breakout after the first N minutes' high/low form.
- **VWAP** — Volume-Weighted Average Price. Intraday benchmark; institutional algos anchor to it.
- **IV Rank** — current implied volatility's percentile over the past 52 weeks. High IVR = options expensive.
- **DTE** — Days To Expiry.
- **Delta** — option's price sensitivity to a $1 move in the underlying. Calls 0→1, puts -1→0.
- **Theta** — daily time-decay of an option's price. Accelerates near expiry.
- **Gamma** — rate of change of delta. Explodes in the last week to expiry → small underlying moves swing option price violently.
- **Vega** — option price sensitivity to a 1-vol-point change in IV.
- **PDT** — Pattern Day Trader rule. 4+ day-trades in 5 days in a sub-$25K margin account triggers restrictions.
- **0DTE / 7DTE** — options expiring today / in 7 days.
- **Whipsaw** — quick reversal that fakes out a breakout.
