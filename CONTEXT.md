# Session Context — Pick Up Here

Quick-resume doc for Claude (and humans). Keep it current. Read this first; deep-dive into [ARCHITECTURE.md](ARCHITECTURE.md) or [TODO.md](TODO.md) as needed.

---

## 🧭 The 30-second handoff

- **Project:** SPY Auto Trader — Flask + SocketIO options day-trading bot. Paper mode.
- **Working directory:** `/Users/bsannadi/Desktop/AlpacaTrader`
- **Preferred launch:** `open "/Applications/SPY Auto Trader.app"` (native macOS app — gradient bar-chart icon)
- **CLI fallback:** `nohup /Users/bsannadi/Desktop/AlpacaTrader/venv/bin/python3.11 /Users/bsannadi/Desktop/AlpacaTrader/scripts/app.py > /dev/null 2>&1 &` → http://localhost:5000
- ⚠️ **Use `python3.11`, not `python`** (the latter is 3.9 with missing deps)
- ⚠️ **Redirect stdout to `/dev/null`** when launching — the FileHandler already writes to `auto_trader.log`. Capturing stdout into the same file causes duplicate lines.
- **Four reference docs in repo root:** [ARCHITECTURE.md](ARCHITECTURE.md) (system design), [TODO.md](TODO.md) (prioritized work), [CONTEXT.md](CONTEXT.md) (this file), [ANALYSIS_LOG.md](ANALYSIS_LOG.md) (behavior-vs-KB cross-references).

> 🔁 **STANDING CONVENTION — always do this:** Whenever you analyze live system
> behavior (skip reasons, EOD review, why-no-trade, signal quality, etc.),
> cross-reference it against [knowledge_base.md](knowledge_base.md) and append
> an entry to [ANALYSIS_LOG.md](ANALYSIS_LOG.md) with: observed behavior, the
> KB rule(s) it maps to (§ ref), and a verdict (✅ ENFORCED / ⚠️ DRIFT / ❓ GAP).
> This is the loop that catches silent strategy drift. Never present an analysis
> without the KB comparison — an analysis without a "is this correct per our
> codified rules?" verdict is incomplete.

---

## 👤 Trader profile (locked 2026-05-14)

User's target real-money setup — **all strategy decisions must respect these constraints**:

| Parameter | Value | Implication |
|-----------|-------|-------------|
| **Account size** | **$5,000** | Sub-PDT ($25K threshold). FINRA rule limits to **3 day-trades per rolling 5-day window**. |
| **Max daily loss** | **$1,000 (20% of account)** | Aggressive by pro standards (most use 1-3%/day). 5 bad days = wiped account. The 20% comes from user's stated tolerance, not a recommendation. |
| **Implied weekly capacity** | **3 day-trades / week** | PDT-bound. Cannot use 8-trade-per-day defaults; system must enforce. |
| **Per-trade budget** | **~$200-330 risk** | $1000 daily / max 3 trades/week ÷ 5 trading days × 1 trade ≈ $300/trade. At 40% stop on a $5 option = $200 max loss = need 1 contract per trade. |
| **Minimum trade notional** | ~$500 entry premium × 100 | Below that, $0.65/contract round-trip fees + 1-2¢ spread eats >40% of risk budget. **Friction is the silent killer at this account size.** |

### Required parameter changes for live mode (not yet applied — go-live gated by backtest validation):

| Constant | Current default | Live-mode target | Why |
|----------|-----------------|------------------|-----|
| `DAILY_LOSS_LIMIT_PCT` | 0.015 (1.5%) | **0.20 (20%)** | Match user's stated $1000 daily risk on $5K account |
| `MAX_RISK_PCT` (per-trade) | 0.005 (0.5%) | **0.04 (4%)** | $200/trade so 1 SPY ATM contract actually fits within risk budget |
| `MAX_PORTFOLIO_RISK` | 0.03 (3%) | **0.20 (20%)** | Allow all 3 weekly day-trades + 1 overnight to fit |
| `MAX_DAILY_ENTRIES` | 8 | **2** | PDT cap enforced (3-per-5-day window). 2/day average works out to 10/week — far too many. Hard-cap at 2/day. |
| `DAILY_PROFIT_LOCK_PCT` | 0.02 (2%) | **0.10 (10%)** | $500 profit lock to scale for higher daily variance |

### Honest assessment of these settings:

- ⚠️ **20% daily DD is 4-7× higher than pro discipline.** This is the user's choice but worth re-confirming after each losing day. Most pros use 1-3%.
- ⚠️ **Bankruptcy math: 5 max-loss days in 1 week = $0.** At PDT 3 trades/week, that's 1.5 weeks to zero. Plan for this scenario.
- ✅ Account size is honest about being a learning experiment, not retirement money.
- ✅ User said "1000 risk on a given day" — meaning they accept losing $1K in a session. That's a real risk tolerance, not bravado.

### Strategy adaptations needed for $5K + 3 trades/week:

1. **Be picky.** With 3 trades/week, average expected entry-skip rate must be ~85-90% (current is ~70%). The signal stack needs to fire less, not more. The recent `mean_rev` and `trend_cont` evaluators may be too loose for this account size — backtest will tell us.
2. **Take partials aggressively.** With $200/trade risk and $1K daily ceiling, a single $200 winner is real progress. Don't wait for T2 (+100%). Consider T1 at +30% on this account instead of +50%.
3. **No correlated stacking.** With 3 trades/week and 6 symbols, if all 3 fire bullish on tech names = single bet. Item 4 in tomorrow's queue (correlation cap) becomes load-bearing.
4. **Pre-FOMC/CPI = wait.** Losing all 3 weekly trades to a 2pm Fed announcement = whole week wasted. Item 5 (macro blackout) becomes load-bearing.
5. **Friday gamma trap.** 7-DTE on Monday is 4-DTE on Friday. With only 3 trades/week, one Friday gamma blowup = the whole week.

These are the constraints we'll design tomorrow's backtest and risk-gate work around.

---

## 📌 Last session: 2026-05-14

### What we shipped

1. **Position persistence + two-way Alpaca reconcile** — `_open_positions` now persists to `~/.spy_trader/open_positions.json` (atomic tmp+rename) on every mutation. On restart `reconcile_positions()` does a two-way sync: adds Alpaca positions missing locally AND removes local positions Alpaca no longer holds (kills the "position not found" error spam). Detection by OCC regex (not asset_class) so NVDA/non-SPY options are picked up.
2. **Sync Positions button** — manual on-demand reconcile from the Settings tab (`⟳ Sync Positions`). No app restart needed.
3. **UI redesign** — tab-based layout:
   - **⚙ Settings** (first tab, default on load): all config/automation/freshness/session/positions cards in a responsive CSS grid (auto-fill 300px columns, each card has native vertical resize)
   - **SPY / AMZN / GOOG / MSFT / NVDA / META**: full-screen chart, nothing else visible
   - **📊 Backtest**: full-screen backtest panel
   - **📋 Log**: full-screen `auto_trader.log` terminal
4. **Log file renamed** `spy_trader.log` → `auto_trader.log` across all files (handler, launcher, UI label).
5. **macOS .app icon** — gradient bar chart (purple/pink, matches design ref). Saved as `AppIcon.icns` + `AppIcon.svg`. Installed to `/Applications/SPY Auto Trader.app`. Favicon for browser too.
6. **Default state changes** — `DRY_RUN=False`, `auto_trade=True`, `debate_enabled=True` set as defaults at app boot (paper mode is the safety; DRY_RUN was redundant).
7. **Risk-cap session start fix** — `_launch_session` no longer refuses to start a symbol when portfolio risk ≥ MAX_PORTFOLIO_RISK. The cap is still enforced per-entry inside the session. This unblocked MSFT/NVDA/META from starting when NVDA's existing position pushed the account to 5.2%.
8. **Scheduler retries missing sessions** — scheduler used to fire once per day; now it relaunches any symbol that isn't running on every poll during market hours. Transient blocks (news veto, risk cap) recover automatically.
9. **`refresh_prices` split** — fast path (active symbol only) for login + UI handlers, full path (all 6 symbols) on the background `price_ticker` thread every 3rd tick. Login no longer hangs on yfinance latency.
10. **Singleton Anthropic client** — `get_anthropic_client()` in `debate.py` caches a single `anthropic.Anthropic()` instance. Fixes "Too many open files" from per-call instantiation.
11. **Knowledge base expanded 10 → 28 books** — VSA, Brooks price action, Sinclair/Hull vol, Fontanills discipline rules wired into debate prompts.

### Pending decisions / next steps

- [ ] Expose `MAX_PORTFOLIO_RISK` as a Settings stepper (filed as TODO #4b)
- [ ] Pick top P1 items: #6 Friday/expiry-week gamma, #7 correlation-adjusted delta cap, #5 macro event blackout
- [ ] Score recent NVDA bull entries against debate-suppressed signals — is the gate actually adding edge?
- [ ] Decide on real-money vs continued paper (TODO 🎯-P3 readiness gates)

---

## 🟢 What's running right now (verify before assuming)

- **Launch path:** macOS app bundle at `/Applications/SPY Auto Trader.app` → spawns Flask via `desktop.py` (or run `scripts/app.py` directly)
- **Log file:** `auto_trader.log` (main, file handler via RotatingFileHandler 10 MB × 5) + `errors.log` (ERROR-only) + `security.log`
- **Position state:** `~/.spy_trader/open_positions.json` — persisted on every mutation, loaded before reconcile
- **Defaults:** `DRY_RUN=False`, `auto_trade=True`, `debate_enabled=True`, `news_filter_enabled=True`, `trade_memory_enabled=True`
- **Verify with:** `lsof -ti :5000` (process), `curl -s http://localhost:5000/health` (HTTP), `cat ~/.spy_trader/open_positions.json | jq .` (positions)
- **Open positions (as of last check):** 2 NVDA calls — `NVDA260522C00232500` 2x @ $9.97, `NVDA260522C00235000` 4x @ $8.98 — total ~5.2% deployed risk

---

## 🧠 Project gotchas to remember

- **Timezone:** the file-handler formatter (`_ETFormatter` in spy_auto_trader.py) now stamps log lines in **ET** explicitly. No more mental conversion from CDT.
- **Don't run two `app.py` processes** — they both write to `auto_trader.log` causing duplicate lines. Always `lsof -ti :5000 | xargs kill -9` before relaunching.
- **DRY_RUN off by default is intentional** — paper mode is already the safety layer; DRY_RUN simulating-on-top-of-paper is redundant and confusing. Don't suggest flipping DRY_RUN back on as a default.
- **Position close path uses `TRADING_CLIENT.close_position(occ)` for full closes** (not `submit_order(SELL)` — Alpaca treats SELL as opening an uncovered short).
- **All Day Session** is the only session type (the old morning/evening split was unified). Runs 9:30 → end time (default 15:45 ET).
- **Worktrees:** be careful which directory you're in when running `git`. The main repo is at `/Users/bsannadi/Desktop/AlpacaTrader`. Edits via absolute paths go to the main repo regardless of worktree CWD.

---

## 📁 Where to look in the codebase

| Need | Go here |
|---|---|
| Signal logic | [scripts/spy_auto_trader.py](scripts/spy_auto_trader.py) — `all_day_session`, `generate_signal`, `opening_range` |
| Risk checks | [spy_auto_trader.py](scripts/spy_auto_trader.py) — `size_contracts`, `daily_loss_check`, `deployed_risk_pct` |
| Position management | [spy_auto_trader.py:check_positions](scripts/spy_auto_trader.py) (every 10s) |
| Position persistence | [spy_auto_trader.py](scripts/spy_auto_trader.py) — `_save_positions`, `_load_positions`, `reconcile_positions` |
| Flask + SocketIO | [scripts/app.py](scripts/app.py) — handlers + background tasks |
| Tuning constants | [spy_auto_trader.py:90–155](scripts/spy_auto_trader.py:90) |
| Trade memory (ChromaDB) | [scripts/trade_memory.py](scripts/trade_memory.py) |
| Debate gate (LLM) | [scripts/debate.py](scripts/debate.py) — singleton client via `get_anthropic_client()` |
| News filter | [scripts/news_filter.py](scripts/news_filter.py) |
| Auth / security | [scripts/security.py](scripts/security.py) |
| UI templates | [templates/index.html](templates/index.html) — tab-based layout, view-{chart,settings,log} body classes |
| UI scripts | [static/main.js](static/main.js) — `_setViewMode()`, `setActiveSymbol()`, `showSettings()`, `showLog()`, `syncPositions()` |
| Knowledge base (28 books) | [knowledge_base.md](knowledge_base.md) — extracted rules injected into debate prompts |

---

## ✏️ Maintaining this file

When something meaningful happens (fix shipped, decision made, mode changed, key constant changed), update:
- "Last session" section with date + bullet of what happened
- "Pending decisions" — check off completed, add new
- "What's running" — log location, current mode, open positions
- Drop stale sections (no "uncommitted changes" lists — those rot fast)

Goal: a future-me reading this should reach the same situational awareness in 2 minutes that the prior session took an hour to build.
