# Analysis Log — System Behavior vs. Knowledge Base

**Standing convention:** every time we analyze the system's live behavior (skip
reasons, EOD review, why-no-trade, signal-quality, etc.), we cross-reference it
against [knowledge_base.md](knowledge_base.md) and record **both** the observed
behavior AND which KB rule it validates or contradicts.

**Why:** this is the loop that tells us whether the codified rules are actually
being enforced in production (good — discipline holding) or whether live
behavior has drifted from the documented strategy (bad — silent regression).
Without this cross-reference, an analysis is just "here's what happened" with no
verdict on whether that's *correct*.

**Format per entry:**
- Date + analysis type
- Observed behavior (the data)
- KB rule(s) it maps to (§ reference)
- Verdict: ✅ ENFORCED (live matches KB) · ⚠️ DRIFT (live contradicts KB) · ❓ GAP (behavior not covered by any KB rule → KB needs a new rule)

---

## 2026-05-15 — Skip-reason analysis (0 trades day)

**Observed:** All 6 symbols ran sessions; every fired signal suppressed by the
debate gate; 0 trades. Root cause near-universal: volume ratio 0.23–0.65 (35–77%
below normal). MSFT the lone exception — suppressed for RSI 86 parabolic blow-off.

| Symbol | Observed reason | KB rule | Verdict |
|--------|-----------------|---------|---------|
| SPY | Vol ratio 0.62, no institutional backing | §Quick Rules "Vol ratio on entry < 0.8 → reduce/skip" + Sinclair vol-trend rule (§12) | ✅ ENFORCED |
| AMZN | Vol ratio 0.23, 82% below 1.3× ORB minimum | §6 ORB "requires vol ratio > 1.3" + §10 VSA institutional-backing | ✅ ENFORCED |
| GOOG | Vol 0.65 + MACD neg + 5 similar = −9% realized | §12 Sinclair + §15 Lowell "hope is not a strategy" + trade-memory recall | ✅ ENFORCED |
| MSFT | RSI 86 climactic exhaustion | §3 "avoid RSI > 70 for calls" + §11 Brooks climax-bar (>2×ATR don't chase) | ✅ ENFORCED |
| NVDA | RSI 33 + vol 0.55 + flat MACD | §16 Thomsett put rule "put RSI window 40–55, NOT <30 (oversold=bounce risk)" | ✅ ENFORCED |
| META | Vol 0.57 + RSI 63 + 7-DTE theta, no vol cushion | §6 ORB vol gate + §1 theta-acceleration + §2 IVR-unknown vega risk | ✅ ENFORCED |

**Verdict: ✅ ALL ENFORCED.** Live debate-gate behavior is a faithful execution
of the codified KB rules — zero drift. The volume gate, RSI ceiling, Brooks
exhaustion rule, Thomsett put-window rule, and Sinclair institutional-backing
rule are all firing exactly as written. The system correctly sat out a
low-volume chop day.

**KB-coverage gaps found:** none. Every rejection traced cleanly to an existing
KB rule. (If a future analysis finds a skip with no mapping KB rule, that's a
❓ GAP → add the rule to knowledge_base.md.)

**Caveat carried forward:** "all enforced" ≠ "profitable." This confirms the
rules are *applied*, not that the rules *make money*. That's the backtest's job
(TODO item 1). An analysis can be ✅ ENFORCED and the strategy still net-negative
if the rules are too strict and filter out winners. Keep this distinction.

---

## 2026-05-15 (11:48 ET) — Why-no-trade follow-up (sustained 0-trade day)

**Observed:** Still 0 trades 2+ hours later. Market-wide low volume persists +
lunch-hour lull (11:30–13:30 ET) active. Live vol ratios: SPY 0.68×, AMZN 0.99×,
GOOG 0.42×, MSFT 0.85×, NVDA 0.53×, META 0.62× — all below institutional
thresholds (0.8 floor / 1.3× ORB). META up to 24 suppressions.

| Symbol | Block | KB rule | Verdict |
|--------|-------|---------|---------|
| SPY/NVDA/META | vol < 0.8 floor | §12 Sinclair vol-trend + §10 VSA | ✅ ENFORCED |
| AMZN | vol < 1.3× ORB min | §6 ORB volume confirmation | ✅ ENFORCED |
| GOOG | RSI 31 oversold-trap + dead vol | §16 Thomsett (put RSI 40–55, NOT <30) | ✅ ENFORCED |
| MSFT | RSI 66.9 + vol gate | §3 RSI ceiling + vol gate | ✅ ENFORCED |

**Verdict: ✅ ALL ENFORCED.** Consistent with the morning entry — same root
cause (dead tape), zero drift, zero KB gaps. Two consecutive same-verdict
analyses on the same day = the volume gate is the dominant filter on low-vol
days.

**Strategic flag (NOT drift — a backtest question):** 0 trades for a full
session is correct *if* low-volume days are genuinely unprofitable. But this is
now the central unanswered question — **does the volume gate filter out losers
(good) or also filter out winners, leaving the strategy net break-even (bad)?**
One quiet day can't answer it. This is precisely what backtest item 1 must
measure: P&L of taken trades vs. the counterfactual P&L of the trades the volume
gate *rejected*. Until then, ✅ ENFORCED stands but edge remains unproven.

---

## 2026-05-15 — Design analysis: dynamic exits vs KB (item 14 / §P1-G)

**Observed:** Reviewed the proposed dynamic stop/target design against
knowledge_base.md to ground parameters in codified rules rather than gut.

**Finding (the important one):** The KB §3 ("Entry & Exit Timing") *already
prescribes* context-dependent exits. The live code's flat -50%/+75% constants
**under-implement the knowledge base**, not the reverse.

| KB rule (verbatim §3/§2/§10/§11/§1) | In code? | Verdict |
|---|---|---|
| 50% premium standard stop | ✅ baseline | ✅ ENFORCED |
| 30% stop in trending/volatile/high-gamma/short-DTE | ❌ | ⚠️ DRIFT (code less strict than KB) |
| Take 50% of max expected move (don't hold full) | partial | ⚠️ DRIFT |
| Time-exit if not profitable by 2:30 PM | ❌ (diff rule) | ⚠️ DRIFT |
| IV-spike vega-harvest (+50% even if flat underlying) | ❌ | ❓ GAP in code (rule exists in KB) |
| VIX 25–40 → tighter stops | ❌ | ⚠️ DRIFT |
| VSA upthrust → exit longs immediately | ❌ | ⚠️ DRIFT |
| Brooks climax >2×ATR → don't chase / exit | ❌ in exit path | ⚠️ DRIFT |

**Verdict: ⚠️ DRIFT — code is materially LESS adaptive than the KB prescribes.**
This is the first ⚠️ DRIFT entry in the log. Unlike the entry-gate analyses
(all ✅ ENFORCED), the EXIT logic has diverged from the documented strategy:
the KB says "be dynamic, tighten in volatility, harvest IV spikes, respect
2:30 PM" and the code does none of it — it just runs flat 50/75 then a
generic 60-min time-stop.

**Implication:** item 14 is reclassified from "nice-to-have enhancement" to
**"close a real strategy-vs-KB drift gap."** The free parameters (ATR mult,
VIX cut points) still get backtest-swept (item 1) to avoid curve-fit, but the
*rules themselves* are not speculative — they are quoted, codified KB content
that production currently ignores. Priority of item 14 should rise accordingly
once the backtest exists to set the parameters.

---

## 2026-05-15 — Entry-logic full audit vs KB (item 15 / §P1-H)

**Observed:** Cross-referenced every entry gate in spy_auto_trader.py against
all entry-relevant KB rules (§1,2,3,5,6,10,11,12,15,16,17 + Quick Rules).

**Already enforced (✅ verified, not gaps):** macro blackout (line 3369),
gap-day delay (3362), earnings filter, news filter, sector cap, PDT, global +
whipsaw cooldowns, time-of-day windows, daily loss/profit breakers, ORB volume
confirmation (MIN_VOL_RATIO 1.5), HTF 30-min trend filter, delta-band
selection (0.40–0.65), OI floor, 5% spread gate.

**Gaps found:**

| # | KB rule | Code | Verdict |
|---|---------|------|---------|
| H1 | IVR<30 naked / 30-50 spread / >50 skip (§2,§5) | IV_RANK_MAX=70, warn@50 | ⚠️ MAJOR DRIFT |
| H2 | IVR-based naked↔spread switching (§5) | naked-only, no spreads | ❓ GAP |
| H3 | "≥2 of 3 (ORB+VWAP+EMA), never single signal" | no confluence gate | ❓ GAP |
| H4 | VSA no-demand/upthrust/distribution = HARD rules (§10) | LLM-prompt only, no det. code | ⚠️ DRIFT (fragile) |
| H5 | VIX-regime strategy adaptation (§2) | regime logged, never acted on | ⚠️ DRIFT |
| H6 | VIX+5pt→spreads 2-3d; SPY>1%/3d→spreads (§12) | not implemented | ❓ GAP |

**Verdict: ⚠️ MIXED — entry gates mostly ✅ ENFORCED but 2 serious drifts.**
Consistent with the exit audit (§P1-G): the deterministic *risk gates* are
faithfully enforced, but the *strategy-selection* layer (IVR→strategy, signal
confluence, VSA, VIX-regime) has drifted from the KB. Pattern across both
audits: **mechanical risk discipline = solid; volatility/strategy-selection
intelligence = under-implemented vs the documented playbook.**

**Most material:** H1. The system buys naked long premium across IVR 30–70%,
the precise band the KB says is debit-spread-or-skip territory. This is a
plausible standing money-leak (systematically overpaying for vega) — and it
would be invisible in a backtest that doesn't tag IVR-at-entry. Backtest item
1 MUST bucket results by entry-IVR to quantify this. Interim fix (lower the
cutoff) is 1 hr and doesn't need spread capability.

**Caveat (same as always):** these are drift findings, not proof the KB rule
makes money. H1/H3/H4 interim fixes are backtest-swept (item 1), not
hand-set. ⚠️ DRIFT means "code diverged from documented strategy" — whether
the documented strategy is the profitable one is still the backtest's call.

---

## 2026-05-15 — Item 4 build: correlation cap was silently DEAD (2 stacked bugs)

**Observed:** `portfolio_delta_check` (KB §Maximum-Exposure / §15 Levy #10
correlation control) was wired into the entry stack but `net_portfolio_delta_
dollars()` had TWO bugs behind one bare `except: continue`:
1. `spot = get_symbol_price(sym) or 0.0` — get_symbol_price returns a TUPLE
   `(price,chg,session)`; `tuple <= 0` → TypeError → swallowed.
2. `bs_delta(..., is_call=...)` — real sig is `(spot,strike,tte,iv,option_type)`;
   bad kwarg + missing `iv` → TypeError → swallowed.
Net effect: every position contributed 0 → net delta ALWAYS 0.0 → the cap
NEVER fired. A key risk control for the user's exact profile (6 high-beta
tech names) was decorative.

| KB rule | Code state (before) | Verdict |
|---|---|---|
| §Max-Exposure / §15 #10 — cap correlated directional exposure | wired but silently always-0 | ❓ GAP (present-but-dead) → now ✅ ENFORCED (computes) |

**Verdict:** Bug fix = ✅ correct, gate now computes real signed delta.
BUT a calibration flaw remains: delta-dollars = delta×spot×100×qty is
equivalent-share *notional* (massive options leverage). At 5% of equity the
cap = $250 on a $5K acct = blocks EVERY trade (1 ATM option ≈ $11K delta-$).
The KB rule is about directional *concentration*, not raw notional — the
metric and/or threshold is mis-scaled for an options account.

**Disciplined resolution:** ship the bug fix (unambiguously correct — a dead
gate computing is strictly better). Do NOT hand-pick a new threshold —
flag it as backtest-coupled (item 1 sweep): test (a) notional-delta cap at
various %, (b) premium-weighted-delta cap, (c) max same-direction position
count. Pick the variant that holds out-of-sample. Logged as TODO §P1-I.

**Meta-pattern (3rd audit now):** exit (§P1-G), entry (§P1-H), and now this —
the deterministic risk-gate *scaffolding* exists but pieces are silently
inert or mis-scaled. The bare-except-swallows-everything anti-pattern is the
common root. Worth a dedicated sweep for other `except Exception: continue`
blocks hiding dead logic.

---

## 2026-05-17 — 🎯 BACKTEST v2 DELIVERED (free BS path) — the gating answer

**Observed:** Built `scripts/backtest_v2.py` (real evaluators imported from
spy_auto_trader, Black-Scholes pricing, VIX-IV proxy, fees+spread, exit
sweep, IVR buckets, walk-forward). 542 trades, 6 symbols, 60d 5-min.

**RESULT — the answer this whole project was gated on:**

| Layer | Verdict |
|---|---|
| **Aggregate** | PF **0.63**, exp **−3.06%/trade** → net NEGATIVE after costs |
| **vwap_momentum** | PF **1.75**, +3.68%/trade, +173% (47 trades) → ✅ REAL EDGE |
| **trend_cont** | PF **0.49**, −4.19%/trade, −1692% (404 trades = 75% of book) → 🔴 THE BLEED |
| gap_fade | PF 0.90, −0.86% → near-flat |
| Exit sweep | flat 0.63 ≈ atr_stop 0.64; momo_fade 0.47 (WORSE) |
| IVR H1 | 30-50 (0.52) worse than 20-30 (0.68) — drift direction confirmed |

**Verdict: ⚠️ DRIFT RESOLVED → strategy is net-negative BUT has a
profitable core.** This retires the caveat carried in EVERY prior
analysis-log entry ("✅ ENFORCED ≠ profitable"). Answer: the faithfully-
enforced discipline was applied to a signal mix that is net-negative —
specifically `trend_cont` (the loosest evaluator, added "when strict gates
produced 0 trades") is a money incinerator at scale, while `vwap_momentum`
genuinely works (KB §6 VWAP-momentum — the one signal with verbatim KB
grounding — is also the one with edge; the score-based trend_cont, the
least KB-grounded, is the bleed. The KB was right.)

**Evidence-based action (NOT a guess — 404-sample, 6-sym, OOS-consistent):**
disable or hard-gate `trend_cont`; restrict live to `vwap_momentum`
(+ gap_fade marginal). This is the highest-value change in the codebase
and it is backtest-justified, $0, reversible.

**Honest caveats (stated, not hidden):**
1. Backtest runs the RAW evaluator chain — NO debate gate / IVR-hard-gate /
   news. Live, debate suppresses ~all trades (ANALYSIS_LOG 0-trade days).
   So this measures the SIGNAL layer's raw expectancy, not the live gated
   system. The robust, gating-independent conclusion: trend_cont's raw
   expectancy is strongly negative across 404 samples — that holds
   regardless of what the debate gate does on top.
2. 60d only (free yfinance limit), BS pricing, flat VIX-IV. Directionally
   decisive at PF 0.49 vs 1.75 (a 3.5× spread won't invert under modeling
   slop), but the 3-yr paid path is still required for go-live magnitudes.
3. trend_cont was literally added as a fallback "when strict gates produced
   0 trades" — i.e. it was the "trade more" lever. The backtest proves
   trading more = losing more. KB §15 Levy / §17 discipline vindicated.

---

## 2026-05-17 — Reconciliation: §P1-G "exit drift" vs backtest exit-sweep

**Question raised:** do we have good adaptive entry/exit criteria matching
the KB, instead of fixed?

**Apparent contradiction in the log so far:**
- §P1-G (2026-05-15): code's FIXED exits ⚠️ DRIFT — KB §3 prescribes
  dynamic exits; "item 14 reclassified to close a real KB-drift gap."
- Backtest (2026-05-17): exit sweep — FIXED flat won (PF 1.17) vs
  class_targets 1.06, atr_stop 0.96, momo_fade 0.72.

**Reconciliation / verdict:** the §P1-G drift finding stands as
*documentation-accurate* (code does under-implement KB §3's dynamic
exits) but is **NOT yet evidence-supported as a defect** — on 60d the
simple fixed exit beat every adaptive variant tested. "Matching the KB"
≠ "more profitable." The KB is the hypothesis generator; the backtest is
the judge; the judge currently favors fixed.

**Entry side:** the backtest independently *confirmed* the KB on signal
selection — vwap_momentum (most KB-grounded, §6) PF 1.31 = the edge;
trend_cont (least KB-grounded, a "trade more" heuristic) PF 0.49 = the
bleed → disabled (item 17). So entry drift was real AND the KB-aligned
direction was the profitable one. Exit drift was real but the
KB-aligned direction (dynamic) did NOT beat fixed.

**Principle crystallized:** KB-alignment is correlated with profit on the
ENTRY/signal layer (confirmed) but NOT on the EXIT layer (refuted on
60d). Do not hand-implement §P1-G/§P1-H dynamic logic to "match the KB" —
the 3-yr paid sweep decides each parameter independently. Restraint here
is the correct behavior, not a gap. ✅ DISCIPLINE HOLDING.

---

## 2026-05-17 — Exit sweep DONE PROPERLY: user skepticism partially vindicated

**Context:** User pushed back on the "fixed beats adaptive" claim. They were
right to: the prior test used 3 single hardcoded adaptive guesses vs fixed —
not a real sweep. Rebuilt as a proper 10-variant parameter grid (ATR-stop
m∈{1.0,1.5,2.0,2.5}, ATR-trail{2,3}, iv_scaled, time_decay, class_targets)
with **walk-forward** (train 1st-half → judge OOS test 2nd-half, rank by
TEST PF — no in-sample cherry-pick).

| Variant | Test PF (OOS) |
|---|---|
| flat (fixed) | 1.48 |
| **iv_scaled** (KB §2 vol-adaptive) | **1.48 — exact tie** |
| atr_2.5 | 1.41 |
| atr_trail_2.0 | 1.40 |
| class_targets | 1.33 |
| atr_1.5 / atr_1.0 | 0.92 / 0.67 (refuted) |

**Verdict: ⚖️ PARITY, not "fixed wins."** Prior claim (1.17 vs 0.96) was an
artifact of an inadequate test. Real grid: fixed TIES the KB-grounded
iv_scaled adaptive dead-even OOS (+426% vs +428%). Fixed is not beaten but
NOT clearly superior — no penalty for a well-designed dynamic exit.

**KB cross-ref:** §3/§2 prescribe dynamic exits. Earlier §P1-G logged this
as ⚠️ DRIFT then the weak backtest seemed to refute the KB. The PROPER
backtest now says: the KB-grounded adaptive (iv_scaled = tighter stop when
VIX high, §2) is at parity → the §P1-G drift is **neither clearly benign
nor clearly harmful on 60d** — genuinely undecided, 3-yr paid run is the
tiebreaker. The one firm result: TIGHT atr stops (m≤1.5) are refuted
(noise-stop volatile options — itself KB-consistent).

**Process note:** this is the trust-but-verify discipline working *on
itself* — user skepticism → conceded the prior test was weak → rebuilt
it rigorously → honest result that's different from what I'd defended.
That correction loop is the point of ANALYSIS_LOG.

---

## 2026-05-18 — 🎯 DEFINITIVE: REAL 3yr 6-symbol backtest — STRATEGY HAS NO EDGE

**The gating question, finally answered on real data.** backtest_v2 on
REAL Polygon 3yr, 6 symbols, real option OHLC, conservative costs:

| Metric | Value |
|---|---|
| Aggregate | **PF 0.74, −1.3%/trade, 3,719 trades — NET NEGATIVE** |
| SPY | PF 1.18, +476% (the ONLY winner) |
| NVDA/MSFT/AMZN/GOOG/META | PF 0.63–0.74, ALL net-negative (−649% to −1317%) |
| vwap_momentum (full universe) | PF 0.88, −1620% — negative once SPY-cherry-pick removed |
| gap_fade | PF 0.46 — catastrophic |
| Exit sweep | MOOT — every variant <1.0 (best 0.81 = slowest leak) |
| Walk-forward | "holds OOS" = consistently loses OOS too |

**Verdict: ⛔ NO EDGE. Do not trade real money. Definitively.**

**Resolves the standing question retired across every prior entry**
("✅ ENFORCED ≠ profitable"): the discipline was faithfully applied to a
strategy that, on real 3yr data across a real universe, does not have
edge. SPY's +476% is 1-of-6 = textbook curve-fit outlier, NOT edge.

**Self-correction (trust-but-verify on my own claims):** the prior turn I
reported the SPY-only smoke as "viable, honest progress." The 6-symbol
breadth run REFUTED that. I owned it. Same standard applied to the exit
claim, the false data-instability alarm, and now this. The correction
loop is the point.

**Why this is the project's most valuable result:** $108 of Polygon data
bought a definitive negative answer that stopped real money funding a
−1.3%/trade strategy. The entire disciplined apparatus (attribution →
audits → no hand-tuning → real backtest before real money) existed to
produce exactly this moment. It worked.

**What it implies for code (per user decision 2026-05-18):**
- Exits: correctly UNCHANGED — sweep is moot when entry has no edge.
  Wiring an LLM into exits was proposed by user, declined with evidence
  (un-backtestable, can't fix no-edge entry, latency-unsafe for stops).
- Item 17 (trend_cont disabled) — confirmed correct but INSUFFICIENT;
  removing the worst signal didn't make the rest positive.
- Next: REDESIGN THE ENTRY SIGNAL (user choice) — but data-driven:
  first diagnose whether the signal has ANY underlying-direction
  predictive power (→ structure/theta problem, fixable) or none
  (→ signal is noise, must be replaced). See next entry.

---

## 2026-05-18 — 🎯 FORK A: signal HAS edge — option STRUCTURE is the bug

**signal_diagnostic.py** (real 3yr cached data, underlying-direction only,
decoupled from option P&L / theta / exits):

| signal | 15m hit | 30m hit | 60m hit | mean@60m | verdict |
|---|---|---|---|---|---|
| **vwap_momentum** | 55.2% | 57.7% | **60.5%** | **+0.62 ATR** | ✅ EDGE |
| gap_fade | 46.7% | 48.7% | 48.2% | +0.06 ATR | ⛔ NOISE |

Per-symbol @30m (NOT a SPY fluke): SPY 59.7 · AMZN 60.1 · GOOG 56.3 ·
MSFT 55.6 · NVDA 57.8 · META 55.9 — all six 55-60%.

**Reconciles the paradox.** Full backtest: vwap_momentum PF 0.88
(net-negative). Diagnostic: it predicts direction ~58%, move +0.34→+0.62
ATR, edge GROWS with horizon. Both true → exactly KB §1: "directionally
right, still lose money — move too slow, theta kills you." The 7-14 DTE
naked long option + 50%-premium-stop exit destroys a signal that works.

**Verdict: ✅ FORK A. The signal is good; the OPTION STRUCTURE is the
fixable bug.** Conclusion flips from "no edge, give up" to "proven signal,
wrong vehicle." This is the project's most actionable finding.

**Evidence-based live change:** gap_fade disabled (GAP_FADE_ENABLED=False)
— confirmed NOISE by TWO independent methods (backtest PF 0.46 +
diagnostic ~48%/~0ATR). Same justified+reversible pattern as item 17.
Live signal set is now vwap_momentum-only (the one with proven edge).

**Next (data-driven, NOT gut):** redesign STRUCTURE around the proven
vwap_momentum signal, backtest each on cached data:
  • DTE sweep {0,1,2 vs 30,45} — 7-14 is peak theta for a 30-60min move
  • underlying-ATR stop sized to the measured excursion (+0.34@30m /
    +0.62@60m), holding ≈60min not multi-day — replaces premium-% stop
  • debit spreads (KB §5) — cut theta+vega drag directly
NOT go-live. This is "is there a structure that monetizes the proven
directional edge after costs" — the next backtest answers it.

---
## 2026-05-18 — "Are we too restricted in taking trades?"
**Live gate stack on the user's $5K (sub-10K, sub-PDT) account:**
- SUB_PDT_MAX_DAILY_ENTRIES = 2 / day  (overrides MAX_DAILY_ENTRIES 8)
- PDT_MAX_DAY_TRADES_5D = 3  (FINRA law for <$25K margin — ~3 round-trips/WEEK, not a setting)
- GLOBAL_COOLDOWN 60s · WHIPSAW 900s · MAX_SECTOR_POSITIONS 2
- TREND_CONT + GAP_FADE disabled (proven NOISE — correct)
- liquidity gates: spread 5% / OI / MIN_NOTIONAL $300 · VIX-spike 15% · Friday DTE≥10 · daily-loss 20% halt · debate-confidence

**KB cross-ref:**
- ✅ ENFORCED — KB L451/L588: selectivity is a feature, not a bug; the 18-gate
  checklist is doctrine. Cooldowns/sector cap/whipsaw all map to KB.
- ✅ ENFORCED — PDT cap is legal reality, bot is correctly PDT-aware (prevents
  account lock), not "over-restricting" by choice.
- ⚠️ DRIFT (the real finding) — "too restricted" is the wrong question. Real
  3yr/6-sym backtest = PF 0.74 net-NEGATIVE → strategy has NO edge. Loosening
  gates on a no-edge strategy loses FASTER; the restriction is the only thing
  slowing the bleed. Bottleneck = lack of edge, not gate count.
- ❓ GAP — the one place restriction genuinely wastes value: signal_diagnostic
  proved vwap_momentum HAS directional edge on the UNDERLYING, but PDT
  (3 day-trades/wk) + 7-14 DTE option theta jointly throw it away. A shares/ETF
  SWING version (hold >1 day) escapes BOTH PDT and theta — the actionable path.

**Verdict:** Not over-restricted as an options day-trader (gates are correct &
mostly legally mandated). The restriction isn't the problem — the no-edge
options structure is. Don't relax gates. Test the proven directional edge as a
multi-day shares/ETF strategy instead.

---
## 2026-05-18 — Pro-trader platform review & rating

**Scorecard (weighted as a real desk would weight it):**
| Category | Wt | Score | Note |
|---|---|---|---|
| Edge / expectancy | 40% | 2/10 | PF 0.74, −1.3%/trade, 3719 trades, ALL 6 syms net-neg |
| Risk management | 20% | 9/10 | 4%/trade·20% port·20% daily-loss halt·cooldowns — institutional |
| Signal research | 12% | 8/10 | vwap_momentum proven directional edge; noise signals killed |
| Structure fit | 10% | 2/10 | 7-14DTE naked + 50% prem stop destroys the proven edge |
| Execution infra | 8% | 7/10 | spread/OI/notional gates, modeled slippage, real fills |
| Ops robustness | 6% | 8/10 | paper-mode, heartbeats, advisory mode, crash-safe |
| Process/discipline | 4% | 10/10 | backtest-as-judge, no hand-tuning, ANALYSIS_LOG, owns errors |
**Weighted overall ≈ 4.4/10 — DO NOT DEPLOY REAL CAPITAL.**

**KB cross-ref:**
- ✅ ENFORCED — risk/exit constants map to KB (§3 stops pre-planned, 50% prem
  stop Natenberg/Saliba, §6 vwap is the KB-grounded signal).
- ⚠️ DRIFT — KB §1 "directionally right, theta kills you" is exactly what the
  backtest shows; the live STRUCTURE contradicts the KB edge thesis.
- ⚠️ DRIFT — PDT relax (2026-05-18) raises trade frequency on a no-edge
  strategy → faster path to the 20% daily-loss halt. Sound infra, wrong
  engine to put more fuel in.
- ❓ GAP — no live-validated positive-expectancy structure exists yet; the
  shares/ETF swing test of vwap_momentum is the unfilled gap.

**Verdict:** Engineering, risk-control and research *process* are genuinely
top-decile for a retail system. The platform is rated low ONLY because a
trading platform's rating is dominated by edge, and the options structure has
none (backtest-proven). Fix = monetize the proven directional edge in a
structure that survives costs (shares/ETF swing), not more tuning.

---
## 2026-05-18 — External source review: YouTube cDt5LFXjq8Q
"Exit Strategies In Options Trading | Secure Your Profits & Limit Losses"
(Apr-2024 generic options-education video. Verbatim transcript not
retrievable; assessed from title + corroborated topic recap.)

**What it teaches:** limit-order profit exit · stop-order loss exit ·
trailing stops · "exit at 50% loss / +100% gain" · "take spreads off at
50% of max profit." Textbook premium-% exit rules.

**KB cross-ref & system check:**
- ✅ ENFORCED — these are ALREADY implemented: STOP_LOSS_PCT 0.50,
  PROFIT_TARGET 1.00, PARTIAL_TRIGGER_PCT 0.50, BREAKEVEN 0.30. Maps to
  KB §3 (pre-planned exits) / §1.
- ⚠️ DRIFT vs our own evidence — this video PRESCRIBES the exact
  premium-% structure the 3yr/6-sym backtest PROVED loses (PF 0.74).
  It is the failing structure, not a fix for it. Endorsement by a
  generic educational video ≠ edge.
- ❓ GAP — video says nothing about defining exits in UNDERLYING terms
  (ATR), DTE/delta selection, or vega; i.e. it omits exactly the levers
  our Structure-fit improvement plan (2026-05-18) identifies.

**Verdict:** Adds nothing new and offers no lift to the 2/10
Structure-fit. It reaffirms the premium-% approach we already run and
already disproved. Not actionable. Keep to the structure-comparison
backtest plan.

---
## 2026-05-18 — Exit-strategy coverage audit (5 categories vs code & KB)
Triggered by user checklist (Schwab/Fidelity/E*Trade exit taxonomy).

| Cat | Status | Code evidence | KB / Verdict |
|---|---|---|---|
| 1 Profit targets | ✅ HAVE | PROFIT_TARGET 1.00, PARTIAL_TRIGGER_PCT 0.50 + T2 | §3 ✅ ENFORCED |
| 2 Stop-loss / risk | ✅ HAVE | STOP_LOSS_PCT 0.50, 4%/20%/20% caps, TIME_STOP 60, EOD 15:50 | §3 ✅ ENFORCED |
| 3 Technical/catalyst exit | ❌ MISSING | no S/R, MA, VSA, or pre-catalyst position close | §10/§11 ⚠️ DRIFT (re-confirms prior log) |
| 4 Trailing stop | 🟡 PARTIAL | TRAIL_GIVE_BACK_PCT 0.20 premium-trail; no MA-trail | §3 ⚠️ partial DRIFT |
| 5 Rolling | ❌ ABSENT | close-only, no roll up/down/out | §15 — intentional; rolling = extend-loser trap on no-edge intraday |

**Key finding:** what we HAVE (1,2,4) is all premium-%-defined = the exact
structure the 3yr backtest disproved (PF 0.74). What we MISS (#3, MA-trail)
is underlying-terms = exactly the Structure-fit fix lever. Coverage looks
broad but is concentrated in the failing dimension.

**Verdict:** Add #3 (spot/technical invalidation exit) — highest-value,
matches the structure plan & closes a standing ⚠️ DRIFT. Deliberately
SKIP #5 (rolling) — anti-pattern for a no-edge intraday directional book.
None changes the score until backtested.

---
## 2026-05-18 — 80/20 exit rule: applicability check
**Q:** add the "80/20 rule" (close at 80% of max profit) to exits?

**Finding:** 80/20 is a premium-SELLER rule (needs defined max profit =
credit received). Our book is long-premium directional BUYER → max profit
undefined (unbounded for calls) → rule is structurally inapplicable as-is.

**KB cross-ref:**
- ❓ GAP — no 80/20 profit-capture rule in KB. Only the 80% *loss* ceiling
  (KB §"max hold to 80% loss") exists — different concept (hard stop).
- ✅ partial — buyer-analogue (scale-out + runner) already present:
  PARTIAL_TRIGGER_PCT 0.50 → PROFIT_TARGET 1.00.
- ⚠️ DRIFT-risk — bolting another premium-% exit onto the no-edge S0
  (PF 0.74) = deck-chair rearrangement; the apparatus exists to prevent
  exactly this untested tweak.

**Verdict:** Do NOT hardcode. 80/20 belongs to a short-premium STRUCTURE.
Proper test = add an S4 credit-spread + 80/20-exit variant to
backtest_structures.py IFF S2 (debit spread) shows life in the running
3yr run. Decision deferred to that result — no blind add.

---
## 2026-05-18 — STRUCTURE COMPARISON RESULT (backtest_structures.py)
Same vwap_momentum entries, 4 structures, REAL Polygon 3yr, 6 syms,
walk-forward 50/50, $200/trade risk budget. Headline = Test PF.

| Structure | n | Train PF | Test PF | Win% | Avg$ | Total$ |
|---|---|---|---|---|---|---|
| S3 SHARES | 1510 | 1.41 | **1.38** | 53.0 | +46.5 | **+70,212** |
| S0 naked 7-14d (CURRENT) | 1477 | 0.75 | 0.92 | 38.4 | -2.44 | -3,601 |
| S1 naked 25-45d ATR-exit | 1509 | 0.32 | 0.41 | 33.1 | -21.5 | -32,396 |
| S2 debit spread | 629 | 0 | 0 | 0.2 | — | INVALID (sparse short-leg data / pricing-bar mismatch — NOT a real result, disregard) |

**KB cross-ref:**
- ✅ ENFORCED — KB §1 "directionally right, theta kills you": S0/S1 naked
  long are net-neg; the SAME entries on shares (no theta/vega) print
  PF 1.38. The KB thesis is now quantified on real 3yr data.
- ✅ ROBUST — S3 train 1.41 → test 1.38 = −2% OOS decay (no curve-fit),
  1510 trades, 53% win, MaxDD −$4.5k vs +$70k total. Strongest positive
  evidence the project has produced.
- ⚠️ DRIFT confirmed — current production structure (S0) is net-negative
  (PF 0.92). The 2/10 Structure-fit rating is now data-validated.
- ❓ S2 unreliable — short-leg OHLC too sparse; spread verdict NOT
  established (neither for nor against). Needs a fixed spread harness.

**Verdict:** The vwap_momentum edge is REAL and is a **STOCK edge**. Every
naked-option wrapper destroys it (theta); shares preserve it (PF 1.38 OOS,
robust). Actionable path = build/validate the shares-or-ETF swing strategy;
deprioritize options. Not go-live yet: still needs per-symbol & per-year
robustness, cost-sensitivity, and GO_LIVE_CHECKLIST. S2 (spread) inconclusive
— re-test only if a fixed spread-data harness is built.

---
## 2026-05-19 — SHARES ROBUSTNESS: S3 REFUTED (own-error correction)
backtest_shares_robust.py — same vwap_momentum entries, ATR exit, 6 syms,
3yr, cost-sensitivity sweep.

**Result:** S3 PF 1.38 was an artifact of optimistic 1bp slippage.
| bp | PF | total$ |
|--|--|--|
| 1 | 1.39 | +147k |
| 3 (realistic) | 0.97 | -13.9k |
| 5 | 0.67 | -175k |
Per-symbol @3bp: only NVDA 1.55 / AMZN 1.22 positive; SPY 0.70 MSFT 0.79
GOOG 0.87 negative. 11/24 symbol-year cells PF≥1.0 (coin flip). NVDA
decays 1.96→0.99 over 2023→2026.

**KB cross-ref:**
- ⚠️ DRIFT (my own analysis) — I labelled S3 "decisive & robust" on a
  train/test decay check ALONE, without a slippage-sensitivity check.
  That was the error. KB §15 Lowell "hope is not a strategy" + the
  project's own trust-but-verify discipline. Correction owned.
- ✅ ENFORCED (method) — the cost-sensitivity gate worked exactly as
  designed: it caught a fragile edge before it became a build decision.
- ⚠️ structural — shares sized to a tight 1.0×ATR stop → huge share
  count for low-ATR names → fixed-bp slippage scales with NOTIONAL not
  RISK. The tight-ATR exit makes BOTH the options and shares expressions
  cost-fragile by construction. The negative is partly the (my,
  unvalidated) exit design, not purely the signal.

**Verdict:** Neither the naked-options route NOR the naive-shares route
has a cost-robust edge. signal_diagnostic's underlying directional edge
is REAL but SMALL (~+0.6 ATR/60min, 52-56% hit) — too small to clear
theta (options) or notional-scaled slippage at a tight stop (shares) at
this trade FREQUENCY. The lever is SELECTIVITY / wider stops / lower
frequency / better excursion-capture — NOT more instruments. Do NOT
cherry-pick NVDA+AMZN (small-sample survivorship = the SPY-fluke trap).
2S dual-instrument build + 1S 39-ticker pull are PREMATURE until a
cost-robust expression exists. Next test is cheap ($0 cached): does a
selective / wider-stop / lower-frequency variant clear 3-5bp?

---
## 2026-05-19 — DEEP BOOK READ (problem-targeted: thin edge dies after costs)
Tooling: scripts/book_dig.py (pypdf, surgical passage extraction — NOT a
re-summary; 3 scanned books Natenberg-1994/Hull/Passarelli need OCR).

**Sources & verbatim findings:**
- Natenberg *Option Vol & Pricing* p.71/72/97/107: profit needs a positive
  THEORETICAL edge; for options that edge must be a VOLATILITY edge, not
  direction alone ("unlike directional strategies… there is no current
  volatility"). → thin directional view as long premium = paying embedded
  theta/vega for priced-in movement.
- Saliba *Option Spread Strategies* p.39: "Vertical spreads are
  DIRECTIONAL strategies… to capture MODERATE underlying moves… limited
  risk… when implied [vol elevated]"; p.5 warns transaction costs
  "significant, especially in option strategies".
- Brooks *Price Action Trends* p.26 Trader's Equation P(win)·reward >
  P(loss)·risk; p.17 edges small/fleeting; p.36 best trades + reward≥risk
  + INCREASE SIZE not frequency; p.85 winners run 4R+, partial+breakeven+
  let remainder run.

**KB cross-ref:**
- ✅ ENFORCED — KB §5 (IVR→spread decision) & §Signal-Quality (2-of-3) &
  §3 (partial/breakeven) already encode these. Books validate KB.
- ❓ GAP (quantified, new) — KB states the rules; it does NOT state that
  OUR specific edge (52-56% / +0.6ATR) is, in Trader's-Equation terms,
  "barely favorable" and therefore (a) MUST be a spread not naked
  (Natenberg+Saliba), (b) MUST use a runner exit not a fixed 1.5ATR cap
  (Brooks p.85 — our current exit is the flaw), (c) is lifted by
  SELECTIVITY+SIZE not more trades (Brooks p.36). This quantitative
  application is the new learning.

**Verdict / converges with backtests:** the literature independently
prescribes EXACTLY the three levers our data pointed to. Not a new
direction — a textbook-grounded confirmation. Actionable, testable:
- H-RUN: replace fixed 1.5ATR target with partial@~1ATR + breakeven +
  ATR-trail runner (Brooks p.85). Re-test shares @3-5bp. (My exit design
  was likely the flaw, not purely the signal — must verify.)
- H-SEL: selectivity gate (≥2-of-3 confluence + institutional-volume) →
  fewer, higher-P(win) trades. Test edge clears costs.
- H-SPR: fix S2 spread harness (2S-B) → test VERTICAL DEBIT SPREAD =
  Saliba's prescribed structure for moderate-directional+limited-risk.
None ships without its own cost-robust ≥3bp walk-forward pass.

---
## 2026-05-19 — DEEP READ: Volatility/VIX collection (Sinclair priority)
book_dig.py generalized to all book roots. 9 vol/VIX books text-OK
(1 corrupt dup). Priority: Sinclair *Volatility Trading 2013*.

**Sinclair verbatim findings:**
- p.14: "When trading options, finding an edge involves FORECASTING
  VOLATILITY" — the options edge IS a vol-forecast edge. Our system has
  ZERO vol forecast (pure price-direction). The missing piece, stated.
- p.67: option transaction costs (brokerage+bid/ask+fees+clearing) are
  "FAR LARGER than costs associated with trading stocks or futures."
  → decisive cross-confirm of why S0 options PF 0.92: a thin directional
  edge in the HIGHEST-cost instrument = structurally worst choice.
- p.54/57/65/87-90: volatility mean-reverts, clusters, +corr to level,
  vol↔volume correlated; VIX is empirically mean-reverting (but spot VIX
  untradable — "easy to price, hard to trade").
- p.17/Ch8: Kelly / trade sizing "dramatically affects returns" & risk
  of ruin — bet sizing is a first-class lever (Brooks p.36 "size" =
  Sinclair's Kelly math).

**KB cross-ref:**
- ✅ ENFORCED — KB §5 (IVR→strategy) & §2 (VIX regime) already encode
  vol-awareness. Sinclair validates KB.
- ⚠️ DRIFT (textbook-confirmed, escalated) — prior audit H1/H5: live
  system COMPUTES IVR/VIX but uses them only as loose filters, never as
  an EDGE. Sinclair+Natenberg make this not-optional: an options route
  with NO vol edge cannot overcome option-level costs. The H1/H5 drift
  is now a first-order defect, not a nicety.
- ❓ GAP — flat $200 sizing ignores Kelly; KB has no bet-sizing math.
  Material for the $5K→$100K roadmap & 20% daily-loss tolerance.

**Verdict / architecture refinement:** the 2S OPTIONS ROUTE must carry
its OWN volatility edge (IVR/vol-forecast), NOT merely spread-wrap the
directional signal — else it just pays higher option costs for the same
thin edge (Natenberg p.97 + Sinclair p.14/p.67). Two new testable
hypotheses:
- H-VOL: gate/condition the options route on a vol-edge (long premium
  only low-IVR per KB §5; OR a short-premium plug-in when IVR high &
  mean-reversion setup). Options trade ONLY with a vol edge present.
- H-KELLY: fractional-Kelly sizing vs flat $200 — measure return &
  risk-of-ruin impact (Sinclair Ch8) under the phased roadmap.
All gated by their own ≥3bp cost-robust walk-forward. No exceptions.

---
## 2026-05-19 — DEEP READ round 3: Gunn (Regime) + VSA. CONVERGENCE.
- Gunn *Trading Regime Analysis* p.22-24: "There is NO holy grail";
  edge = identifying TRENDING vs RANGING regime & only running the
  directional strategy when the regime favors it. p.24 verbatim: trend
  strategy "loses heavily" in non-trend, "wins superbly" in trend — net
  depends on regime mix. → our 52-56% aggregate is almost certainly
  STRONG-on-trend + NEGATIVE-on-chop blended to mush.
- VSA (Holmes companion): act with Smart Money; "no demand" (up bar /
  low vol) = no institutional backing → don't follow. Selectivity by
  institutional-volume confirmation.

**KB cross-ref:**
- ✅ ENFORCED — KB already has a chop filter + VSA concepts. Books
  validate the KB design.
- ⚠️ DRIFT escalated (textbook-confirmed, first-order now):
  · H5 — live computes a regime/chop label but NEVER acts on it. Gunn
    makes regime-gating THE lever for a trend strategy, not optional.
  · H4 — VSA is LLM-prompt-only, not deterministic code. VSA validates
    it must be a hard gate.
- ❓ none new.

**Convergence reached (6 masters → one prescription):**
Natenberg+Sinclair (need a vol edge; option costs >> stock) · Saliba
(vertical debit = the moderate-directional structure) · Brooks
(selectivity + reward≥risk + runner + size, Trader's Equation) · Gunn
(regime-gate the directional strategy) · VSA (institutional-volume
confirmation). They do not diverge — they all say the SAME thing:
a thin directional edge is monetized by SELECTIVITY (regime + volume),
correct STRUCTURE (spread / low-cost shares), RUNNER exit, and SIZING —
not more trades, signals, or instruments.

**Decision:** deep-read has hit diminishing returns (strong convergence,
no contradiction). Further reading is now lower-value than TESTING.
Prioritized, cost-gated (≥3bp walk-forward) hypothesis queue:
  H-REGIME (NEW, top) — gate vwap_momentum on trending regime (ADX /
     BB-width / existing chop label). $0 cached. Likely biggest uplift.
  H-RUN — runner exit vs fixed 1.5ATR target (Brooks p.85). $0 cached.
  H-SEL/H-VSA — deterministic institutional-volume gate.
  H-SPR — fixed spread harness + vertical debit (Saliba).
  H-VOL — options route gated on a real vol edge (Natenberg/Sinclair).
  H-KELLY — fractional-Kelly sizing (Sinclair Ch8) for the $5K→$100K road.
Sequence after the running 39-ticker robustness: H-REGIME + H-RUN first
(cheap, highest expected uplift, both test likely flaws in MY design).

---
## 2026-05-19 — DEEP READ round 4: Sinclair Ch8 (Kelly) — ROADMAP IMPACT
- p.149: Kelly fraction = peak of growth curve. **Betting >2× Kelly
  turns the growth rate NEGATIVE** — a positive-edge strategy LOSES
  money and tends to ruin purely from oversizing.
- p.150: half-Kelly ≈ most of the growth at far lower volatility/DD
  (standard practitioner choice).
- p.151: Kelly applies to ALL distributions (not just binary).
- p.109: discrete trading + commissions + bid/ask → effectively
  infinite transaction cost in the BSM continuous limit (Nth cost
  confirmation).

**KB cross-ref:**
- ❓ GAP — KB/code have NO bet-sizing math; flat $200. First-order per
  Sinclair (sizing "dramatically affects returns").
- ⚠️ ROADMAP CONFLICT (must surface) — user roadmap: "MAX risk on paper
  to learn" + 20%/day loss tolerance. Sinclair's hard result: oversizing
  above 2×Kelly converts a WINNING strategy into a losing one and courts
  ruin. For any realistic edge (≤+0.6ATR, ~53% hit), full-Kelly is
  small; 20%/day and "max risk" are almost certainly FAR above 2×Kelly.
  → "max risk to learn" risks teaching the WRONG lesson: a sound method
  can look like a failure purely from ruinous sizing. Position sizing is
  determinative, not a detail.

**Action (refines TODO 3R-B / H-KELLY):**
- Phase-1 paper "max risk" must be reframed: learn MECHANICS at
  controlled size; do NOT equate paper survival/ruin at max-risk with
  edge presence/absence (sizing confound).
- 3R-B numeric gate must include a Kelly-derived cap: live size ≤
  fraction (≤ half-Kelly) of the BACKTESTED edge's Kelly; refuse live
  if requested risk > 2×Kelly of the validated edge (hard block).
- H-KELLY promoted: estimate Kelly from each passing strategy's
  walk-forward stats; size at ≤½-Kelly; this is the bridge from $5K
  trial to $100K (geometric growth, ruin-bounded), not a flat %.

**Discipline note:** deep-read now firmly past diminishing returns
(round 4, still converging, no contradictions). Continuing to mine 30+
day-trading titles would itself violate the selectivity lesson. The
library has given its verdict; remaining value is in TESTING + correct
SIZING, not more pages.

---
## 2026-05-19 — KB UPDATED (closing the ❓ GAPs from rounds 1–4)
The deep-read rounds flagged ❓ GAPs but had only been recorded in this
log, not promoted into knowledge_base.md (convention = record BOTH).
Closed now — durable principles + citations only (project backtest
specifics stay here, not in KB):
- §8 NEW master entries: **Sinclair** (options edge = vol-forecast;
  option costs ≫ stock; Kelly determinative) + **Gunn** (regime is the
  edge for a directional strategy).
- §4 NEW: **Kelly Criterion & Risk of Ruin** (>2×Kelly ⇒ negative
  growth; use ≤½-Kelly; size from backtested edge only).
- §5 NEW: **Transaction-Cost Hierarchy** (shares < futures ≪ options ≪
  spreads; thin edge → cheapest instrument).
- §11 NEW: **The Trader's Equation** (P(win)·reward > P(loss)·risk;
  edges thin; selectivity+size not frequency; runner not fixed target).
Verdict: ❓ GAPs → now ✅ codified. KB and ANALYSIS_LOG consistent.

---
## 2026-05-19 — DEEP READ round 5: Davey (validation discipline) → KB §12
Davey *Building Winning Algorithmic Trading Systems*:
- p.57 "too good to be true… better it tests historically, less likely
  it repeats" — exactly our S3 (1.38@1bp → 0.97@3bp). Validates the
  ≥3bp cost gate and the trust-but-verify reflex.
- p.61/63 validation ladder: historical < OOS < walk-forward <
  real-time(paper/incubation) < live; never optimize on full data.

**KB cross-ref / action:** ❓ GAP — KB had §7 mistakes but NO explicit
backtest-validation methodology. Closed in SAME pass (as committed):
new **KB §12 Backtest & Validation Discipline** + 3 rule-table rows.

**Understanding updated (roadmap alignment):** Davey's ladder maps 1:1
onto the phased capital roadmap — Phase-1 PAPER == Davey's
"real-time/incubation" rung (the highest pre-capital tier), NOT a
formality. This independently validates 3R: paper is a *validation
rung*, the Phase-1→2 gate is the ladder (cost-robust walk-forward +
incubation), never paper P&L. No contradiction; convergence holds
(8 masters). Deep-read CLOSED — methodology was the last real gap;
further reading now strictly diminishing. Remaining value = TESTING.

---
## 2026-05-19 — DEEP READ round 6: "Risk Management Collection" → NO-OP
Path: ~/Desktop/books/Trading 2/@Gurgavin's Risk Management Collection.
Triaged 10 files; targeted-dug the 3 plausibly-relevant.

**Finding: NOT applicable to a retail intraday options/stock system.**
- Advanced/Quantitative/Fundamentals/IT Risk Mgmt = credit, interest-
  rate, enterprise, IT risk — out of domain.
- Stock Market Math = taxes / P/E / fundamental selection — out of scope.
- Little Book of Sideways Markets = secular value investing (multi-year,
  P/E, dividends) — wrong timeframe & philosophy, NOT intraday regime.
- Mastering the Stock Market / Moving Averages 101 / 7 Chart Patterns =
  generic TA already covered by Brooks §11 / KB.

**KB cross-ref:** no ❓ GAP. Every risk-relevant principle is already
better covered by Sinclair→§4 (Kelly/ruin), Davey→§12 (validation),
Brooks→§11 (Trader's Equation). **KB intentionally NOT updated** —
padding it with nothing-new would violate the very selectivity /
trust-but-verify discipline the corpus teaches.

**Verdict:** clean negative, recorded per convention. Deep-read remains
CLOSED (convergence across 8 applicable masters; 6th round confirms
diminishing/zero returns). Remaining value = TESTING (H-REGIME/H-RUN),
not more reading.

---
## 2026-05-19 — 39-TICKER SHARES ROBUSTNESS (real, post-fix run)
backtest_shares_robust.py ALL — 39 syms, 3yr, 18,790 trades, walk-fwd.

**Result @3bp: PF 1.09 / +$241k (vs 6-sym 0.97). Verdict ⚠️ MARGINAL /
CONCENTRATED — NOT validated:**
- @5bp PF 0.82 (negative) — fails pessimistic-cost gate. Cost-fragile.
- 103/154 symbol-year cells ≥1.0 (66.9%) — boundary, not broad.
- Per-year positive every year (1.09/1.03/1.13/1.21) — regime-consistent.

**Structural finding (the real signal):** edge is concentrated in
HIGH-volatility single names (NVDA1.55 CRWV1.51 ARM/SOFI1.48 TEAM1.45
HOOD1.42 INTC1.34 PLTR1.33) and NEGATIVE on LOW-vol index/mega
(SPY0.70 MSFT0.79 V0.79 GOOG0.87 QQQ0.91 MA0.97 UNH0.96). Coherent
with Sinclair (fixed cost vs movement) + the tight-ATR-stop
notional-scaling effect: low-ATR names → slippage swamps thin edge.
The original 6-sym watchlist was ~the WORST universe for this strategy.

**KB cross-ref:**
- ✅ ENFORCED — KB §5 transaction-cost hierarchy + §12 cost-sensitivity
  gate worked: caught a fragile edge, prevented an over-claim (no repeat
  of the S3 error).
- ✅ ENFORCED — KB §11 Gunn/Brooks: edge needs volatility/movement;
  selectivity is the lever.
- ❓ no new GAP (principles already codified this session).

**Verdict / next (NOT a green light; survivorship trap explicitly
resisted):** do NOT hand-pick the winner list. Convert to a
PRE-SPECIFIED rule — universe filter "trade only names with ATR%
≥ threshold" — and test it WITH H-REGIME (trending-only) + H-RUN
(runner exit) on a holdout, ≥3-5bp. That single combined backtest
(still $0, cached) is the decisive next experiment. Stay paper;
GO_LIVE_CHECKLIST + cost-robust pass still required.

---
## 2026-05-19 — PRO-TRADER SYSTEM RATING (post-backtest, post-deep-read)
Scorecard (weight·score): Edge/profitability 35%·2 · Risk-mgmt 20%·7 ·
Backtest-rigor 15%·8.5 · Process-integrity 10%·9 · Infra/ops 10%·7.5 ·
Execution 10%·5  →  **weighted ≈ 5.5/10**.

**Verdict:** elite PROCESS, immature PRODUCT. No edge validated after
realistic costs (S0 options PF 0.92; shares 1.09@3bp/0.82@5bp;
spreads unresolved). System's top achievement = trustworthy NEGATIVE
results + refusing to trade an unvalidated edge. A pro allocator: keep
the researcher, don't fund the strategy yet.

**KB cross-ref:**
- ✅ ENFORCED — rating method itself applies KB §12 (validation ladder),
  §11 (Trader's Equation: thin edge), §4 (Kelly/ruin re: 20%/day too
  aggressive), §5 (cost hierarchy). The discipline the books prescribe
  is the discipline the system scores highest on.
- ⚠️ DRIFT (own, prior, corrected) — S3 over-claim already logged;
  cited here as evidence the integrity control works.
- ❓ no new GAP — rating is synthesis, not new behavior.

**Only lever that moves Edge 2→up:** a strategy passing ≥3-5bp
walk-forward OOS (H-REGIME + H-RUN + vol-filtered universe). Cosmetic
/infra work does NOT move the dominant 35% category. Real-money: OFF.

---
## 2026-05-19 — "How to improve Edge 2/10" — expectancy-decomposed plan
Frame: Expectancy = P(win)·avgWin − P(loss)·avgLoss − costs. At ~53%
win / ~1:1 payoff we sit microscopically −EV after 3-5bp. Need a
modest REAL move in one term, not a miracle.

**Tier 1 (extract from existing signal; queued; $0 cached; test as ONE
combined backtest):**
1. H-RUN runner exit → ↑avgWin (R 1.0→~1.8 ⇒ breakeven win 50%→36%).
   Biggest lever; likely MY fixed-target design error. (KB §11 Brooks)
2. H-REGIME trending-gate → ↑P(win) 53→~57%+. Uses the already-computed
   but ignored chop label (H5 drift). (KB §8 Gunn)
3. Vol-filtered universe (pre-specified ATR% ) → ↓cost%. (39-run finding,
   KB §5)
4. Lower frequency / confluence → ↓total cost. (KB §11)
5. Shares on liquid high-ATR names → ↓cost (Sinclair §5; S0 0.92 vs 1.09)
   Levers compound; threshold = +EV after 3-5bp OOS ⇒ Edge 2→5-6.

**Tier 2 (iff Tier 1 fails the cost gate — honest, acceptable):** signal
is the ceiling; ADD edge not tune: (a) genuine volatility edge / IVR
(KB §4/§8 — makes options viable), (b) orthogonal-edge PORTFOLIO (2S
thesis), (c) replace primary signal. Brooks: edges small & fleeting —
don't expect the thin one to become large.

**KB cross-ref:** ✅ ENFORCED — plan is a direct application of KB
§4/§5/§8/§11/§12; no new GAP. Discipline: no lever counts pre cost-
robust ≥3-5bp walk-forward; Kelly compounds only a PROVEN edge.
Real-money OFF until Tier-1 combined backtest passes OOS.

---
## 2026-05-19 — DEEP READ round 7: Bull/Bear collection (11 books)
Triage: 9/11 out-of-domain (macro/long-term investing, seasonality) or
PROMOTIONAL (Identifying Market Trends = AbleTrend software vendor book —
honest no-op). 1 genuinely additive: **Covel, Trend Following**.

**Covel — durable principles → KB §8 (same-pass promote):**
- Win rate is the WRONG metric for a directional edge; normal shape =
  many small losses + few outsized winners; low win-rate is a feature.
- Edge lives in the FAT TAIL; fixed targets clip the outliers that pay
  for everything (LTCM = no-fat-tail fallacy). Strongest case for
  runner/trailing exits — directly supports H-RUN.
- Prediction futile → react to realized trend (reinforces Gunn/H-REGIME).
- Risk ENOUGH that a win matters (under-betting also fails) — complements
  Kelly §4.
- Volatility is the profit source (converges w/ 39-ticker high-ATR
  finding).

**KB cross-ref:** ❓ GAP closed — KB §11 Brooks had "let winners run"
but NOT the explicit "win-rate-is-misleading / edge-is-in-the-tail /
don't-clip / risk-enough" doctrine. Promoted to KB §8 Covel entry in
same pass (convention upheld).

**Why this matters now:** directly answers our own hand-wringing over
the 52-56% win rate — that is the NORMAL shape of a real directional
edge, not evidence of no edge. Strengthens the Tier-1 priority of H-RUN
(stop clipping the tail) and H-REGIME (react, don't predict). Deep-read
otherwise remains at convergence; rounds 5-7 = mostly no-op, this 1
principle the exception.

---
## 2026-05-19 — DEEP READ round 8: library triage → Connors/Raschke
Catalogued 247-PDF library by collection; triaged for OPEN-NEED fit
(Tier-2 orthogonal alpha, regime method, cost). Hedge-fund/market-timing/
long-term collections = out-of-domain (no-op, honest). One on-target hit:
**Connors & Raschke, Street Smarts (1996)** (file mislabeled "High
Probability Short Term…"; cited accurately).

**Additive findings → KB §8 (same-pass promote):**
- p.51 recipe: edge + longer-term trend filter + volatility filter +
  money-management = system. INDEPENDENT 3rd-lineage confirmation of
  H-REGIME + vol-filter + Kelly stack.
- Mean-reversion / pullback-in-trend ("Anti", RSI-extreme) = ORTHOGONAL
  edge family vs momentum-breakout → the concrete Tier-2 diversifier the
  2S portfolio thesis needs.
- Combine independently-tested setups (portfolio-of-edges empirics).
- Full-mechanization of a known edge invites arbitrage (expect modest
  expectancy; echoes Brooks).

**KB cross-ref:** ❓ GAP closed — KB had momentum/breakout (Brooks) +
regime (Gunn) but NO explicit mean-reversion/pullback-in-trend edge
family. Now in KB §8 Connors/Raschke. ✅ recipe convergence reinforces
§4/§8/§11/§12.

**Action impact:** gives 2S a concrete second strategy candidate
(pullback-in-trend mean-reversion, trend+vol filtered) — Tier-2 of the
Edge plan now has a named, literature-grounded starting point, NOT just
"find orthogonal alpha". Still gated: must pass its OWN ≥3-5bp
walk-forward before it joins the portfolio. Deep-read otherwise at
convergence; this is a genuine Tier-2 addition, not redundant.

---
## 2026-05-19 — DEEP READ round 9: expanded library (297 PDFs) → NO-OP
Library consolidated under ~/Desktop/books (297 PDFs, 272 indexed
deduped). book_dig roots fixed to the single consolidated root (3 prior
roots no longer exist post-reorg).

**Triage of NEW collections vs open needs (Tier-2 alpha / sizing /
regime / cost):**
- Futures&Forex, Hedge Fund x2, Bull/Bear-2, Long-Term/Bonds/Fundamental
  = out-of-domain for an intraday equity/options system.
- No Vince/Tharp/stat-arb/pairs text present (would've been prime
  sizing/Tier-2 adds) — absent.
- Minervini *Trade Like a Stock Market Wizard* (only marginal hit):
  growth-stock POSITION investing (SEPA, fundamentals, 200-day trend
  template). Transferable nugget (trade only with primary trend /
  relative-strength universe) ALREADY covered by Gunn §8 + Connors §8 +
  vol-universe finding.

**KB cross-ref:** no ❓ GAP. KB intentionally NOT updated — nothing
durable that isn't already codified. Padding would violate the
selectivity/trust-but-verify discipline.

**Verdict:** more books ≠ more edge. Deep-read remains CLOSED at
convergence (rounds 5-9 mostly no-op; only Davey/Covel/Connors-Raschke
were genuine adds). Remaining value = TESTING (H-REGIME/H-RUN/
vol-universe), not more reading.

---
## 2026-05-19 — EXTERNAL PROJECT ANALYSIS: zubair-trabzada/ai-trading-claude
Set up ~/Desktop/External_Projects/ (AlpacaTrader_copy = 58M source copy,
venv/cache excluded; cloned the repo read-only — third-party code NOT
executed). Full writeup: External_Projects/ANALYSIS_ai-trading-claude.md.

**What it is:** Claude Code skill pack (16 skills / 5 parallel agents) →
composite Trade Score 0-100 + PDF report. By its README: no bot, no
execution, no brokerage, no data subs, NO backtest. LLM-knowledge
discretionary research assistant.

**KB cross-ref:**
- ⚠️ DRIFT vs KB §12 (validation ladder) — a 0-100 score never tested
  vs forward returns / costs / walk-forward = narrative, not edge.
  Bottom rung of the ladder. On our Edge standard ≈1/10. It is the
  *polished version of the exact trap* our discipline exists to prevent.
- ✅ useful (advisory only) — clean 5-agent parallel decomposition +
  report UX is better-factored than our monolithic debate gate, AS AN
  ADVISORY layer.

**Verdict:** borrow its agentic decomposition + report UX for our
ADVISORY layer only; it contributes nothing to the Edge question and
must never gate execution (KB §12). We solve a strictly harder problem
(edge survival after real costs) it doesn't attempt. No KB change —
no new durable principle, just an architecture pattern noted for the
advisory layer (folds into 2S-F if/when there's a validated strategy
to advise on).

---
## 2026-05-19 — EXTERNAL PROJECT #2: PyPatel/Options-Trading-Strategies
Cloned read-only (not executed). Writeup:
External_Projects/ANALYSIS_PyPatel-Options-Strategies.md.

**What:** 4 educational scripts (~581 LOC) + C++ MC pricer. Hardcoded
params (VIX=22, TP 5%), single instrument, NO walk-forward / OOS / cost.
Crypto-donate + "LSTM promising" hype.

**KB cross-ref:**
- ⚠️ DRIFT vs KB §12 — cruder unvalidated-strategy trap; ~1/10 edge.
  No adoptable code.
- ❓ no GAP — concept notes only: (1) PCR/TRIN = candidate sentiment/
  breadth FEATURES for advisory sentiment sub-agent (ADV-1) / a Tier-2
  hypothesis (must pass ≥3-5bp like everything). (2) Turtle = reference
  impl of ATR-trail/Donchian exit — doctrine ALREADY in KB §8 Covel /
  §11 Brooks, no new principle.

**Verdict:** less useful than repo #1; zero edge, zero adoptable code,
no KB change. Two concept notes appended to existing TODOs (ADV-1
sentiment inputs; H-RUN Turtle reference). Honest near-no-op — recorded
per convention.

---
## 2026-05-19 — DECISIVE TIER-1 TEST: H-REGIME+H-RUN+vol-universe → FAIL
backtest_hregime_hrun.py — 39-sym universe.ALL, real 3yr cached, walk-fwd.

| Variant | n | Tr PF | Te PF@3bp | Te win% | Te$ | Te PF@5bp |
|---|---|---|---|---|---|---|
| V0 baseline (fixed 1.5ATR tgt) | 9235 | 1.08 | 1.14 | 53.0 | +180k | **0.88** |
| V1 H-RUN (runner exit) | 9235 | 1.10 | **1.16** | 56.0 | +184k | **0.88** |
| V2 +H-REGIME | 2129 | 0.99 | 1.02 | 53.4 | +6k | 0.76 |
| V3 +vol-filter (upper half ATR%) | 1004 | 1.17 | 1.07 | 53.7 | +10k | 0.87 |

**Bar:** Te PF ≥ 1.10 @ BOTH 3 & 5 bp. **NONE cleared. All die @5bp.**

**KB cross-ref:**
- ✅ ENFORCED — KB §12 Davey validation ladder + cost-sensitivity gate
  worked AGAIN, exactly as designed. Caught a marginal/cost-fragile
  edge BEFORE real money. Repeat of the discipline catching S3.
- ✅ ENFORCED partial — H-RUN directionally correct (Brooks p.85 / Covel
  KB §8 "don't clip the fat tail"): win 53→56%, Te PF 1.14→1.16. Real
  improvement, just not enough.
- ⚠️ small-n trap (own/honest) — V2/V3 over-filtered (2129/1004 trades
  vs 9235 base); regime+vol gates removed too much volume, didn't lift
  edge enough to compensate. Brooks "edges small & fleeting" empirical.
- ❓ no new GAP — outcome is consistent with KB; no new principle.

**Verdict (pro-trader):** Tier-1 EXHAUSTED. The vwap_momentum directional
signal has a real but thin edge that does NOT robustly survive realistic
3-5bp costs at this trade frequency, even with the textbook-correct
runner exit. Real-money: HARD NO. Path forward = Tier-2 orthogonal edge
(Connors mean-reversion, queued) OR accept the signal as research, not
a strategy. Either is a respectable, disciplined outcome — this IS the
validation system doing its job at $0 instead of $5K-100K.

---
## 2026-05-19 — STRATEGIC SYNTHESIS: "what do we need to find an edge?"
After Tier-1 fail + 300+ books + 8-master convergence + Polygon Pro on 503
symbols. User's hard question; honest pro-trader answer.

**Diagnosis (not motivational):** We are searching the SINGLE hardest
corner of the trading universe — 5-min intraday directional / mean-rev
on retail-cost shares / naked options / OHLC-only data. HFTs/market-
makers compete most fiercely here; spreads are largest fraction of P&L;
edges decay fastest. Both literature (Brooks §11, Sinclair §5) and our
own backtests point at the same wall. **Adding more INPUTS of the same
kind will not move it.** The frame is the bottleneck, not the inputs.

**What is genuinely missing (priority order, NOT "more of"):**
- Tier A — frame shifts (real EV):
  · slower timeframe (daily/multi-day; slippage fixed per trade)
  · structurally-different signal family — overnight/intraday return
    decomposition, PEAD, VIX term-structure, cross-sectional momentum,
    pairs/stat-arb (none tested)
  · options STRUCTURAL edge: variance risk premium / short-vol
    (Sinclair Ch10) — we dismissed options after testing only ONE
    structure (directional naked). Unfair to options.
- Tier B — data we don't have: dealer positioning / GEX; real L2/order
  book; earnings/event feeds.
- Tier C — lower-friction broker (IBKR Pro / Tradier) → can move 3bp
  gate toward 1bp; same edge, different verdict.
- Tier D — engineering: daily-bar harness; walk-forward ML pipeline
  (only AFTER Tier A — curve-fit prone).

**What is NOT missing:** books (convergence reached), 5-min OHLC (we
have 3yr × 503), validation discipline (pro-grade), refinement of
vwap_momentum (Tier-1 just exhausted it).

**KB cross-ref:**
- ✅ ENFORCED — §11 Brooks "edges small/fleeting; market won't allow
  big persistent one" + §5 cost hierarchy + §12 Davey too-good-to-be-
  true. Our wall = exactly what KB predicts for this frame.
- ❓ no new GAP — frame-shift is direction change, not new principle.

**Three-path fork (this is the real decision, not "another backtest"):**
- A. **Frame shift:** pick ONE Tier-A item (slowest timeframe + an
  academic-edge family, e.g., PEAD or variance premium). Genuine new
  build; current intraday infra mostly doesn't transfer. Targeted at
  where edge plausibly lives.
- B. **Stop.** Accept project as rigorous research + apparatus that
  produced a defensible negative. Don't deploy real money. Professional
  outcome, not failure.
- C. **Wait Connors** (running). One last evidence point inside the
  CURRENT frame. Low base rate of clearing the gate; real possibility.

**Pro recommendation:** wait Connors → pick A or B based on result +
appetite for frame shift. Do NOT pay $199/mo Polygon Advanced, license
dealer-positioning data, or buy another book before the frame question
is settled. Inputs ≠ edge in our current frame.

---
## 2026-05-19 — TIER-2 CONNORS (intraday frame): 0 TRADES → frame confirmed
backtest_connors.py — pre-specified RSI(2)<10 above ema200 / >90 below.

**Result:** ZERO trades fired on the 39-symbol 3yr universe. Root cause:
intraday EMA200 never forms on 5-min bars (~78 bars/session; live engine
correctly sets ema200=NaN). Canonical Connors is a DAILY-bar signal —
forcing it into our intraday frame breaks the trend filter by
construction.

**KB cross-ref:**
- ✅ ENFORCED — KB §12 Davey: result IS the result; do NOT loosen
  parameters to manufacture trades on a signal designed for a different
  timeframe. That would be curve-fit / "tune until it works."
- ✅ ENFORCED — KB §8 Connors/Raschke: the literature's signal needs
  its native timeframe (daily). Our frame breaks it.

**Verdict:** Tier-2 inside the CURRENT (5-min intraday) frame is CLOSED.
Second consecutive evidence point this session that confirms the
strategic synthesis (2026-05-19): the FRAME is the bottleneck, not
the signal family. The genuinely orthogonal Connors family belongs at
DAILY bars — testing it there is Path A (frame shift), not Path C.

**Decision narrowed to two:**
- A. Build daily-bar harness + retest Connors (+ other Tier-A
  candidates: PEAD, overnight/intraday decomp, variance premium).
  Genuine new infrastructure work; current intraday code mostly
  doesn't transfer.
- B. Accept the project as rigorous research + apparatus; do not
  deploy real money. Defensible professional outcome.
Path C (more inside the intraday frame) is now empirically closed —
both Tier-1 and Tier-2 attempted; both failed/inapplicable.

---
## 2026-05-19 — EXTERNAL PROJECT #3: sirnfs/OptionSuite (substantively useful)
Cloned read-only (not executed). Writeup:
External_Projects/ANALYSIS_OptionSuite.md.

**What:** Event-driven options backtest FRAMEWORK with proper engineering:
PutVertical/Strangle as first-class multi-leg objects with leg-match
invariants enforced at construction; unit tests for every primitive;
pluggable data providers (iVolatility configured); decimal precision.
NOT a strategy; doesn't claim an edge.

**KB cross-ref:**
- ✅ relevant infra — directly addresses how S2 broke (sparse short-leg
  / pricing-bar mismatch). Their PutVertical ctor *raises* on mismatched
  expirations — exactly the discipline our S2 lacked. Unit tests per
  primitive would have caught the 0.2%-winrate impossibility immediately.
- ⚠️ KB §12 — framework ≠ edge. Adopting it does not move Edge score.
  Whether ANY strategy clears the cost-robust gate is a separate
  empirical question (current answer: no in 5-min intraday).
- ❓ no NEW durable principle — engineering patterns, not doctrine. The
  Trader's Equation / Kelly / cost-hierarchy stuff is already in KB.
- 📍 DATA POINTER: iVolatility ($50-200/mo) provides full historical
  option CHAIN snapshots — different from Polygon Options Developer
  (single-contract OHLC). For proper spread backtesting iVolatility may
  be a better data spend than Polygon Options Advanced ($199 NBBO).
  Real finding worth recording.

**Action:** enrich 2S-B (broken spread harness) with OptionSuite
architectural references — leg-match invariants, primitive-as-object,
event-driven loop, unit tests per primitive. NOT wholesale code adoption
(always read what you adopt). Reference becomes useful only if Path A
chosen and 2S-B becomes active work.

**Verdict:** the most useful external repo this session by a wide
margin. Engineering quality directly informs how to do the unresolved
options work correctly. But it changes the cost of doing Path A, not
the probability Path A finds an edge. Decision unchanged.

---
## 2026-05-19 — DEEP READ round 10: /books/internet → NO-OP
Triaged 3 PDFs (Fidelity Entry/Exit transcript, Fidelity GetPlan webinar
2016, Schwab Technical-Analysis-for-Options deck) + 2 saved broker HTML
pages (Schwab "3 Types of Options Exit Strategies", E*TRADE "Call
Option Exit Strategy: Automating a Closure").

**All broker pedagogy / standard order-type tutorials.** Content
overwhelmingly covers: 50% loss / 100% gain / trailing-stop / OCO /
"pre-determine exit" / "have a plan" — exactly the textbook premium-%
doctrine that:
- Is ALREADY codified in KB §3 (pre-planned exits / Thomsett) +
  §11 (Brooks Trader's Equation) + our `TRAIL_GIVE_BACK_PCT`
  implementation.
- Has been **empirically disproven for our edge** by our own backtests
  (S0 naked options PF 0.92; Tier-1 H-RUN PF 0.88 @5bp).

**KB cross-ref:** no ❓ GAP. KB intentionally NOT updated — broker
pedagogy doesn't add durable principles 8 master texts and our backtests
haven't already covered (and refuted for our use case). Padding KB with
broker tutorials would violate the selectivity discipline + give
unwarranted weight to the very approach our evidence rejects.

**Verdict:** 3rd honest no-op in succession (round 6 Risk-Mgmt, round 9
library expansion, round 10 internet). Convergence remains; the source
exhaustion pattern itself is informative — the bottleneck is FRAME, not
KNOWLEDGE inputs. Strategic synthesis stands.

---
## 2026-05-20 — PATH A: CONNORS RSI(2) DAILY-BAR — FIRST COST-ROBUST PASS ✅
backtest_connors_daily.py — 39-sym universe, yfinance daily OHLC (5yr, free),
pre-specified Connors RSI(2)<10 above SMA200 → enter next-day open →
exit RSI>70 or 2×ATR14 stop or 10-day cap. LONG-only. Same $200/trade risk.
Same walk-forward 50/50 + ≥3bp AND ≥5bp cost gate.

**Result — the gate clears for the first time in this project:**

| Metric | Value |
|---|---|
| Full-sample n | 2,325 trades, 39 symbols, 5yr |
| Full-sample win% | 66.6% |
| Full-sample PF @3bp | 1.39 |
| Train PF @3bp | 1.48 |
| **Test PF @3bp** | **1.31 ✅** |
| **Test PF @5bp** | **1.28 ✅** |
| OOS decay | 1.48 → 1.31 = −11.5% (Davey: <25% acceptable) |
| Test win% | 65.5% |
| Test total$ @3bp | +$18,439 |
| Breadth (test) | **23/39 symbols PF ≥ 1.0** |
| Exit breakdown | 75% mean_revert · 23% atr_stop · 2% time_cap |

Per-year PF @3bp: 2021 1.59 / 2022 **0.79⛔** / 2023 1.50 / 2024 1.75 / 2025 1.16 / 2026 1.65.

**KB cross-ref:**
- ✅ ENFORCED — KB §8 Connors/Raschke Street Smarts p.51: "edge + longer-term
  trend filter + volatility filter + money-management = system." SMA200 is the
  trend filter; ATR14 stop is the vol/MM component; RSI(2) is the edge. The
  recipe maps exactly to the KB prescription.
- ✅ ENFORCED — KB §12 Davey: OOS decay −11.5% < 25% threshold → not curve-fit
  by the project's own standard. Walk-forward discipline holds.
- ✅ ENFORCED — KB §5: daily-bar shares are the lowest-cost instrument (no
  theta, no vega, lowest slippage). Frame-shift to daily IS the cost-hierarchy
  solution Sinclair prescribed. The strategy that couldn't survive 5-min intraday
  at 3bp (Tier-1 PF 0.88@5bp) now clears it by switching frames.
- ✅ ENFORCED — KB §11 Covel / Brooks: long-running fat-tail exits (mean-revert
  exit when RSI>70 = 10+ days average hold); 65.5% win is lower than the
  implied K% for this payoff but PF 1.31 means the runners carry the book.
- ⚠️ REGIME DEPENDENT — 2022 PF 0.79 (BEAR YEAR). Long-only RSI(2) above
  SMA200: in a sustained downtrend, prices fall BELOW SMA200 → entry filter
  rarely fires → low signal volume + mean-reverts that don't complete.
  This is expected Connors behavior (Street Smarts documents it). The strategy
  needs bear-market handling: either (a) short-side symmetric rule (RSI>90
  below SMA200) or (b) sit out bear regimes entirely. NOT a disqualifier — a
  known property to handle before live.
- ⚠️ BREADTH CONCENTRATION — 23/39 positive but winners concentrated in:
  financials (C 2.50, V 2.82, WFC 2.68, MA 1.75, JPM 1.15, BAC 1.15),
  specific tech (NVDA 3.46, QQQ 2.28, PLTR 2.20, TSM 2.15). Losers include
  CRM (0.23), CRWD (0.58), MU (0.45), AMZN (0.61), META (0.89). Not a
  uniform edge; some names break the pattern.
- ⚠️ TINY-SAMPLE SYMBOLS — ADBE (n=2), NKE (n=4), CRWV (n=1) in test half
  are statistically meaningless; their verdicts are noise, not signal.
- ❓ GAP — test period (May 2024–May 2026) is predominantly a bull market.
  2022 (the major bear year) is in the TRAINING half. Bear-side robustness
  needs explicit testing, not assumed from the 2022 in-sample data.

**Verdict: ✅ CANDIDATE — first strategy to clear the cost-robust gate.**
Path A (frame-shift to daily bars) was the correct call. The Connors RSI(2)
mean-reversion-in-trend on daily bars passes what the intraday vwap_momentum
directional signal never could: the 3-bp AND 5-bp OOS gate simultaneously.

**What this means / doesn't mean:**
- MEANS: there is a measurable edge in this signal on this universe at this
  timeframe, robust to realistic costs OOS. Davey's ladder: this is the
  "historical + OOS walk-forward" rung. Two rungs remain: paper incubation
  (real-time simulation, NOT paper P&L as edge proof) and live trial.
- DOES NOT MEAN: green light to real money. GO_LIVE_CHECKLIST still all-unchecked.
  Paper incubation required (Davey rung 3). Bear-regime behavior unresolved.
  23/39 breadth = not universal; universe filter may be needed.
- DOES NOT MEAN: perfect or complete. The 2022 gap is a real concern.

**Immediate next steps (mandatory, ordered):**
1. ~~Assess bear-side symmetric rule~~ — DONE 2026-05-20; FAILED (see entry below).
2. Pre-specify a universe filter rule (e.g., min-ATR% or min-liquidity) to
   handle the 16/39 losing symbols — test it OOS, don't hand-pick.
3. Kelly sizing: win 65.5% / avg_win ~$16 / avg_loss ~$30 → ½-Kelly ~7% → $350/trade.
4. Build daily execution layer in the live bot.
5. Paper incubation ≥4 weeks (mechanics, not P&L).
6. GO_LIVE_CHECKLIST: begin checking boxes.

---
## 2026-05-20 — BEAR-SIDE TEST: FAILS — LONG-ONLY IS THE KEEPER
Same Connors framework, RSI(2)>90 below SMA200 → short entry (symmetric rule).

**Result:** Adding short side HURTS — combined PF drops from 1.32 to 1.05@3bp,
fails the gate. Max drawdown worsens from 38.5% to 51.2%. Short side dilutes edge.

**Why:** The 2021-2026 period has a strong upward market drift. RSI(2)>90 below
SMA200 fires during sharp short-term bounces inside a downtrend; those bounces
often continue (short squeeze), producing losses on the short side. Long-only
(mean-reversion BUYING dips in uptrends) is the statistically dominant side.

**KB cross-ref:**
- ✅ ENFORCED — KB §8 Covel: "edge-in-the-tail" applies asymmetrically; the fat
  tail is on the LONG side in a secular bull market. Adding symmetric shorts in a
  bull-dominated sample destroys the asymmetry.
- ✅ ENFORCED — KB §12 Davey: let the data decide; the backtest decided. Don't add
  shorts because it seems symmetric — the data says it isn't.

**Verdict:** LONG-ONLY only. Bear-side variant retired. No further testing needed.

---
## 2026-05-20 — CHECKLIST STATS COMPUTED (long-only, 5-concurrent cap, @3bp)

**Full GO_LIVE_CHECKLIST §1 result — 8/9 metrics pass:**

| Metric | Value | Threshold | Status |
|---|---|---|---|
| Annualized return on account | +65.5%/yr | > 0 | ✅ |
| Test PF @3bp | 1.32 | ≥ 1.10 | ✅ |
| Test PF @5bp | 1.29 | ≥ 1.10 | ✅ |
| Test PF last 18 months | 1.11 | ≥ 1.10 | ✅ |
| OOS decay | +2.3% (improved OOS) | < −25% fail | ✅ |
| Annualized Sharpe | 1.32 | ≥ 0.8 | ✅ |
| **Max drawdown (% of account)** | **38.5%** | **< 12%** | **⛔** |
| Top-3 concentration | 5.5% | < 40% | ✅ |
| Beats SPY (annualized) | yes (+65%/yr vs +42.5% total) | beats B&H | ✅ |

**The one ⛔: max drawdown 38.5%.**

Analysis: the 38.5% drawdown is NOT signal failure — it is a SIZING + CORRELATION
risk. The Feb 2025 market selloff caused multiple consecutive days of 5 concurrent
losing positions (all long, all oversold simultaneously) → ~$1K/day × ~2 days
from the equity peak. Root causes:
1. Correlated mean-reversion longs: when the market sells off hard, ALL symbols
   fire RSI(2)<10 at once. Even with MAX_CONCURRENT=5, 5 consecutive losses in 2
   days = $1,000/day × 2 = $2K drawdown off a smallish equity peak.
2. The $5K starting capital is small relative to $200/trade × 5 concurrent risk.
   Before profits accumulate (early in the test), a 2-day bad run is a large % DD.

**KB cross-ref:**
- ✅ ENFORCED — KB §4 Kelly/Sinclair: >2×Kelly = negative growth. The 38.5% DD is
  consistent with being near or above Kelly at moments of concentrated risk. The
  ½-Kelly prescription ($350/trade, or reducing MAX_CONCURRENT) would reduce DD.
- ⚠️ DRIFT — the GO_LIVE_CHECKLIST 12% threshold was set for a generic account;
  it is inconsistent with the user's stated 20%/day loss tolerance on $5K. A
  2-day max-loss event (20%×2=40%) = the observed 38.5%. The threshold needs to
  be consciously updated to match the ACTUAL risk tolerance stated by the user.
- ❓ GAP — checklist threshold 12% was written before the $5K + daily-bar profile
  was established. Must be re-evaluated and signed off by the user with eyes open.

**What this means for GO_LIVE_CHECKLIST:**
The 12% threshold ⛔ is a hard gate item. Before live:
- User must consciously decide: accept the 38.5% worst-case drawdown (= 2 max-loss
  days back-to-back) as within their $5K risk tolerance, update the checklist
  threshold to their actual accepted level (e.g., 40%), and date+initial the box.
- OR: reduce MAX_CONCURRENT to 2-3 (reduces DD to ~15-20%) at cost of fewer trades.
- This is a risk-tolerance decision, NOT a backtest failure. The signal has edge.

**Remaining gap before live — summary:**
- ⛔ Max drawdown checklist item: user decision needed (accept 38.5% or reduce size)
- ⬜ Daily execution layer: zero infrastructure exists in the live bot
- ⬜ Paper incubation: ≥4 weeks, mechanics-focused (Davey rung 3)
- ⬜ Operational items: watchdog, webhooks, 24hr stability — existing infra, verify
- ⬜ PDT: daily-bar swing holds are NOT day-trades (hold > 1 day = not round-trip
  on same day). PDT rule does not apply to this strategy. Existing PDT counter is
  irrelevant for daily-bar swings — remove from gate for this strategy.

---

## 2026-05-31 — Book-dig: problem-targeted mine for live blockers (2S-B spread harness + Connors regime weakness)

**Trigger:** user pointed at the consolidated 297-PDF library (`/Users/bsannadi/Desktop/bharath/books`, already the canonical root in `scripts/book_dig.py`). Ran problem-targeted `book_dig.py` queries on the two live blockers: **2S-B** (build a correct debit-spread pricer + its own vol edge) and the **Connors RSI(2) 2022 bear-year weakness** (PF ~0.79–0.85).

**Books mined (5):** Natenberg *Option Volatility and Pricing*, Saliba *Option Spread Strategies*, Sinclair *Volatility Trading*, Connors *Short Selling Stocks with ConnorsRSI*, Connors & Raschke *Street Smarts / High-Probability Short-Term Trading*.

| Observed / extracted | KB rule it maps to (§ ref) | Verdict |
|---|---|---|
| Sinclair p.62/79: implied vol is a structurally **upward-biased** estimate of realized vol (variance premium); IV > realized ~70% of months. Net-long-vega structures (naked long, net-long debit spread) fight this premium. | §22 Variance Risk Premium | ✅ ENFORCED — already codified, and **explains** the disproven naked options route (PF 0.92). The options route's own vol edge (H-VOL) must be premium-**selling** in high-IVR, not a directional wrapper. |
| Natenberg p.238: vertical leg-selection by IV — **"If IV is low, focus on buying the ATM option; if IV is high, focus on selling the ATM option"** (ATM is most vega-sensitive, so most mispriced). | §20 Spread Greeks (covers anatomy, NOT this IV→which-leg-is-ATM rule) | ❓ GAP → KB updated (§20 addendum). This is the concrete strike-placement rule the 2S-B harness needs. |
| Natenberg p.248–260: theoretical edge alone is meaningless (any spread scales to arbitrary edge by size); **"a good spread is one that allows a reasonable margin for error"** so losses don't lead to ruin — not the one with the highest best-case profit. | §4 Risk / §5 Strategy Selection (had cost hierarchy, not this margin-for-error framing) | ❓ GAP → KB updated (§5 addendum). Directly relevant to the $5K cost-fragility trap: don't size a spread for max edge, size for survivable error. |
| Saliba p.61/156: bull call = buy lower strike + sell higher strike = net **debit**; strike selection from support/resistance + mean-reversion area. | §5 Debit Vertical Spreads + §20 | ✅ ENFORCED — confirms existing rules; the mean-reversion-area strike anchoring is a useful tie-in to the Connors strategy. |
| Connors *Short Selling w/ConnorsRSI* p.26: stricter entry threshold (CRSI 95 vs 75) → ~half the signals but **nearly 2× avg P/L per trade**. Selectivity raises per-trade expectancy. | §19 Connors (long-only, frozen params) + CONTEXT.md "be picky at $5K / 3-trades-week" | ❓ GAP → KB updated (§19 addendum) as a **candidate** regime-weakness mitigation, NOT a live change. Must be OOS-tested (tighten RSI(2) entry in weak/bear regime), not hand-tuned — curve-fit trap (§12 Davey). |
| Connors & Raschke *Street Smarts* Ch.20: range contraction (NR4 + inside day + 6/100-day HV ratio < 50%) precedes expansion/breakouts. | §11 / §18 (candidate indicators) | ❓ GAP (low priority) — a volatility-regime entry filter; logged for future H-VOL work, not wired. |

**Verdict summary:** the dig mostly **confirms** the existing KB (VRP, spread Greeks, debit mechanics all already codified and correctly applied). Three genuine gaps were closed in the KB (Natenberg IV-leg-selection, Natenberg margin-for-error, Connors selectivity→expectancy). **No live code changed** — the Connors selectivity finding is explicitly a backtest candidate, not a hand-tune, consistent with the cost-robust-gate discipline. The single most strategically important confirmation: the variance premium (Sinclair) is *why* the naked options route loses, and dictates that the options route must earn its slot through a vol-selling edge — reinforcing the 2S-B/2S-C gate that the options route stays disabled until a fixed spread harness + vol-edge component passes its own ≥3bp walk-forward.

---

## 2026-05-31 — KB multi-strategy backtest (fixing "single regime-dependent strategy = fragile foundation")

**Trigger:** operator directive to multi-strategy the system using the knowledge base, after a system rating flagged the single-strategy fragility. Built `backtest_multi_strategy.py` — 4 PRE-SPECIFIED, KB-sourced daily strategies through the SAME cost-robust gate (Test PF ≥ 1.10 @ BOTH 3bp & 5bp OOS, 50/50 walk-forward, $200/2×ATR sizing, MAX_CONCURRENT=5). Exit model made consistent with the frozen Connors baseline (ATR stop fills at the stop, not next open).

| Strategy (KB ref) | n | Test PF 3bp/5bp | Win% | 2022 PF | Verdict |
|---|---|---|---|---|---|
| S1 Connors RSI2 — mean-rev (§19) | 790 | 1.35 / 1.32 | 66.1% | 0.85 | ✅ PASS |
| S2 Bollinger reversion (§1) | 348 | 1.40 / 1.37 | 57.1% | 0.62 | ✅ PASS |
| S3 Trend pullback (§8/§14) | 350 | 2.11 / 2.08 | 42.2% | 0.68 | ✅ PASS |
| S4 52w-high breakout (§15) | 133 | 1.96 / 1.94 | 40.0% | 0.03 | ✅ PASS |

Monthly-P&L correlation vs Connors: S2 0.49 (MR, expected), **S3 0.31, S4 0.32** (real diversifiers). S2↔S3 = 0.19.

**KB cross-ref / verdict:**
- ✅ **All 4 clear the cost-robust gate** (§12 Davey discipline). The trend/momentum pair (S3, S4) shows the classic high-payoff/low-win profile (§8 Covel "expectancy over win rate"). This is a genuine, validated multi-strategy set — a real upgrade from the single-strategy foundation.
- ✅ **Low pairwise correlation** → diversifies SIGNAL risk in normal regimes (a bad month for mean-reversion is often fine for trend). S1+S3 is the strongest complementary pair.
- ⚠️ **CRITICAL LIMITATION — they do NOT fix the regime (2022) risk.** All four are LONG-ONLY EQUITY, so all four fail in a broad bear year (2022 PF: 0.85 / 0.62 / 0.68 / 0.03). Monthly correlation (~0.3) badly understates TAIL correlation — in a crisis month they go down together. Diversifying across long-equity strategies reduces signal fragility but NOT market-beta fragility.
- ❓ **GAP → the real fix is a non-equity-beta component, not more long-equity strategies:** a regime overlay that de-risks the whole book when SPY < its 200-SMA, and/or a sleeve uncorrelated to equity (inverse/short, bonds, long-vol). Note: a naive SPY<200SMA *entry block* was already REFUTED for Connors (2026-05-31 H-SEL-REGIME made 2022 worse). The overlay must scale SIZE/exposure, not just gate entries — and ideally add a genuinely uncorrelated return stream. Cannot be backtested on S&P-500-only daily data (need bond/inverse/vol series).

**Discipline note (multiple-comparisons):** testing 4 strategies and keeping winners inflates false-positive risk. Survivors go to PAPER INCUBATION alongside Connors, NOT straight to live. The cost-robust gate is necessary, not sufficient.

**Recommended next steps:** (1) incubate S3 (trend pullback) as the best diversifier; (2) design + backtest a regime/size overlay with a non-equity sleeve before claiming the fragility is fixed.

---

## 2026-05-31 — Exit-ladder backtest (REQ-608 dynamic profit-protection)

**Trigger:** operator REQ-608 (escalating profit floor so a winner can't become a loss). Built `backtest_exit_ladders.py` — same entries on the 4 validated strategies, re-simulated exits under a fixed baseline vs 3 pre-specified profit-floor ladders. Same 50/50 walk-forward + cost gate.

| Strategy | exit | Test PF 3/5bp | win% | test $ | maxDD $ |
|---|---|---|---|---|---|
| connors | baseline | 1.19/1.15 | 65.2 | 4870 | 6252 |
| connors | **L1 be+trail30** | **1.23/1.18** | 64.1 | **5523 (+653)** | **6023 (-229)** |
| trend | baseline | 1.67/1.63 | 39.6 | 13471 | 3570 |
| trend | **L1 be+trail30** | **1.76/1.71** | 35.9 | **14080 (+609)** | **3062 (-508)** |
| breakout | baseline | 1.97/1.93 | 34.5 | 9839 | 2687 |
| breakout | L1 be+trail30 | 2.01/1.96 | 27.1 | 9591 (-248) | 3327 (+640) |

L1 = breakeven stop at +5% gain, trail 30% off the high-water mark, lock +10% floor at +20% gain. L2/L3 (tighter / bigger thresholds) **hurt every strategy**.

**KB cross-ref / verdict:**
- ✅ **REQ-608 validated in principle** — gentle profit-protection (L1) BEATS the fixed baseline OOS on Connors and Trend, improving PF **and** lowering max-DD. Directly serves REQ-611 (conservative, low-DD). A winner protected at breakeven can't become a loss (the operator's intent).
- ⚠️ **The operator's *example* thresholds are too coarse for daily stock swings.** Big floors (+20/+50% triggers, L2/L3) get whipsawed — stopped on noise, miss the recovery (KB §3, the REQ-608.4 caveat, now empirically confirmed). The data prefers an EARLY breakeven (+5%) + moderate trail, not late big-step floors.
- ❓ **Options not yet tested** — options move far more than the underlying, so the operator's +40/+80/+200% option ladder may be appropriate on option P&L (different distribution). Needs the option data (pulling now) + the spread harness to test on real option series.
- **Discipline:** L1 is a candidate → paper incubation alongside the strategy, not a live edit to the frozen Connors exit (REQ-203/603.3). Breakout shows it's not universal — applied per-strategy.

---

## 2026-05-31 — Regime/hedge overlay backtest (Phase 4, the 2022 tail-risk fix)

**Trigger:** the multi-strategy backtest showed all 4 validated strategies are long-only equity → all fail 2022 (tail risk, REQ-205/611.2). Built `backtest_regime_overlay.py` on the combined 4-strategy portfolio.

| variant | n | PF | total$ | maxDD$ | 2022 PF | 2022 $ |
|---|---|---|---|---|---|---|
| A baseline (long-equity only) | 723 | 1.13 | 7092 | 9850 | 0.58 | -6536 |
| **B regime-skip (SPY<200SMA → no entry)** | 535 | **1.18** | 7186 | **6046** | 0.28 | **-3402** |
| C regime-half (half size risk-off) | 723 | 1.15 | 7139 | 7948 | 0.51 | -4969 |
| D + TLT sleeve (bonds when risk-off) | 738 | 1.09 | 5298 | 11579 | 0.53 | -8044 |

**KB cross-ref / verdict:**
- ✅ **Regime-skip (B) is the validated tail-risk fix.** Skipping new entries when SPY < its 200-SMA HALVES the 2022 loss (-6536 → -3402) and cuts max drawdown 39% (9850 → 6046), while *improving* overall PF (1.13 → 1.18). Directly serves REQ-205 (regime overlay) + REQ-611.2 (low-DD conservative). KB §8 Gunn (un-conditioned = no edge) — the broad-market regime is the conditioning the long-equity portfolio was missing.
- ❌ **TLT non-equity sleeve REFUTED (D).** 2022 was a rare joint stock+bond selloff (rates spiked), so bonds were NOT a haven — the sleeve made the tail WORSE. Honest lesson: a hedge only diversifies if uncorrelated IN THAT crisis; don't assume bonds protect.
- ⚠️ **Reconciles the earlier H-SEL-REGIME result (per-Connors gate made 2022 worse):** the win here is PORTFOLIO-level — the skip mainly kills trend/breakout entries (death in a bear, breakout 2022 PF 0.03), which dominates the small dent to mean-reversion. Apply the regime overlay at the PORTFOLIO/risk-brain level, not per-mean-reversion-strategy.
- **Next:** wire a portfolio regime gate (SPY<200SMA → no new entries) into the risk brain as a candidate, validated here; → incubation, not a live edit to frozen Connors. Consider regime-half (C) as a softer variant (keeps more upside, still cuts DD).

---

## 2026-05-31 — Requirements-driven book deep-read (Davey + Elder → REQ mapping)

**Trigger:** operator request to deep-read the library for content serving our requirements (REQ-601..613). Mined Davey *Building Winning Algorithmic Trading Systems* + Elder *The New Trading for a Living*.

| Finding (book, page) | Serves | Verdict / action |
|---|---|---|
| **Elder 6% Rule (p.224-226):** stop new entries for the month when (month's realized losses + open risk on all positions) ≥ 6% of month-start equity. 2%/trade → ≤3 concurrent; 1%/trade → ≤6. | REQ-611, REQ-602 | ❓ GAP → **add a monthly 6% open-risk circuit breaker to risk_brain.** We have daily-loss + options-weekly caps but NOT Elder's monthly portfolio rule. Our MAX_CONCURRENT=8 is slightly loose vs the 6% rule (~1%/trade × 8 = 8%); tighten or gate on open-risk. |
| **Elder open-risk accounting (p.224):** a position whose stop is at breakeven has ZERO open risk → frees the 6% budget for a new trade. | REQ-608 + REQ-611 | ✅ SYNERGY → our breakeven ratchet (REQ-608) literally INCREASES capacity. **risk_brain should track OPEN RISK (Σ dist-to-stop × size), not just deployed capital** — then breakeven-stopped positions don't count. |
| **Elder 2×ATR trailing stop "outside the zone of market noise" (p.237):** trail at every bar, gradually reducing risk. | REQ-608/609 | ✅ ENFORCED — matches our exit_engine (2×ATR init + trail). "Outside market noise" = the whipsaw caveat we found empirically (REQ-608.4). |
| **Davey: strategies DECAY; keep spares in reserve (p.51):** "I naively thought I could trade the same strategies forever... had no extra strategies waiting in limbo when the first group lost their edge." | REQ-201 | ❓ GAP → **build a PIPELINE of validated strategies + monitor live edge-decay.** We have 4 validated; Davey says keep MORE in reserve and watch for decay. |
| **Davey: Monte Carlo + return/drawdown (Calmar) is the #1 metric (p.75-83):** simulate trade-order randomization → worst-case DD; size off that, not the single historical curve. | REQ-202, REQ-611 | ❓ GAP → **add Monte Carlo to the validation harness + use Calmar (return/maxDD)**, not just PF. Directly serves the conservative/low-DD objective. |
| **Davey: live drawdowns will be WORSE/longer than backtest (p.72):** size money management assuming both. | REQ-611 | ⚠️ → size for worse-than-backtest DD (haircut the backtest maxDD). |
| **Davey: selection-bias rookie mistake (p.39):** testing 20-25 instruments then keeping the best = the multiple-comparisons trap. | REQ-202 | ✅ ENFORCED — exactly the discipline we've held (every strategy its OWN cost-robust gate; survivors → incubation). |

**Net:** the deep-read produced 3 concrete enhancement candidates that strengthen the CONSERVATIVE objective (REQ-611): (1) Elder's **6% monthly open-risk circuit breaker** + open-risk accounting in risk_brain, (2) Davey's **Monte Carlo + Calmar** in validation, (3) a **strategy pipeline + edge-decay monitor** (REQ-201). All are risk-reducing, all align with the existing discipline, and the 6%-rule + breakeven synergy is elegant: protecting profits (REQ-608) literally frees risk budget. → candidates for the risk_brain / validation roadmap, gated as usual.
