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
