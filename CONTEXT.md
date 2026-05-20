# Session Context — Pick Up Here

Quick-resume doc for Claude (and humans). Keep it current. Read this first; deep-dive into [ARCHITECTURE.md](ARCHITECTURE.md) or [TODO.md](TODO.md) as needed.

---

## 🧭 The 30-second handoff

- **Project:** SPY Auto Trader — Flask + SocketIO options day-trading bot. Paper mode.
- **⚠️ Strategy state (2026-05-19):** NO validated edge. Options strategy disproven (backtest); shares over-claim corrected & refuted @realistic cost; building the **2S dual-instrument** framework + **3R phased roadmap** as PAPER-ONLY scaffolding. Read "Last session" + ANALYSIS_LOG before any strategy work. Do NOT treat the framework build as edge validation.
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

## 🪜 Phased capital roadmap (locked 2026-05-19, user directive)

All trade/option strategising must serve this 3-phase progression. Each
phase has an OBJECTIVE gate to the next — not vibes.

| Phase | Capital | Risk posture | Purpose | Gate to advance |
|---|---|---|---|---|
| **1 — Paper (NOW)** | Paper $ | **MAX risk — intentionally aggressive** | LEARN: exercise the system hard, see gates fire, stress execution/UX, surface failure modes cheaply | A **cost-robust (≥3 bp) walk-forward backtest passes** AND a defined paper track record (see caveat) |
| **2 — Live trial** | **Real $5,000** | Disciplined (the locked $5K profile above — NOT phase-1 max risk) | Validate the edge survives REAL fills/slippage/psychology at small stakes | **Profitable AND consistent** over a defined live-trial window (criteria below) |
| **3 — Scale** | **+$100,000** | Scaled but disciplined | Real trading at size | — |

**Honest caveats (must stay attached to this plan):**
1. **"Max risk on paper to learn" is valid ONLY for learning system
   mechanics** (gate behaviour, execution, UX, failure modes). Paper P&L
   at max risk on a not-yet-cost-robust edge teaches *nothing about
   edge* — it's noise amplified. Do NOT read paper profit as validation.
2. **Phase-1→2 gate is the backtest, not paper P&L.** A strategy can be
   green in paper and still be the fragile 3 bp-failing edge we already
   found. The cost-robust backtest + GO_LIVE_CHECKLIST is the real gate
   (this is the existing non-negotiable guardrail; this roadmap does not
   loosen it).
3. **Phase-1 max-risk profile must NOT silently carry into Phase 2.**
   The $5K live trial uses the disciplined locked profile. Needs an
   explicit paper-aggressive vs live-disciplined risk mode separation
   (TODO 3R) so going live can't inherit paper recklessness.
4. **"Profitable and consistent" must be defined numerically** before
   Phase 2→3 (e.g. ≥N live-trial weeks, positive expectancy after real
   costs, max-DD within tolerance) — TODO 3R captures this.

### ⚠️ Sizing reality at $5K (discovered building item 3, 2026-05-15)

With the **default 50% stop**, an option's risk/contract = `mid × 0.50 × 100`.
At $5K with 4% per-trade ($200 budget):
- $5.00 mid option → $250 risk/contract → **unaffordable** (0 contracts)
- $4.00 mid option → $200 → exactly 1 contract
- ≤ $3.50 mid option → fits with room

**Implication:** at $5K the system can only trade **cheaper options (≤$4 mid)**
unless item 14's dynamic exits land (a 30% stop in volatile conditions drops
risk/contract to $150, making $5 options affordable). This is correct
conservative behavior, not a bug — but it means the tradeable universe at $5K
is narrower than at $100K. Don't "fix" it by loosening the stop; that's the
curve-fit trap. It resolves naturally when item 14 ships backtest-proven
context-aware stops.

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

## 📌 Last session: 2026-05-19 (strategy-research arc)

> Earlier infra work (position persistence, two-way Alpaca reconcile, tab UI,
> macOS .app, scheduler retry, KB 10→28 books) shipped 2026-05-14 — see git
> history. This session was the **strategy verdict + research** arc:

1. **Backtest harness built & run on REAL paid Polygon 3yr data** —
   `polygon_data.py`, `backtest_v2.py`, `backtest_structures.py`,
   `backtest_shares_robust.py`, `signal_diagnostic.py`. $108 data spend
   bought a definitive answer.
2. **THE verdict:** the automated **options** strategy has **no edge**
   (S0 naked PF 0.92, net-negative). `vwap_momentum` has a *real but small*
   directional edge on the **underlying** (signal_diagnostic: ~52-56% hit,
   +0.6 ATR/60min) — too thin to survive theta (options) OR slippage
   (shares) at current frequency.
3. **S3 shares over-claim CORRECTED (own error):** "shares PF 1.38 / +$70k"
   was a 1bp-slippage artifact; @3bp realistic PF 0.97. S3 **refuted**.
   `backtest_shares_robust.py` cost-gate caught it pre-build.
4. **Architecture set (user directive):** **2S** dual-instrument
   portfolio-of-strategies (shared signal core → instrument router →
   shared risk brain; each strategy earns its slot via its OWN ≥3bp
   walk-forward). **3R** phased capital roadmap (paper@learn → $5K live
   trial → +$100K). Hard guardrail: paper-only, every route gated by
   GO_LIVE_CHECKLIST + cost-robust backtest. Build ≠ validated.
5. **PDT self-enforcement disabled** — `PDT_RULE_ENABLED=False` operator
   switch (rule eliminated mid-2026 per operator); daily-entry cap → 8.
6. **Chart tab-switch latency fixed** — TTL 8→60s + background prewarm.
7. **Deep book-read (problem-targeted):** `book_dig.py`; 8 masters
   converged → KB updated §4 (Kelly/ruin·Sinclair), §5 (transaction-cost
   hierarchy), §8 (Sinclair+Gunn), §11 (Trader's Equation·Brooks),
   §12 NEW (validation discipline·Davey). Risk-Mgmt collection = no-op
   (out of domain, honest negative logged).
8. **39-ticker universe** pulled & cached (`universe.py`,
   `pull_universe.py`; 39/39 OK, CRWV/ARM partial).

### Pending decisions / next steps

- [x] 39-ticker shares-robustness — DONE 2026-05-19: PF 1.09 @3bp
      (⚠️ MARGINAL/CONCENTRATED, fails @5bp). Key finding: edge lives in
      HIGH-vol single names (NVDA/SOFI/ARM/TEAM/HOOD/PLTR), NEGATIVE on
      low-vol index/mega (SPY/QQQ/MSFT/V/GOOG). Original 6-sym watchlist
      ≈ worst universe. NOT validated. Logged ANALYSIS_LOG 2026-05-19.
- [x] **Tier-1 H-REGIME+H-RUN+vol-universe** — DONE 2026-05-19: FAILED the
      gate. V1 H-RUN best Te PF 1.16@3bp / **0.88@5bp** (cost-fragile).
      H-RUN directionally right (win 53→56%) but not enough. Tier-1
      exhausted. Logged.
- [x] **Tier-2 Connors mean-reversion** — DONE 2026-05-19: **0 trades**
      (intraday EMA200 doesn't form on 5-min bars; canonical Connors is
      a DAILY-bar signal). Frame confirmed as bottleneck.
- [ ] 🚧 **DECISION FORK (the real next step — see ANALYSIS_LOG strategic
      synthesis 2026-05-19):**
      **A) Frame shift** — build daily-bar harness, retest Connors at
      native timeframe + Tier-A candidates (PEAD, overnight/intraday
      return decomp, VIX term-structure, variance risk premium /
      systematic short-vol). Real new infra (~2-4 weeks); intraday code
      mostly doesn't transfer.
      **B) Stop** — accept project as rigorous research + apparatus +
      permanent data backup. Don't deploy real money. Professional
      outcome. Most retail accounts end far worse.
      Don't decide tonight; wait BK-B verification, cancel Polygon, sleep on it.
- [ ] 3R code-update tasks (now broken down in TODO 3R, ~10h total, $0,
      transfers across A/B): A.1-4 risk-mode separation; B.1-3 Kelly +
      hard GO_LIVE gates; C.1-4 paper learning instrumentation.
- [ ] ARCHITECTURE.md STALE re: dual-instrument 2S — banner added; full
      rewrite folds into 2S-E (post-validated-strategy).

---

## 🟢 What's running right now (verify before assuming)

- **Strategy state:** NO validated edge yet. Options route disproven;
  shares route refuted @realistic cost; spreads unresolved. Hypotheses
  H-REGIME/H-RUN/H-VSA/H-SPR/H-VOL/H-KELLY queued, all ≥3bp-gated.
- **Background job:** 39-ticker `backtest_shares_robust.py ALL` run
  (cached Polygon, $0). Check `/tmp/bsr39.log` for `Report →`.
- **Launch path:** macOS app at `/Applications/SPY Auto Trader.app` → Flask
  via `desktop.py` (or `scripts/app.py` directly)
- **Log file:** `auto_trader.log` (RotatingFileHandler 10 MB × 5) +
  `errors.log` + `security.log`
- **Defaults:** `DRY_RUN=False`, `auto_trade=True`, `debate_enabled=True`,
  `PDT_RULE_ENABLED=False` (operator-disabled 2026-05-19)
- **Verify with:** `lsof -ti :5000`, `curl -s http://localhost:5000/health`,
  `cat ~/.spy_trader/open_positions.json | jq .`
- **Polygon cache:** `~/Desktop/AlpacaTrader_Data/polygon_cache` (~760 MB,
  39 symbols stock bars + sampled option OHLC; $0 to re-run backtests)
- **Open positions:** verify live (the 2026-05-14 NVDA snapshot is stale)

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
