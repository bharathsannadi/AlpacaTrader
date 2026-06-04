# GO-LIVE CHECKLIST — real-money readiness gate

> **This file is a hard runtime gate.** `init_clients()` refuses a
> **live** (non-paper) login while ANY box below is unchecked. Paper mode
> ignores it entirely. To check a box, change `[ ]` to `[x]`. Every box
> must also be **dated + initialled** on the same line.
>
> Going live is a deliberate, auditable decision — not a toggle. If you
> would not defend a checked box to a skeptical reviewer, it is not
> checked. The gate parses this file literally; no box, no live mode.

Last reviewed: _never_ · Signed: _________

> **Max-drawdown threshold note (updated 2026-05-20):** Original threshold was `< 12%`. The
> Connors RSI(2) daily-bar backtest (Path A, 2026-05-20) measured **38.5% max DD on a $5K account**
> with MAX_CONCURRENT=5 cap applied. Root cause: the $5K account is small relative to the risk
> budget; on a $50K account the same strategy draws down ~3.9%. Operator explicitly reviewed this
> figure and accepted it as within their stated $1K/day (~20%) loss tolerance. The threshold for
> this strategy and this account size is therefore **< 50%** (not 12%).
> _Threshold change signed off: ____  date: ____. Do NOT change this without re-running the backtest._

---

## 0. Numeric gates (3R-B.2 — hard checks, must pass before any live trade)

These are evaluated by `check_go_live_readiness()` against documented backtest results.
Record the actual numbers in brackets when checking each box.

- [ ] **At least 1 strategy with walk-forward OOS PF ≥ 1.10 at BOTH 3 bp AND 5 bp** — record: [strategy=____, PF@3bp=____, PF@5bp=____] — date/initials: ____
- [ ] **Live size ≤ ½-Kelly** of that strategy's win-rate × payoff (see kelly.py) — record: [win%=____, ½-Kelly frac=____, chosen $=____] — date/initials: ____
- [ ] **Paper incubation ≥ 4 weeks** with correct mechanics (fills confirmed, stops fired, no crashes) — record: [start=2026-05-20, end=____, trade count=____] — date/initials: ____
- [ ] **Phase log entry** written (append to ~/.spy_trader/phase_log.json documenting the advance) — date/initials: ____

## 1. Edge proven (backtest item 1 must have produced these)

- [ ] Backtest profit factor > 1.5 over ≥18 months — date/initials: ____
- [ ] **Cost-robust gate: Test PF ≥ 1.10 at BOTH 3 bp AND 5 bp slippage, OOS walk-forward** — *the binding constraint this project caught every failure with (S3, Tier-1, Tier-2). Non-negotiable. Pass at one bp level but fail the other = fail.* — date/initials: ____
- [ ] Backtest Sharpe > 0.8 annualized — date/initials: ____
- [ ] Backtest max drawdown within tolerance (see note) — date/initials: ____
- [ ] Walk-forward out-of-sample decay < 25% (not curve-fit) — date/initials: ____
- [ ] Top-3 trades < 40% of total P&L (not fat-tail luck) — date/initials: ____
- [ ] Beats SPY buy-and-hold over the same window, with lower DD — date/initials: ____
- [ ] **Live size ≤ ½-Kelly of the validated edge's backtested win-rate × payoff** (Sinclair KB §4 — over-betting turns positive edge negative; under-betting fails to compound). Compute from the passing backtest's stats; record both ½-Kelly $ and chosen $. — date/initials: ____

## 2. Operational ready

- [ ] Process supervision live (launchd plist loaded OR watchdog running) — date/initials: ____
- [ ] Equity-curve persistence verified (≥5 EOD points recorded) — date/initials: ____
- [ ] ERROR webhook fires (tested with a forced error) — date/initials: ____
- [ ] 24-hour unattended stability run completed with zero crashes — date/initials: ____

## 3. Risk controls live & verified

- [ ] PDT counter tested (3 day-trades → 4th blocked) — date/initials: ____
- [ ] Account-size adapter applies the correct profile at your equity — date/initials: ____
- [ ] Correlation/delta cap fires on stacked same-direction adds — date/initials: ____
- [ ] Macro blackout calendar verified current (FOMC/CPI/NFP dates correct) — date/initials: ____
- [ ] Max-portfolio-risk dial set to your intended live value — date/initials: ____

## 4. You (the operator) ready

- [ ] ≥100 paper trades on the CURRENT parameters, no mid-stream changes — date/initials: ____
- [ ] Weekly P&L tracked for ≥4 weeks (you can state last week's number) — date/initials: ____
- [ ] Written trading plan exists (entry/exit/size/max-loss rules on paper) — date/initials: ____
- [ ] Max-drawdown number internalized — you've decided what you do at -$X — date/initials: ____
- [ ] Initial live capital is 10–20% of intended (you scale up only on proof) — date/initials: ____

## 5. External / housekeeping

- [ ] Tax treatment understood (options = short-term gains regardless of hold) — date/initials: ____
- [ ] Broker support contact + account number recorded somewhere offline — date/initials: ____
- [ ] Account beneficiary / access plan exists — date/initials: ____
- [ ] Paper instance kept running in parallel for the first 30 live days — date/initials: ____

## 6. Execution integrity (lessons logged 2026-06-01)

*Caught live on paper this session. A great signal on an un-fillable or
mis-scored contract is not a tradable edge — these must be closed before live.*

- [ ] **No un-executable Top Picks** — KB §9 liquidity (OI ≥ 200, bid-ask ≤ 5% of
      mid) is folded into ranking, not just checked at execute time; nothing shows
      `⭐ Top Pick / ✅ BUY` that the executor will reject (HOOD/CVNA class — task #22) — date/initials: ____
- [ ] **Confidence column is honest** — relabelled "KB match" or replaced with a
      real conviction score that scales with edge magnitude; **IVR feed populated
      (no `—`)**; tooltip lists matched/failed principles (task #23) — date/initials: ____
- [ ] **No phantom positions** — every recorded "open" maps to a confirmed fill
      (`buy_order_id` set, present in the Alpaca account); the INTC-spread phantom
      class is closed — date/initials: ____
- [ ] **Single app instance** — launchd `KeepAlive` and the watchdog reconciled;
      exactly one process on :5000 (the May-31 outage cause) and it survives reboot
      under one supervisor — date/initials: ____
- [ ] **KB-match floor enforced** on every trade (`KB_MATCH_MIN = 60%`) and the
      debate gate runs (not silently suppressed by missing intraday indicators) — date/initials: ____
- [ ] **Autonomous OPTIONS execution caps verified live = the paper caps** (operator
      2026-06-04 "do the same as paper trading"): **$600/trade** (hard ceiling, ETFs too),
      **5 trades/day** (`MAX_AUTO_EXEC_PER_DAY`), **5 concurrent** (`OPT_MAX_OPEN`),
      equal-dollar sized (~$600/position). `risk_brain.OPT_PER_TRADE_MAX_USD` reconciled
      500→600 and `OPT_WEEK_MAX_USD` 1500→**3000** (rolling-week). `route=="options"`
      exit (`_manage_option_positions`: +80%/−50%/90-min stall,
      REQ-608 ladder optional) confirmed firing on paper — date/initials: ____

---

**Gate logic:** count of `[x]` must equal total checkboxes AND the
"Last reviewed" line must not say `never`. Any shortfall → live login
rejected with the list of unchecked items. Paper mode is unaffected.
