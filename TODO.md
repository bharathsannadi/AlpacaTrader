# AlpacaTrader — End-of-Day TODO

Deep audit performed: 2026-05-12 (mid-session). Defer code changes until after market close so we don't restart the app while sessions are running.

> **Overall verdict:** This is a genuinely well-built system. Daily loss/profit circuit breakers, sector caps, IV rank gates, earnings filter, Greeks-aware sizing, time stops, breakeven ratchet, position reconciliation on restart, walk-to-ask order execution, news filter, LLM debate gate — all already implemented. The items below are *the next tier* of pro-trader concerns, not "the system is broken."

---

## 🔴 P0 — Real bugs / data-integrity gaps

### 1. Dry-run trades all share `order_id="DRY_RUN"` (collision)
- **Where:** [scripts/spy_auto_trader.py:1897](scripts/spy_auto_trader.py:1897)
- **Problem:** Hard-coded string. Multiple concurrent dry-runs collide on the same key.
- **Fix:** `f"DRY_{occ_symbol}_{int(time.time()*1000)}"`.

### 2. Dry-run entries not recorded in ChromaDB
- **Where:** [scripts/spy_auto_trader.py:1892-1899](scripts/spy_auto_trader.py:1892) vs [1952](scripts/spy_auto_trader.py:1952)
- **Problem:** `TRADE_MEMORY.record()` is real-trade-only. `update_outcome()` for dry-runs silently no-ops — learning loop is dormant during dry-run mode.
- **Fix:** Add `TRADE_MEMORY.record(..., is_dry_run=True)` in the dry-run branch. Update `retrieve_similar()` to filter dry-runs out by default (keep dataset clean for live), but expose them for backtesting / what-if review.

### 3. Dry-run positions vanish on app restart
- **Where:** [scripts/spy_auto_trader.py:reconcile_positions](scripts/spy_auto_trader.py:3050)
- **Problem:** `reconcile_positions()` queries Alpaca for orphaned positions. Dry-runs don't exist at Alpaca → wiped clean on restart. If we restarted the app today after the 09:15 SPY 737P fired, all tracking would be lost.
- **Fix:** Persist `_open_positions` to a JSON file on every change; reload on startup; reconcile real ones with Alpaca + retain dry-runs from the JSON.

### 3b. **CRITICAL** — `TimeInForce.IOC` not supported by Alpaca for options
- **Where:** [scripts/spy_auto_trader.py:3129](scripts/spy_auto_trader.py:3129) in `_close_option_position`.
- **Problem:** Alpaca rejects every close order with `{"code":42210000,"message":"order_time_in_force provided not supported for options trading"}`. Alpaca options only support `DAY` and `GTC`. The system **cannot close positions in real (non-dry-run) mode**. Stops, T1, T2, hard-close — all fail.
- **Observed today (2026-05-12):** **1,313 ERROR lines** all from this single bug. SPY 737P stop-out couldn't close, error spam every 10s after the dry-run toggle flipped off.
- **Fix:** Change to `TimeInForce.DAY`. The existing `client_order_id` retry logic already dedupes, so the "don't leave a resting close order" concern in the original comment is moot — same client_order_id = same order at Alpaca.
- **Severity:** **P0 blocker for going live.** Must be fixed before flipping `DRY_RUN = False` for real.

### 3c. **CRITICAL** — DRY_RUN toggle at runtime creates inconsistent close behavior
- **Where:** runtime state across [spy_auto_trader.py:1892](scripts/spy_auto_trader.py:1892) (entry branch) and [spy_auto_trader.py:3293](scripts/spy_auto_trader.py:3293) (close branch); UI toggle at [app.py:645](scripts/app.py:645).
- **Problem:** Position metadata doesn't carry `is_dry_run`. Entry path checks `DRY_RUN` global at entry time; close path checks it at close time. If user flips `DRY_RUN` off mid-session, dry-run-entered positions try to close as real Alpaca orders → fail (no position at Alpaca).
- **Observed today:** This is exactly what produced the stranded position + error spam.
- **Fix:**
  1. Add `is_dry_run: bool` field to the position dict in `register_trade()`, captured from `DRY_RUN` at entry time.
  2. In `check_positions` close path, branch on `pos["is_dry_run"]`, not the global `DRY_RUN`.
  3. (Optional) Disable the UI dry-run toggle when there are open positions of a different mode, OR queue the toggle to take effect after all positions close.

### 4. Reconciled positions get default risk params, not the original ones
- **Where:** [scripts/spy_auto_trader.py:3063](scripts/spy_auto_trader.py:3063)
- **Problem:** When `reconcile_positions` recovers an orphan, it calls `register_trade()` with current defaults for stop_pct, T1, T2 — so a position originally entered with a different config gets the wrong management plan after a restart.
- **Fix:** Persist the full position dict (stops/targets/entry_price/opened_at) alongside the symbol so reconciliation restores the exact plan.

---

## 🟠 P1 — Risk-management gaps a pro trader would flag

### 5. No macro event blackout (FOMC / CPI / NFP)
- **Status:** Earnings filter exists ([check_earnings_risk](scripts/spy_auto_trader.py:650)). No equivalent for macro events.
- **Why it matters:** A pre-Fed entry at 1:50 PM ET is a coin flip on the 2 PM statement. 7-DTE options through a CPI print = pure gamble. The system would happily fire.
- **Fix:** Add `check_macro_event_risk()` that returns blocked status for known windows: FOMC announcement (2 PM ET on Fed days), 8:30 AM data (CPI/PPI/NFP/GDP/PCE) within first 90 min, and Powell speeches. Use a static calendar or free API (FRED, Trading Economics).
- **Quick-win interim:** Block all new entries 30 min before & 30 min after the 2 PM ET hour on known FOMC dates (hard-coded list).

### 6. Friday / expiry-week gamma not throttled
- **Status:** `DTE_MIN = 7`. Means we can buy options that expire in 7 calendar days = 5 trading days.
- **Why it matters:** Gamma explodes in the last 3 days to expiry. A 7-DTE option held overnight Thu→Fri sees IV crush + accelerating theta + binary gamma. Not pro behavior unless intended.
- **Fix:** Add `DTE_MIN_FRIDAY = 14` (or skip new entries on Thu/Fri if DTE < 10). Also: never enter on Friday afternoon unless this is intentional 0DTE strategy.

### 7. Cross-symbol correlation risk
- **Status:** `MAX_SECTOR_POSITIONS = 2`. Helps, but SPY + AMZN + GOOG + MSFT + NVDA + META are **all** high-beta to SPY.
- **Why it matters:** Six 0.5% bets in the same direction during a market move = effectively a single 3% bet, not a diversified book. `MAX_PORTFOLIO_RISK = 3%` masks the true correlation-adjusted risk.
- **Fix:** Track signed delta-dollar exposure across positions (sum of `qty × delta × 100 × spot`). Cap net portfolio delta as a % of equity (e.g., ±5%) so a wave of bull signals doesn't quietly stack to a directional bet.

### 8. No trailing stop after T1 partial
- **Status:** At +30% → stop moves to breakeven. At +50% → close 25%. After that → static T2 at +100%.
- **Why it matters:** Today's SPY 737P at +50% would close 25% and then sit waiting for T2. If it goes +90% and reverses to +30%, we ride it back to breakeven on the remaining 75%. Pros trail the stop up after partial.
- **Fix:** After T1 fires, ratchet stop to `max(entry, current - 1.5×ATR_in_premium)` and update on each new high. Equivalent to a Chandelier exit on the remaining contracts.

### 9. Commissions / exchange fees not in P&L
- **Status:** P&L calc is mid-based, ignores fees. Alpaca options exchange/clearing fees ≈ $0.10-$0.65/contract round-trip.
- **Why it matters:** A 2-contract trade with 50% return on $5.75 entry = $575 gain → minus ~$1.50 fees. Not material at this size, but at scale or on tight setups (small wins) it inflates win rate by ~1-2 pp.
- **Fix:** Add `OPTION_FEE_PER_CONTRACT = 0.65` and subtract `2 × qty × fee` from realized P&L in close events.

### 10. No realized-slippage metric
- **Status:** Walk orders go mid → ask. No tracking of actual fill vs target mid.
- **Why it matters:** Slippage is a hidden tax. If average slippage is 5 ¢ on a $5 option = 100 bps drag per trade — invisible.
- **Fix:** In the real-order branch, capture `actual_fill_price` from the filled order and store `slippage_bps = (actual − target_mid) / target_mid × 10000`. Add to EOD review.

### 11. VIX absolute level only — no VIX rate-of-change
- **Status:** `VIX_MAX = 30`. Below that, anything goes.
- **Why it matters:** VIX going from 14 → 19 in one session is a regime change even though both are "low." Volatility-of-volatility (VVIX rising) is a pro signal.
- **Fix:** Block new entries when intraday VIX is up >15% from yesterday's close, regardless of absolute level.

### 12. Gap-day handling
- **Status:** No explicit "if SPY gapped >1.0% on open, wait extra 15-30 min" filter.
- **Why it matters:** Gap fills / gap-and-go are very different beasts and the first 30 min of a gap day is the highest-whipsaw period.
- **Fix:** Add `OPEN_GAP_DELAY_PCT = 1.0`. If open gap > threshold, push session start to 10:00 ET for that day.

---

## 🟡 P2 — Analytics & observability

### 13. EOD review missing pro metrics
- **Status:** Win rate, avg win, avg loss are computed. ([eod_review](scripts/spy_auto_trader.py:3471))
- **Missing:** Expectancy (`avg_win × win_rate - avg_loss × loss_rate`), profit factor (gross_wins / gross_losses), R-multiples per trade (P&L / risk-at-entry), max intraday drawdown, longest losing streak.
- **Fix:** Add these to the plain summary block.

### 14. No weekly / monthly equity tracking
- **Status:** Only daily loss/profit limits.
- **Why it matters:** A bot can be flat each day but bleed -0.3% × 20 days = -6% in a month and the daily limits never fire.
- **Fix:** Persist daily equity to JSON; expose 5-day / 20-day rolling drawdown in the EOD review. Add `WEEKLY_LOSS_HALT_PCT = 0.04`.

### 15. No log rotation
- **Status:** `spy_trader.log` grows unbounded.
- **Fix:** Wrap the file handler in `logging.handlers.RotatingFileHandler(maxBytes=10MB, backupCount=5)`.

### 16. No emergency "kill switch" / flatten-all button
- **Status:** To stop trading, user toggles auto-trade off + stops sessions. Open positions still ride.
- **Fix:** Add a "FLATTEN ALL" socket event that (a) sets a global halt flag, (b) closes every open position at the ask immediately (no walk), (c) cancels every working order. Confirmation modal required.

### 17. No process supervision / crash recovery
- **Status:** Run via `nohup`. If process dies mid-session, no auto-restart, no alert.
- **Fix:** Either a launchd plist (macOS) with `KeepAlive=true`, or a 5-line watchdog shell script + `kill -0 $PID` healthcheck.

### 18. Silent failures only logged as WARNING
- **Status:** e.g., `refresh_account failed: {e}` ([app.py:365](scripts/app.py:365)).
- **Fix:** Add a Pushover / Discord / Slack webhook for any ERROR or repeated WARNINGs > 3 in 10 minutes.

### 18b. Errors not isolated in their own log file
- **Status:** Everything (INFO, WARNING, ERROR) goes to one stream → `spy_trader.log` + stdout. Today's 1,313 ERROR lines were buried in tens of thousands of INFO lines making the actual problem hard to spot.
- **Fix:** Add a second `logging.handlers.RotatingFileHandler` writing to `errors.log` with `level=logging.ERROR`. INFO/WARNING continue to go to `spy_trader.log` as today. Bonus: a third handler for `signals.log` (entry decisions only) makes EOD parsing/journaling easier than regex over the full log.
- **Bonus:** Add a deduper that suppresses repeated identical ERROR lines (1,313 copies of the same string is noise) — emit once + a counter like "(× 1,313 over 4h)".

### 18c. Werkzeug development server in production (**deferred**)
- **Status:** [scripts/app.py:1060](scripts/app.py:1060) uses `socketio.run(app, ...)` with `allow_unsafe_werkzeug=True`. Flask logs a soft warning at startup.
- **Initial scope was wrong** — claimed "one-line change to async_mode='eventlet'". Reality: a proper switch requires `eventlet.monkey_patch()` at the entry point, which globally rewrites threading/socket/time primitives. The codebase uses `threading.Lock()` and `threading.Event()` extensively; all become eventlet-compatible but their behavior subtly changes (preemption rules, no kernel-level threads). Without monkey_patch, eventlet doesn't help — Socket.IO still falls back to threading.
- **Decision:** Deferred until there's a real reason to switch. The app runs on localhost only, paper trading, single user. No observed Werkzeug failures over a full session. Risk > reward for now.
- **Revisit if:** Multi-user access, real-money mode, or any sign of connection / memory leak under sustained load.

---

## 🟢 P3 — Cleanups

### 19. Stale docstring
- **Where:** [scripts/spy_auto_trader.py:3151](scripts/spy_auto_trader.py:3151) — says "Called every 30 s", actual is 10s.

### 20. Log timezone ambiguity
- **Status:** Trader logic uses ET (`ZoneInfo("America/New_York")`). Log timestamps use system local time (CDT for this machine).
- **Why it matters:** When reading logs, you have to constantly mentally convert. "09:15:00" in the log was actually 10:15 ET — easy to misread the timing of every trade.
- **Fix:** Force logger formatter to emit ET (or UTC) timestamps explicitly. Append "ET" suffix.

### 21. `PDT_REMAINING = 3` is module-state, not per-account
- **Status:** Comment says it doesn't apply ≥$25K margin accounts. Fine for now, but the constant is misleading if anyone ever runs a sub-$25K account.

### 22. Freshness panel shows option_quote as stale even when position_monitor is polling it
- **Where:** [scripts/spy_auto_trader.py:3115](scripts/spy_auto_trader.py:3115) and [3173](scripts/spy_auto_trader.py:3173)
- **Problem:** `check_positions` calls `OPTION_CLIENT.get_option_latest_quote()` every 10s for each open position but does NOT call `stamp_freshness("option_quote:{underlying}", ...)`. Only `find_atm_option` stamps that key. So if you have an open SPY position but no recent SPY entry attempts, the UI's freshness panel shows `option_quote:SPY` as 30+ minutes stale even though it's being polled every 10s.
- **Impact:** UI-only — misleading display. Trading logic is unaffected (`stale_data_check` only gates new entries, not management of existing positions).
- **Fix:** After each `get_option_latest_quote` in `check_positions`, derive the underlying from the OCC symbol (first 1–6 chars before the digits) and call `stamp_freshness(f"option_quote:{underlying}", source_tag="alpaca")`. ~2 lines per call site.

---

## 🎯 Strategy & Edge Validation — the single most important sub-project

> **The most honest critique of this codebase:** the infrastructure is A+ but the strategy edge is unproven. We've added 18 filters without ever verifying the underlying signal has positive expectancy after fees and slippage. Every item below is about answering "does this thing actually make money, and how do we know?"

### 🎯-P0 — Backtest harness (cannot validate edge without this)
- [ ] **Build `backtest.py`** as a standalone file (no changes to webapp) that:
  - Loads historical 5-min bars from yfinance or Polygon for SPY + watchlist over 3+ years
  - Loads historical option chains (Polygon `/options/contracts/historical` or theta-data) — required for realistic fills
  - Replays the existing `_add_indicators` + signal logic against each bar
  - Simulates entry/exit at the historical mid + spread + fee
  - Outputs: total return, Sharpe, Sortino, max DD, win rate, profit factor, expectancy, R-distribution, monthly equity curve
- [ ] **Compare against a dumb baseline.** "Buy SPY 30-DTE ATM call at every >0.5% gap up." If our strategy can't beat a 5-line baseline by 30%+, we don't have edge — we have complexity.
- [ ] **Walk-forward validation.** Train parameters on 2023, test on H1 2024. Refit on H1 2024, test on H2 2024. Repeat. Look for in-sample-only fits.
- [ ] **Parameter sensitivity sweep.** What happens if VIX_MAX moves 25→35, IV_RANK_MAX 60→80, STOP_LOSS_PCT 30→50? Robust systems work in a *neighborhood* of params, fragile ones cliff-edge.

### 🎯-P1 — Strategy structural changes (long-premium math is rough)
- [ ] **Stop-loss on underlying price, not premium %.** Current: `stop_price = entry × 0.6` on the *option*. A 0.7% adverse move in SPY can fully stop you out — that's noise. Better: store `entry_underlying_px` on the position and trigger stop when underlying moves ≥ 1.0× ATR against you. Gives consistent dollar risk.
- [ ] **A/B test debit spreads vs naked long options.** Same setups, same risk %, run for 30 days paper:
  - Spread: buy ATM, sell 2 strikes OTM → half the theta, half the vega, defined max profit (~50%)
  - Naked: current behavior
  - If naked wins by enough to justify the extra theta/vega cost → keep. If not → switch.
- [ ] **Pick a DTE side.** Current 7-14 DTE is incoherent — too much theta for swing, too much premium for scalp.
  - Option A (true intraday): DTE_MIN = 0, DTE_MAX = 2. Use 0-1 DTE SPY for breakouts. Theta is brutal but holding period is hours.
  - Option B (real swing): DTE_MIN = 21, DTE_MAX = 45. Less theta, more vega, hold 3-7 days. Pair with daily/weekly trend filter.
- [ ] **Diversify the watchlist beyond mega-cap-tech.** SPY + AMZN + GOOG + MSFT + NVDA + META are >0.85 correlated. Sector cap doesn't fix this — they all crash together on a Fed surprise. Add: IWM (small-cap, lower correlation), XLE or XLU (defensive), and consider dropping one of the tech names.

### 🎯-P2 — Track real performance, not vibes
- [ ] **Daily equity curve persisted + visible.** Append day-end equity to `~/.spy_trader/equity_curve.json`. Display rolling 30-day equity + 30-day drawdown chart in dashboard. **Without this you cannot tell if you're getting better or worse.**
- [ ] **Per-symbol P&L attribution.** Are we making money on SPY and losing it on NVDA? On bull signals vs bear? On ORB vs VWAP-momentum? Today's EOD review aggregates everything — split it.
- [ ] **Benchmark vs SPY buy-and-hold.** Each month: did the bot beat just buying SPY? If not for 3 months running, the strategy needs surgery, not a new filter.
- [ ] **Track avg slippage in bps and visualize trend.** The `entry_slippage_bps` field is captured but not surfaced anywhere — if it's drifting up, our fills are getting worse.
- [ ] **Per-trade R-multiple distribution histogram.** Quick visual of whether winners >> losers. A "lots of small wins, occasional big loss" distribution is the failure mode of every long-vol strategy.

### 🎯-P3 — Real-money readiness gates (don't trade real money until these pass)
- [ ] **Minimum 60 days of paper trading** with the *current* parameters, no mid-stream changes. Daily Sharpe > 0.5 annualized.
- [ ] **Drawdown discipline drill.** Simulate hitting `WEEKLY_LOSS_HALT_PCT` (currently 4%). Does the system actually halt? Does the user actually stop manually overriding? If you'd override yourself, you'll override the halt → don't go live.
- [ ] **Tax / wash-sale awareness for live.** Options are short-term capital gains regardless of holding period. If running ≥6 figures real, this materially affects after-tax returns and may favor IRA/Roth wrapping.
- [ ] **Margin call & PDT scenario tests** for sub-$25K accounts. The new `pdt_check` reading from Alpaca handles this — but verify by simulating 4+ day trades in one week on a paper sub-$25K account.

### 🎯-Stretch — quantitative refinement
- [ ] **Replace fixed filter thresholds with probability-of-success estimates.** Instead of "skip if IVR>70", use historical data to compute "for setups like this, IVR>70 trades have win rate X% — go/no-go based on expected value, not a hard cutoff."
- [ ] **Bayesian parameter updating.** As ChromaDB accumulates closed trades, update prior beliefs about which indicator combinations work. (This is closer to what the LLM debate aspires to but isn't.)
- [ ] **Regime detection.** Trend vs. chop vs. high-vol regimes call for different strategies. A regime classifier (HMM or simple range-rule) that switches strategy weights is what modern quant funds do.
- [ ] **Reality check: is the LLM debate gate actually helping?** Compare 30 days of trades passed by debate vs. similar trades the gate rejected (use ChromaDB retrieval). If passed-rate isn't materially higher P&L → it's a $0.001-per-call placebo.

---

## 📊 Chart View Upgrades — separate sub-project

The current chart is functional but bare: candles + bull/bear arrow markers. To match what the engine actually trades on (VWAP, EMAs, ORB levels, IV, etc.) the chart needs significant additions. Grouped by priority below.

**Current state:** [static/main.js:754-902](static/main.js:754) — LightweightCharts.createChart with `addCandlestickSeries` only, plus `setMarkers` for signal arrows. Server already emits via `socket.on("chart_data")` and `chart_data` SocketIO event from [app.py:978-1015](scripts/app.py:978).

### 📊-P0 — Show what the engine actually uses to make decisions ✅ SHIPPED
- [x] **VWAP line** (orange, lineWidth 2)
- [x] **EMA9 (cyan) + EMA21 (purple) + EMA200d (red dashed)** line series
- [x] **ORB high + ORB low** as cyan horizontal priceLines, axis label visible
- [x] **Prior day H/L/C** as dashed grey priceLines (PDH/PDL/PDC labels)
- [x] **Volume histogram pane** at bottom of chart, color-coded by candle direction

### 📊-P1 — Position context ✅ SHIPPED
- [x] **Entry marker** — yellow horizontal priceLine with "Entry Nx" + "[DRY]" tag for dry-runs
- [x] **Stop / T1 / T2 horizontal lines** — red (stop), yellow (T1), green (T2); T1 hidden once partial fires; stop line label switches to "(trail)" once T1 hits
- [x] **Close markers** — circles with P&L% + reason in marker text (event source `d.closes` reserved; backend needs to populate from trades_today, deferred to fast-follow)
- [x] **Live P&L badge** — top-right of chart header, green/red, aggregates open positions on active symbol
- [x] **Greyed-out background** — lunch + post-14:00 windows shaded via absolute-positioned divs

**Implementation notes:**
- Backend: new `chart_overlays(bars, symbol)` in [spy_auto_trader.py](scripts/spy_auto_trader.py) computes VWAP/EMAs/ORB/prior-levels from yfinance bars; new `_build_blocked_windows(bars)` in [app.py](scripts/app.py) emits time-range shading.
- Chart payload now carries: `overlays`, `position_overlay`, `blocked_windows` alongside `bars` and `signals`.
- Indicator tooltip on hover (O/H/L/C + VWAP + EMA9 + EMA21) implemented as a P3 freebie since the subscribeCrosshairMove hook was right there.

### 📊-P2 — Pro overlays
- [ ] **VWAP bands (±1σ, ±2σ)** — mean-reversion zones.
- [ ] **Bollinger Bands** (the engine computes them — logs show `BB[nan-nan]` often, suggesting bug there too).
- [ ] **RSI subplot** with 30/70 lines. Today's SPY hit RSI=22 — should be visible without reading log lines.
- [ ] **MACD subplot** with signal/histogram.
- [ ] **VIX overlay line** (small, in own scale) — regime context.
- [ ] **News-veto markers** — yellow dot at bars where news filter blocked a session start.
- [ ] **Earnings/macro event flags** — vertical dashed line at known event times (FOMC, CPI, ER).

### 📊-P3 — UX polish
- [ ] **Tooltip on hover** showing all indicator values for that bar (price, VWAP delta, EMAs, RSI, MACD, vol ratio, ATR).
- [ ] **Hide weekend / overnight gaps** so 5-day chart isn't broken by flat dead-zones.
- [ ] **Last bid / ask / spread in chart corner** for the active symbol (live tick).
- [ ] **Signal hover detail** — clicking a CALL/PUT arrow shows the full signal reasoning from the log (bull_score, bear_score, indicators at the time).
- [ ] **Replay slider** — drag back to any time today, see indicator state at that bar (post-trade learning).
- [ ] **Multi-symbol mini-chart row** — small sparklines for each watchlist symbol so user can scan trends across all 6 without tab-switching.
- [ ] **Persist chart preferences** (interval, range, indicator toggles) in localStorage so they survive a refresh.

### 📊-Backend support needed
Server endpoint [`get_chart_data` at app.py:978](scripts/app.py:978) currently returns `bars` + `signals` only. To enable the above:
- [ ] Extend payload to include indicator series aligned to bar timestamps (`vwap`, `ema9`, `ema21`, `ema200d`, `rsi`, `macd`, `volume_ratio`, `atr`, `bb_upper`, `bb_lower`).
- [ ] Add `prior_levels` block (PDH, PDL, PDC) + `orb` block (high, low, formed_at) + `events` array (news vetoes, earnings, FOMC).
- [ ] Add `position_overlay` block (entry, stop, t1, t2, current P&L) for the active symbol.

### 📊-Stretch goals
- [ ] **Theme picker** — current is dark-only.
- [ ] **Heat-strip below volume** colored by signal confidence (debate judge score 0-100) over time.
- [ ] **Export-to-PNG** of the chart with all overlays for sharing/journaling.
- [ ] **Side-by-side compare mode** — pin two symbols and align time scales.

---

## 🖥️ macOS Desktop App — separate sub-project

Wrap the existing Flask+SocketIO dashboard in a real Mac .app so it launches with one click, shows native notifications, and lives in the Dock (or menu bar). **Recommended path: PyWebView** — keeps everything in Python, ~30 lines of new code, packages with py2app.

**Why not Electron/Tauri:** would duplicate the UI in JS/TS and require a separate build pipeline. Existing Flask+JS dashboard is already complete; wrap it, don't rewrite it.

### 🖥️-P0 — Working desktop bundle
- [ ] Add `pywebview` + `py2app` to `requirements.txt`.
- [ ] Create `desktop.py` entry point that:
  - Starts Flask+SocketIO in a daemon thread (or launches `app.py` in a subprocess).
  - Waits for `http://127.0.0.1:5000/health` to return 200.
  - Opens a native `webview.create_window("SPY Auto Trader", "http://127.0.0.1:5000", width=1400, height=900)`.
  - Cleanly shuts down Flask on window close.
- [ ] Create `setup_py2app.py` to build the .app bundle with the right icon, bundle identifier, and entitlements.
- [ ] Test build: `python setup_py2app.py py2app` → produces `dist/SPY Auto Trader.app`.

### 🖥️-P1 — Native macOS polish
- [ ] **App icon** (.icns) — generate from a simple SVG.
- [ ] **Native menu bar** — File / Edit / View / Window menus with proper Cmd+Q, Cmd+W, Cmd+R bindings.
- [ ] **Desktop notifications** for fills, stop-outs, and target hits via `pync` or `pyobjus` (NSUserNotificationCenter).
  - Hook into `_on_trader_fill` callback in [app.py:368](scripts/app.py:368).
- [ ] **Dock badge** showing count of open positions.
- [ ] **Prevent system sleep during market hours** — replace the current `caffeinate` subprocess with native `IOPMAssertion` via pyobjus, only assert while sessions are running.

### 🖥️-P2 — Menu bar / status bar mode
- [ ] **Menu bar status item** showing live P&L (green/red) + small dot for system status (running / halted / disconnected). Click → opens the main window.
- [ ] **Right-click menu** with: Start all sessions / Stop all sessions / Flatten all / Toggle auto-trade / Open dashboard / Quit.
- [ ] Use `rumps` library (purpose-built for macOS status bar apps in Python).
- [ ] Decide: status bar replaces Dock app, or runs alongside (LSUIElement vs regular app).

### 🖥️-P3 — Distribution & robustness
- [ ] **Code signing** with your Apple Developer ID (Personal account, ~$99/yr) so Gatekeeper doesn't block the app. Required for any sharing beyond your own machine.
- [ ] **Notarization** — `xcrun notarytool submit` after signing for Catalina+ compatibility.
- [ ] **Auto-restart on crash** — launchd plist with `KeepAlive=true` so the app comes back if Flask dies (replaces the watchdog item #17).
- [ ] **Single-instance lock** — refuse to launch twice; bring existing window forward instead.
- [ ] **Crash log to local file** — capture stack traces in `~/Library/Logs/SPYAutoTrader/` for debugging.
- [ ] **Settings UI** — native preferences pane for `DRY_RUN`, `MAX_RISK_PCT`, `ANTHROPIC_API_KEY`, etc. instead of editing the .py file.

### 🖥️-Backend changes needed
- [ ] Make the Flask app importable cleanly (factory function `create_app()`) so `desktop.py` can run it in-process instead of spawning a subprocess. Lower memory, faster startup.
- [ ] Add a `/shutdown` endpoint guarded by a local-only secret so the desktop wrapper can cleanly stop background tasks before quitting.

### 🖥️-Stretch
- [ ] **Touch Bar support** for MacBook Pro models — buttons for "Pause All", "Flatten All", "Toggle Auto-trade".
- [ ] **Spotlight metadata** so Cmd+Space → "spy" surfaces the app.
- [ ] **iCloud sync** for ChromaDB memory + settings (cross-Mac).
- [ ] **Widget** (macOS 14+) — small dashboard tile on the desktop showing live P&L.

---

## ✅ Already fixed today (2026-05-12)

- Account / Buying Power / Max Risk header now auto-refreshes every ~15s ([scripts/app.py:44](scripts/app.py:44), [scripts/app.py:445](scripts/app.py:445)). Previously frozen between fills.
- **DRY_RUN default flipped to False** ([spy_auto_trader.py:90](scripts/spy_auto_trader.py:90)). Paper-mode is now the safety; DRY_RUN is opt-in for isolated testing.
- **#3b — `TimeInForce.IOC` → `DAY`** ([spy_auto_trader.py:3129](scripts/spy_auto_trader.py:3129)). Close orders now accepted by Alpaca; the 1,313-line error spam from today eliminated.
- **#3c — `is_dry_run` flag on position dict.** Set at entry from the global `DRY_RUN`, checked in close path. Toggle-mid-session no longer creates inconsistent state.
- **#1 — Unique dry-run order_id.** `f"DRY_{occ}_{ms}"` instead of literal `"DRY_RUN"`. No more ChromaDB collisions.
- **#2 — Dry-runs recorded in ChromaDB** with `is_dry_run=True` metadata. `retrieve_similar` filters them out by default (won't pollute real-trade learning); accessible via `include_dry_run=True`.
- **#3 + #4 — Open positions persisted to JSON.** `~/.spy_trader/open_positions.json` is written on every register/close/breakeven-ratchet; `reconcile_positions` loads it first so dry-runs survive restart and real-position stops/targets keep the original plan.
- **#15 — Log rotation.** `spy_trader.log` rotates at 10 MB × 5 backups, `security.log` at 5 MB × 3 backups via `RotatingFileHandler`.
- **#18b — Separate `errors.log` + dedup.** ERROR-level lines go to a dedicated rotating file. Repeats of identical messages within 60s are collapsed to one + a "(repeated N times)" summary, killing the kind of 1,313-line spam we saw today.

### Reconciliation pass (2026-05-12 evening): items already implemented in code

The following numbered TODO items were already implemented in the codebase before today's "fix the rest" session — they just weren't crossed off here. Verified via grep + code read:

- **#5** `macro_event_blackout_ok()` — hardcoded FOMC calendar through end of 2026, 30 min before/after release window. [spy_auto_trader.py:1997](scripts/spy_auto_trader.py:1997)
- **#6** `friday_gamma_ok(expiry)` — extends DTE_MIN on Thu/Fri to avoid expiry-week gamma. [spy_auto_trader.py:2026](scripts/spy_auto_trader.py:2026)
- **#7** `portfolio_delta_check()` + `net_portfolio_delta_dollars()` — net delta exposure cap across open positions. [spy_auto_trader.py:3806](scripts/spy_auto_trader.py:3806)
- **#8** Chandelier-style trailing stop after T1 — `peak_mid_after_t1` field on position dict + `TRAIL_GIVE_BACK` constant. [spy_auto_trader.py:3589](scripts/spy_auto_trader.py:3589)
- **#9** `OPTION_FEE_PER_CONTRACT = 0.65` applied to `pnl_pct_net` in close events. [spy_auto_trader.py:4165](scripts/spy_auto_trader.py:4165)
- **#10** `update_slippage_for_order()` captures realized fill vs target mid into `entry_slippage_bps` on the position. [spy_auto_trader.py:3602](scripts/spy_auto_trader.py:3602)
- **#11** VIX rate-of-change gate — `VIX_SPIKE_PCT = 0.15` blocks new entries when VIX is up >15% from prev close. [spy_auto_trader.py:2056](scripts/spy_auto_trader.py:2056)
- **#12** `gap_day_delay_ok()` — pushes first-entry to 10:00 ET on gap days. [spy_auto_trader.py:1923](scripts/spy_auto_trader.py:1923)
- **#13** EOD review now computes win rate, profit factor, expectancy, avg R-multiple. [spy_auto_trader.py:4330](scripts/spy_auto_trader.py:4330)
- **#14** `weekly_drawdown_check()` + persisted daily equity history. [spy_auto_trader.py:2157](scripts/spy_auto_trader.py:2157)
- **#16** `flatten_all_positions()` kill-switch. [spy_auto_trader.py:3895](scripts/spy_auto_trader.py:3895)
- **#17** launchd plist exists at `com.spy_auto_trader.plist` (repo root).
- **#18** `_WebhookAlertHandler` on root logger — POST to any Slack/Discord-compatible webhook on ERROR. [spy_auto_trader.py:369](scripts/spy_auto_trader.py:369)
- **#19** Stale "30s" docstring already updated to reference `POSITION_MONITOR_SEC (10s by default)`.
- **#20** `_ETFormatter` forces all log timestamps to ET, message format includes " ET" suffix. [spy_auto_trader.py:347](scripts/spy_auto_trader.py:347)
- **#22** `stamp_freshness("option_quote:{sym}", ...)` now called in both `_close_option_position` and `check_positions` quote-fetch paths.

### Shipped in this "fix the rest" session

- **#21** `pdt_check()` rewritten to query Alpaca's `account.pattern_day_trader` + `daytrade_count` instead of trusting a static `PDT_REMAINING = 3` constant. Sub-$25K accounts now get accurate enforcement. [spy_auto_trader.py:1889](scripts/spy_auto_trader.py:1889)
- **#18c** Werkzeug development server replaced with **eventlet WSGI**. `_ASYNC_MODE = "eventlet"` with `monkey_patch()` at the top of [app.py:7-22](scripts/app.py:7). Deprecation warning suppressed (we acknowledge eventlet is in bugfix mode; gevent or ASGI is the longer-term target). Falls back to threading + `allow_unsafe_werkzeug` if eventlet ever fails to import.

### Second batch (P1 + P2 + P3, late 2026-05-12)

- **P3 #19** — Stale "30s" docstring fixed; now references `POSITION_MONITOR_SEC`.
- **P3 #20** — Log timestamps now emit in **ET** (`2026-05-12 16:40:16 ET`). Custom `_ETFormatter` on the root logger.
- **P3 #21** — `PDT_REMAINING` comment clarified — only enforced when `pattern_day_trader` + equity < $25K.
- **P3 #22** — `check_positions` and `_close_option_position` now `stamp_freshness("option_quote:SYMBOL", ...)` on every quote fetch, so the UI panel reflects actual liveness instead of going red after 30s of no entry attempts.
- **P2 #18c** — **Deferred** (see entry above). Werkzeug warning is cosmetic; eventlet requires invasive monkey_patch().
- **P2 #13** — EOD review now reports **win rate, profit factor, expectancy %, avg R-multiple, max consecutive losses, gross wins, gross losses**. ([spy_auto_trader.py:eod_review](scripts/spy_auto_trader.py:3471))
- **P2 #14** — Weekly drawdown tracking: closing equity persisted to `~/.spy_trader/equity_history.json` at EOD; `weekly_drawdown_check` halts new entries when 5-day DD ≥ `WEEKLY_LOSS_HALT_PCT` (4%). EOD review prints 5-day + 20-day DD.
- **P2 #16** — Kill switch / flatten-all. New `flatten_all_positions()` + socket handlers `flatten_all` (requires `confirm: "FLATTEN"`) and `clear_emergency_halt`. Closes every open position, halts new entries via `_EMERGENCY_HALT` flag. **UI button not yet added — see chart/desktop sub-projects.**
- **P2 #17** — `com.spy_auto_trader.plist` launchd template at repo root. Activate with `cp ... ~/Library/LaunchAgents/ && launchctl load ...`.
- **P2 #18** — Webhook alerts on ERROR: set `$ALERT_WEBHOOK_URL` (Slack/Discord-compatible). Rate-limited to 1 post / 60s.
- **P1 #5** — FOMC/CPI/NFP blackout via hardcoded `MACRO_EVENTS` calendar (2026 dates pre-loaded). 30-min before to 30-min after window. **You must keep the list current.** Long-term: swap for FRED/TradingEconomics API.
- **P1 #6** — Friday gamma throttle: on Fridays, require DTE ≥ `FRIDAY_MIN_DTE` (10) for new entries. Wired into `target_expiry` gating.
- **P1 #7** — Correlation-adjusted portfolio delta cap. New `net_portfolio_delta_dollars()` sums signed delta-$ across all open positions; `portfolio_delta_check` blocks same-direction adds when |net delta| ≥ `MAX_NET_PORTFOLIO_DELTA_PCT` (5%) of equity. Hedging trades still pass.
- **P1 #8** — Trailing stop after T1. Once partial fires, tracks `peak_mid_after_t1`; trailing stop = peak × (1 − `TRAIL_GIVE_BACK_PCT`=20%). Stop only ratchets UP; floor at entry if `TRAIL_MIN_STOP_AT_ENTRY`.
- **P1 #9** — Per-contract fees subtracted from realized P&L. `pnl_pct_net` and `fees_pct` now in close event payload. `OPTION_FEE_PER_CONTRACT = $0.65` round-trip.
- **P1 #10** — Realized slippage tracking. `update_slippage_for_order` captures actual fill vs target mid in bps; stored on position dict as `entry_slippage_bps` and emitted in close events.
- **P1 #11** — VIX rate-of-change gate. Blocks new entries when intraday VIX > `VIX_SPIKE_PCT` (15%) above prior close, even when absolute VIX is < `VIX_MAX`.
- **P1 #12** — Gap-day delay. Blocks entries before 10:00 ET on days where the open gaps > `OPEN_GAP_DELAY_PCT` (1%) from prior close.

---

## 📋 Session observations (today, 2026-05-12)

- **Hypothetical fired:** SPY 737P, May 19 expiry, 2x @ $5.75 — DRY RUN.
  - At 10:34 ET: SPY $733.61 → position estimated **+25-28%** (working).
  - 7 DTE means we'd be in the high-gamma zone end of next week — flag #6 applies.
- **Skipped tickers behaving correctly:** GOOG (IVR=100%), NVDA (IVR=100%), MSFT (spread=18% of mid).
- **ANTHROPIC_API_KEY still unset** → debate gate OFF, EOD review will be plain-stats only.
- **AUTO-TRADE enabled** in dry-run. Re-think the default before going live.

---

## 🔧 EOD decisions checklist

- [ ] **Restart app after 16:00 ET market close** — picks up `DRY_RUN = False` so tomorrow trades real paper orders
- [ ] Sanity-check today's hypothetical SPY 737P EOD result against the engine's tracked P&L (then it's gone — dry-runs don't persist across restart)
- [ ] Apply P0 fixes (#1, #2, #3, #4) — bugs/data-integrity
- [ ] Pick which P1 fixes to take next: #5 (FOMC blackout), #6 (Friday gamma), #7 (correlation), #8 (trailing stop)
- [ ] P2 quick wins: #15 (log rotation, 5 LOC), #19/#20 (cleanups)
- [ ] Set `ANTHROPIC_API_KEY` to enable debate gate + LLM EOD review
