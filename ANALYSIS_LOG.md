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
