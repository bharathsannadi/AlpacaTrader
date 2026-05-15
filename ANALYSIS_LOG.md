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
