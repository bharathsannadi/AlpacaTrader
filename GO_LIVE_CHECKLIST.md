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

---

## 1. Edge proven (backtest item 1 must have produced these)

- [ ] Backtest profit factor > 1.5 over ≥18 months — date/initials: ____
- [ ] **Cost-robust gate: Test PF ≥ 1.10 at BOTH 3 bp AND 5 bp slippage, OOS walk-forward** — *the binding constraint this project caught every failure with (S3, Tier-1, Tier-2). Non-negotiable. Pass at one bp level but fail the other = fail.* — date/initials: ____
- [ ] Backtest Sharpe > 0.8 annualized — date/initials: ____
- [ ] Backtest max drawdown < 12% — date/initials: ____
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

---

**Gate logic:** count of `[x]` must equal total checkboxes AND the
"Last reviewed" line must not say `never`. Any shortfall → live login
rejected with the list of unchecked items. Paper mode is unaffected.
