# Requirements — AlpacaTrader

Single source of truth for what the system **must** do. Each requirement has an
ID, a statement, a rationale/source, and a status. Keep IDs stable; append new
ones, don't renumber.

**Status legend:** ✅ implemented · 🔄 in progress · ⬜ planned · 🔒 gated (blocked on a gate)

> ⚠️ Seeded 2026-05-31 from decisions made this session. **Add your own
> requirements below the relevant section** (or a new section) and I'll wire
> them up + update status.

---

## 1. Safety & execution

| ID | Requirement | Rationale / source | Status |
|----|-------------|--------------------|--------|
| REQ-001 | **Dry-run defaults ON** — no real order is sent unless the operator explicitly disables it | Operator directive 2026-05-31 (max safety while iterating) | ✅ |
| REQ-002 | **Paper mode is the default**; live trading requires a fully-signed `GO_LIVE_CHECKLIST.md` (hard runtime gate) | §P1-F | ✅ |
| REQ-003 | **Live mode forces the disciplined risk profile** (4%/20%/20%); UI risk overrides are ignored in live | 3R-A risk-mode separation | ✅ |
| REQ-004 | **Every trade must clear the KB-principles gate** (≥ 60% match) before placement | Operator: "always trade using the knowledge base / max principles" | ✅ |
| REQ-005 | **Every trade must clear the bull/bear debate gate** (fail-closed) when enabled | Operator: "debate gate while taking trades" | ✅ |
| REQ-006 | **Auto-Execute is armed by default but safe** — bounded by dry-run + KB/debate gate | Operator directive 2026-05-31 | ✅ |
| REQ-007 | **Hard caps**: ≤ 3 auto-executions/day, daily-loss circuit breaker auto-disarms on breach (per-trade $ caps are now route-specific — see REQ-605) | KB §4 / Kelly | ✅ |
| REQ-008 | **Never leave a naked leg** — roll back partial spread fills | screener_executor STO failure path | ✅ |
| **REQ-605** | **Options route risk limits: max $500 risk per trade AND max $1,500 risk per week** (= 3 max-risk options trades/week) | Operator requirement #5 | ⬜ planned |
| REQ-605.1 | The risk brain **tracks cumulative options risk over the week** and refuses a new options entry that would push the week's deployed risk past $1,500 | weekly cap | ⬜ |
| REQ-605.2 | **$500 is the per-trade hard ceiling**; ½-Kelly may size *below* it (current `RISK_BUDGET` $400 sits under the cap) — the cap never increases sizing, only bounds it | REQ-007 / Kelly | ⬜ |
| REQ-605.3 | "Per week" = **rolling 5 trading days / Mon–Fri** (⚠️ confirm which) | definition | ⬜ confirm |

## 2. Universe

| ID | Requirement | Rationale / source | Status |
|----|-------------|--------------------|--------|
| REQ-101 | **Stock-trading universe = 74** (40 stocks + 34 long-only ETFs) | Operator 2026-05-31 | ✅ |
| REQ-102 | **Options universe = all S&P 500 + all ETFs** | Operator 2026-05-31 | 🔄 (data pull) |
| REQ-103 | **Priority order: ETFs → large-cap stocks → small-cap stocks** (see REQ-604) | Operator 2026-05-31 | 🔄 (data pull ✅, trading ⬜) |
| REQ-104 | **Inverse/vol ETFs (SH/PSQ/SDS/SQQQ/VIXY) excluded from long-only** — reserved for the hedge/regime overlay | structural decay; ETFS_HEDGE | ✅ |

## 3. Strategy & validation

| ID | Requirement | Rationale / source | Status |
|----|-------------|--------------------|--------|
| REQ-201 | **Multi-strategy portfolio**, not a single strategy | system-rating risk #3 | 🔄 (4 validated, not yet live) |
| REQ-202 | **Every strategy must pass its OWN cost-robust walk-forward** (Test PF ≥ 1.10 at BOTH 3 bp AND 5 bp OOS) before enabling | §12 Davey — non-negotiable | ✅ (gate enforced in backtests) |
| REQ-203 | **Validated strategies go to paper incubation (≥ 4 weeks) before live**, params frozen during incubation | §19, Davey ladder | 🔄 (Connors incubating) |
| REQ-204 | **Strategies are sourced from the knowledge base** (each cites its KB section) | Operator: "multi strategy using knowledge base" | ✅ (S1-S4 KB-cited) |
| REQ-205 | **Address regime/tail risk with a non-equity-beta sleeve + size overlay** (long-only equity strategies all fail 2022) | ANALYSIS_LOG 2026-05-31 | ⬜ |

## 4. Data archival

| ID | Requirement | Rationale / source | Status |
|----|-------------|--------------------|--------|
| REQ-301 | **Archive 5yr Polygon data before subscription lapse (2026-06-16)** | Operator deadline | 🔄 |
| REQ-302 | Daily stock bars for all 503 S&P 500 + all ETFs | — | ✅ |
| REQ-303 | Options (5yr daily, monthly, ±15% ATM, calls+puts) — ETFs first, then S&P 500 by liquidity | REQ-102/103 | 🔄 |
| REQ-304 | Minute bars (RTH) for ETFs + top-100 liquid stocks | lower priority (intraday no validated edge) | 🔄 |

## 5. UI / observability

| ID | Requirement | Rationale / source | Status |
|----|-------------|--------------------|--------|
| REQ-401 | **Confidence % column** in both screener tables = KB-principles match, gate-blocked rows flagged | Operator: "confidence column so I can see and buy" | ✅ |
| REQ-402 | Screener tables show **up to 15 rows** each | Operator: "max 15 items" | ✅ |
| REQ-403 | EOD review split into **MECHANICS vs EDGE** scorecards (paper P&L ≠ edge) | 3R-C | ✅ |
| REQ-404 | Persistent **mode badge** (PAPER max-risk / LIVE disciplined) + dry-run indicator | 3R-A.4 | ✅ |
| REQ-405 | Daily positions panel + paper-incubation tracker | PA-UI | ✅ |

## 6. Security & ops

| ID | Requirement | Rationale / source | Status |
|----|-------------|--------------------|--------|
| REQ-501 | **No secrets hardcoded in source** — keys from `.env`/env only | risk #2 | ✅ (code) / ⬜ rotate exposed Polygon key |
| REQ-502 | Process supervision (launchd + watchdog) with meaningful `/health` | §P2 #17 | ✅ |
| REQ-503 | Append-only failure-mode + gate-fire + slippage-vs-model logs | 3R-C | ✅ |

---

## 7. Instrument routing (dual-instrument)

| ID | Requirement | Rationale / source | Status |
|----|-------------|--------------------|--------|
| **REQ-601** | **The system shall trade BOTH options and stocks, choosing the instrument per signal based on knowledge-base rules** (a shared signal core → KB-driven instrument router → shared risk brain) | Operator requirement #1; KB §5; TODO "2S dual-instrument" | ⬜ planned (router not built) |
| REQ-601.1 | **Routing policy is KB-driven, not hand-picked**: a thin *directional-only* edge routes to **shares** (cheapest vehicle — KB §5 transaction-cost hierarchy); an option is used only when a **volatility edge** is also present (KB §2/§5, Natenberg/Sinclair) | KB §5 / §22 | ⬜ |
| REQ-601.2 | **Option structure by IVR**: IVR < 30 → naked long; IVR 30–50 → debit spread; IVR > 50 → spread only (no naked) | KB §2/§5 | 🔄 (daily_trader has IV/HV logic; not wired to a router) |
| REQ-601.3 | **Account-size affordability check**: at $5K, route to shares (or skip) when the option premium can't fit the $400 risk budget | CONTEXT trader profile | ⬜ |
| REQ-601.4 | **Each route gated independently**: a route (shares or options) only goes live after ITS OWN cost-robust ≥3bp walk-forward passes, plus the KB-principles + debate gates | REQ-202, 2S-G | 🔒 (options route blocked on 2S-B spread harness) |

**Current state (honest):** the two instruments exist *separately* —
`daily_trader.py` has an `INSTRUMENT = "options" | "shares"` global toggle, and
`screener_executor` places options orders — but there is **no per-signal router**
that applies the KB §5 decision framework to pick the vehicle. Building REQ-601 =
the project's **2S-D** (router policy) + **2S-E** (route abstraction:
`shares_executor` / `options_executor` behind one signal+risk core). The options
side also depends on the **2S-B** spread-data harness being fixed first.

### Capital allocation across routes

| ID | Requirement | Rationale / source | Status |
|----|-------------|--------------------|--------|
| **REQ-602** | **Split the paper account: $95,000 reserved for STOCK trading, the remainder for OPTIONS trading** | Operator requirement #2 | ⬜ planned |
| REQ-602.1 | The risk brain **tracks deployed capital per route** and refuses a new entry that would exceed that route's sleeve | shared risk brain | ⬜ |
| REQ-602.2 | Per-route position sizing respects its sleeve (stocks sized within $95K; options within the remaining ~$12.8K) | REQ-007 sizing | ⬜ |

**Note / reconciliation:** the live paper account is **~$107,846**, so "the rest"
for options ≈ **$12,846** today (it floats with total equity). This is distinct
from the **$5,000 live-trial profile** documented in CONTEXT.md — that profile is
for the eventual *real-money* Phase-2 trial, NOT this paper account. The $95K/rest
split applies to the current paper book. ⚠️ At ~$12.8K, options sizing must respect
the per-trade caps (≤ $400 risk, REQ-007) and affordability (REQ-601.3).

---

## 8. Entry & exit criteria (principle-based)

| ID | Requirement | Rationale / source | Status |
|----|-------------|--------------------|--------|
| **REQ-603** | **Entry and exit criteria shall be PRINCIPLE-BASED, not fixed thresholds** — each criterion is derived from and traceable to a knowledge-base principle, and adapts to context (regime, IVR, volatility, structure) rather than using one rigid number | Operator requirement #3; KB §2/§3/§5/§8 | 🔄 (partial) |
| REQ-603.1 | **Every entry/exit criterion cites its KB principle** (regime filter §8, IVR routing §2/§5, VSA §10, profit-target/theta/earnings/VIX-spike exits §3/§23) and is surfaced to the operator (e.g. the confidence tooltip already lists matched principles) | KB-principles gate (REQ-004) | ✅ (gate) / 🔄 (exits) |
| REQ-603.2 | **Criteria adapt to context**: e.g. stop/target scale with ATR & volatility regime, IVR drives structure, exit triggers on principle events (80% of max profit, theta acceleration, D-2 earnings, VIX spike) — not a single fixed stop/target | KB §3/§5/§22/§23 | 🔄 (some exits exist) |
| REQ-603.3 | **⚠️ GUARDRAIL — principle-based ≠ discretionary or un-validated.** Any adaptive criterion must be PRE-SPECIFIED and pass the cost-robust ≥3bp/5bp walk-forward before going live. "Not fixed" must not become "curve-fit / tuned on hindsight." | §12 Davey; H-SEL-REGIME refutation 2026-05-31 | 🔒 standing |

**Current state (honest):** the system is **mixed**. Principle-based already:
KB-principles confidence gate (REQ-004), IVR→structure routing, VIX gate, the
SMA200 regime filter, the KB-grounded exit suite (80% profit close, 7-DTE exit,
D-2 earnings exit, VIX-spike→spread). Still **fixed** in the validated daily
strategy: RSI(2)<10 entry, 2×ATR stop, 50% premium stop, 10-day time cap — these
are deliberately FROZEN during paper incubation (changing them mid-incubation
breaks REQ-203). REQ-603 = migrate the *fixed* knobs to principle-derived,
context-adaptive forms **via backtested variants**, not live hand-tuning.

---

## 9. Prioritization tiers

| ID | Requirement | Rationale / source | Status |
|----|-------------|--------------------|--------|
| **REQ-604** | **Process/trade in priority tiers: (1) ETFs → (2) large-cap S&P 500 stocks → (3) small/mid-cap S&P 500 stocks.** Applies to data pulls, signal scanning, and trade prioritization when capacity-limited | Operator requirement #4 | 🔄 |
| REQ-604.1 | **Data pull** follows the tiers (ETFs first, then stocks by size) | Polygon archival | ✅ (ETFs first, then S&P ranked by dollar-volume ≈ size) |
| REQ-604.2 | **Trade/capacity prioritization**: when concurrent slots or a capital sleeve are limited, fill ETF signals first, then large-cap, then small-cap | shared risk brain | ⬜ |
| REQ-604.3 | **Tiering metric**: market cap where available, else dollar-volume (close × volume) as the proxy (no shares-outstanding data cached yet) | data limitation | 🔄 (dollar-volume proxy in use) |

**Note:** the Polygon pull's `prioritized_universe()` already does ETFs-first then
S&P-500 by dollar-volume (descending) — a big-cap-first ordering — so REQ-604.1 is
met. True market-cap tiering (REQ-604.3) would need shares-outstanding data; the
dollar-volume proxy is close and free. Trade-time prioritization (REQ-604.2) is
part of the REQ-601/602 risk-brain build.

---

## 10. Stock position sizing

| ID | Requirement | Rationale / source | Status |
|----|-------------|--------------------|--------|
| **REQ-606** | **Stock route buys 10 shares of each name on a buy signal, and sells the position on the sell signal** | Operator requirement #6 | ⬜ planned |
| REQ-606.1 | Entry = 10 shares at the signal; exit = full close on the strategy's sell signal (e.g. Connors RSI(2) > 70) | signal-based exit (matches daily_trader) | ✅ (exit logic) / ⬜ (fixed-10 sizing) |
| REQ-606.2 | Total stock deployment still bounded by the **$95K stock sleeve** (REQ-602) and **MAX_CONCURRENT** — refuse a 10-share buy that would breach the sleeve | REQ-602 | ⬜ |

**⚠️ Tension to confirm (conscious trade-off):** fixed 10-share sizing **overrides
risk-based / ½-Kelly / ATR sizing** for stocks (REQ-007). Consequences:
- **Dollar exposure varies by price**: 10×$500 stock = $5,000 vs 10×$30 stock = $300.
- **Dollar-risk varies by name**: with an ATR stop, a high-priced/volatile name
  risks many times more $ than a cheap one — this contradicts the KB "equal risk
  per trade" principle (§7 rule 9) and REQ-603's principle-based intent.
- This is fine as an explicit operator choice for a simple, legible stock book —
  just confirming you want **fixed 10 shares** (not "10 shares scaled by price" or
  "$X notional per name"). Say the word and I lock REQ-606 as-is.

---

## 11. Paper-only until edge proven → go-live signal

| ID | Requirement | Rationale / source | Status |
|----|-------------|--------------------|--------|
| **REQ-607** | **ALL trading stays on the paper system until a validated edge is proven. No real money is traded before then.** | Operator requirement #7 (the core discipline) | ✅ (paper default + dry-run + GO_LIVE hard gate) |
| REQ-607.1 | **"Edge proven" = objective, pre-defined criteria** (NOT paper P&L): cost-robust walk-forward PF ≥ 1.10 at BOTH 3 bp & 5 bp; OOS decay < 25%; ≥ 4-week paper incubation with clean mechanics; GO_LIVE_CHECKLIST §0–5 fully signed | REQ-202/203, GO_LIVE_CHECKLIST | 🔄 (criteria defined; incubation running) |
| REQ-607.2 | **When ALL edge criteria are met, the system shall PROACTIVELY SIGNAL the operator** ("✅ Edge validated — ready to consider live") via the dashboard + a notification | Operator: "give me a signal to switch to real trades" | ⬜ planned |
| REQ-607.3 | **The system NEVER auto-switches to real money** — the go-live signal is advisory; flipping to live remains a deliberate, manual, auditable operator action (live login still refused until the checklist is signed) | go-live discipline | ✅ |
| REQ-607.4 | Paper P&L is **explicitly NOT** an edge signal (it amplifies noise at max risk); only the objective criteria in REQ-607.1 trigger the signal | 3R-C, Davey | ✅ (EOD mechanics/edge split) |

**Current state:** the *defensive* half is fully built — paper mode default
(REQ-002), dry-run default (REQ-001), and `check_go_live_readiness()` hard-refuses
a live login until GO_LIVE_CHECKLIST is signed. What's missing is the *proactive*
half (REQ-607.2): a readiness monitor that watches the edge criteria and, when
they all flip green, raises a clear "ready to consider live" signal — so you don't
have to keep checking manually. Build = wire the numeric gates (GO_LIVE §0) into a
background check that emits a dashboard banner + notification when satisfied.

---

## 12. Dynamic profit-protecting exits

| ID | Requirement | Rationale / source | Status |
|----|-------------|--------------------|--------|
| **REQ-608** | **No fixed exit — a DYNAMIC, escalating profit-floor ladder.** As the unrealized gain grows, the protected floor ratchets UP in tiers; the exit strategy is continuously updated based on the move so a winner can never become a loss and a big winner can never give back to a small one | Operator requirement #8 (instance of REQ-603) | 🔄 (single-tier intraday only) |
| REQ-608.1 | **Tier 1 — breakeven**: once up ≥ the first trigger, stop moves to entry → trade can no longer become a loss | KB §3; existing `BREAKEVEN_TRIGGER_PCT` | ✅ (intraday) / ⬜ (daily) |
| REQ-608.2 | **Tier 2+ — escalating profit floor**: at higher gain tiers the locked-in floor steps UP (and the trail tightens), so each new profit level is protected as it's reached | KB §3 (let winners run + protect) | ⬜ |
| REQ-608.3 | Floor is **monotonic** — it only ratchets up, never down; once a profit level is locked it cannot be given back | profit-protection | ⬜ |
| REQ-608.4 | Applies to **both routes** with route-specific ladders; exact tiers/floors are **operator examples to be backtested** (REQ-603.3) | dual-instrument | ⬜ |
| REQ-608.5 | **⚠️ Whipsaw caveat + validation**: too-tight tiers get stopped on noise then miss the recovery. Tier triggers, floor %s, and trail give-backs must be **backtested**, not hand-set | §12 Davey; KB §3 | 🔒 standing |

**Example dynamic exit ladder (operator-supplied — illustrative, to be backtested):**

| Gain reached | OPTIONS floor / action | Gain reached | STOCKS floor / action |
|---|---|---|---|
| +40% | stop → breakeven, start trail | +20% | stop → breakeven, start trail |
| +80% | step floor up (lock partial profit, tighter trail) | +50% | lock in a "certain profit" floor |
| +200% | floor ≥ **+150%** (never give back below +150%) | … | (further tiers as defined) |

The principle: **continuously update the exit as the trade moves** — every higher
gain tier raises the protected floor. Not one fixed trigger.

**Current state (honest):** the *intraday options* path already implements this —
`BREAKEVEN_TRIGGER_PCT` (move stop to entry at +30%), `PARTIAL_TRIGGER_PCT` (+50%
partial), and `TRAIL_GIVE_BACK_PCT` (trail 20% off the high-water mark after T1).
But the **validated daily strategy (Connors) does NOT** — it exits on signal
(RSI(2) > 70), a 2×ATR stop, or a 10-day cap, with no profit-protection trail. The
+40%-then-reverses scenario you describe is exactly the gap on the daily/stock
side. ⚠️ Adding a trailing/breakeven exit to Connors **changes its exit logic**,
which is FROZEN during incubation (REQ-203) and was validated with the current
exit — so this ships as a **backtested variant** (does the profit-protect exit
improve OOS PF/expectancy without whipsaw drag?), NOT a live edit to the frozen
strategy.

### Downside: KB-principle loss-cutting (mirror of REQ-608)

| ID | Requirement | Rationale / source | Status |
|----|-------------|--------------------|--------|
| **REQ-609** | **Symmetric downside: a DYNAMIC, de-escalating loss ladder.** As adverse evidence accumulates (loss deepens, KB warning signals stack, time passes without recovery), the tolerated loss TIGHTENS in tiers — cut sooner, not at one fixed stop — with a hard max-loss cap as the backstop | Operator requirement #9; KB §3/§7/§10/§11/§15 | 🔄 (fixed stops only) |
| REQ-609.1 | **Tier 0 — initial stop** at a KB level on entry (ATR-scaled §3 / 50% premium §9) | KB §3/§9 | ✅ (fixed form) |
| REQ-609.2 | **Tier 1+ — tighten on KB warning signals**: thesis-broken (Brooks §11), VSA distribution/upthrust/no-demand (§10), volume divergence, momentum loss — each warning tightens the stop / scales the position down | KB §10/§11/§15 | ⬜ |
| REQ-609.3 | **Time de-escalation**: a stalled losing trade's tolerance shrinks over time (theta-aware for options, §1/§3 time-stop) | KB §1/§3 | 🔄 (time-stop exists) |
| REQ-609.4 | **Hard max-loss backstop**: never exceeds the route budget — options ≤ $500/trade & ≤ $1,500/week (REQ-605); stocks within the sleeve/share limits (REQ-602/606) | REQ-605/606 | 🔄 |
| REQ-609.5 | **⚠️ Validation**: adaptive/tiered loss-cuts must be backtested vs the frozen fixed stop — a smarter stop can also cut winners early (REQ-603.3) | §12 Davey | 🔒 standing |

**Together REQ-608 + REQ-609 = the full principle-based dynamic exit:** protect
winners on a reversal, cut losers when the thesis breaks — both KB-driven, both
backtested before replacing the frozen fixed stops. Current state: the system has
*fixed* loss-cuts (2×ATR stop, 50% premium stop, time-stop) — real but not yet
the adaptive, KB-signal-driven form REQ-609 asks for.

---

## 13. Primary objective — conservative, profitable, capital-preserving

| ID | Requirement | Rationale / source | Status |
|----|-------------|--------------------|--------|
| **REQ-611** | **The north star is a CONSISTENTLY PROFITABLE system, even if conservative — "don't lose money" first.** Capital preservation and positive expectancy after costs rank ABOVE aggressive growth | Operator requirement #11 | 🔄 (guides all design) |
| REQ-611.1 | **Be picky**: fewer, higher-quality trades (high KB-match, strong confluence) over many marginal ones — selectivity raises per-trade expectancy (Connors p.26 finding) | KB §12, ANALYSIS_LOG | 🔄 |
| REQ-611.2 | **Low drawdown / asymmetric**: dynamic loss-cuts (REQ-609) + profit-protection (REQ-608) so the average loss stays small and winners are protected → positive expectancy even at modest win rate | REQ-608/609 | ⬜ |
| REQ-611.3 | **Cost-robust profitability is the bar**: a strategy must be net-positive AFTER realistic costs (≥3bp/5bp) — never deploy a gross-positive/net-negative edge | §12 Davey | ✅ (gate) |
| REQ-611.4 | **Tension to confirm:** this conservative mandate **tempers** the Phase-1 "paper @ max-risk to learn" stance (CONTEXT.md). If the goal is a conservative live system, paper should increasingly trade the *disciplined* profile so the track record reflects how it'll actually run | CONTEXT roadmap | ⬜ confirm |

**Reading:** REQ-611 reframes success as **"green, small, and steady"** rather than
"big." It elevates the existing discipline (cost-robust gate, dynamic exits,
selectivity) into the system's explicit objective function. ⚠️ It also gently
conflicts with the earlier *paper-aggressive* learning posture — worth confirming
whether you want paper to now mirror the conservative live profile.

---

## 14. Self-learning loop (EOD)

| ID | Requirement | Rationale / source | Status |
|----|-------------|--------------------|--------|
| **REQ-610** | **The system shall learn from its trades. At end of day Claude reviews the day's trades and self-learns** — extracts what worked/didn't, updates memory, proposes improvements | Operator requirement #10 | 🔄 (partial) |
| REQ-610.1 | **EOD review**: MECHANICS scorecard (gates, fills, stops) + EDGE scorecard (P&L), per-symbol & per-strategy attribution | 3R-C, REQ-403 | ✅ |
| REQ-610.2 | **Trade memory**: each closed trade (setup, context, outcome) stored + recalled before future similar signals | trade_memory (ChromaDB) | ✅ |
| REQ-610.3 | **Lesson extraction**: day's lessons + KB cross-reference written to ANALYSIS_LOG; losing symbol×strategy cells flagged | ANALYSIS_LOG convention | ✅ / 🔄 (auto-write) |
| REQ-610.4 | **Proposes — never auto-applies — param changes.** Every "learned" tweak is a BACKTEST candidate gated by the cost-robust walk-forward; never silently retune live | §12 Davey; REQ-603.3 | 🔒 standing |
| REQ-610.5 | **Failure-mode learning**: crashes/desyncs/slippage-vs-model logged + reviewed | 3R-C failure_log | ✅ |

**⚠️ The critical line:** "self-learn" = surface patterns, update memory, and
*propose* backtest-gated improvements — NOT an auto-optimizer that retunes live
thresholds on recent trades (the exact curve-fit failure the discipline prevents).

---

## Appendix A — KB-derived entry & exit criteria (proposed)

*Synthesized from `knowledge_base.md` to satisfy REQ-603/604/605/606/608/609/611.
Principle-based and dynamic; every criterion cites its KB section. PROPOSED — ships
to live only via backtested, cost-robust variants (REQ-202/603.3), not by hand.*

### Entry — a signal must clear ALL gates (be picky, REQ-611.1)

1. **Regime (§8 Gunn, §19):** symbol `close > SMA200` AND broad market risk-on
   (`SPY > SMA200`) for longs. No counter-trend longs in a risk-off tape.
2. **Validated setup fires (one of):** Connors RSI(2) < 10 (§19) · Bollinger
   lower-band reversion (§1) · trend pullback dip-and-reclaim (§8/§14) · 52-week
   breakout (§15). *(All four cleared the cost-robust gate 2026-05-31.)*
3. **Confluence ≥ 2 (§Signal-Quality, §10):** setup + a confirmer (volume/VSA
   support §10, not into resistance §6, momentum aligned).
4. **Instrument routing (§5, §2):** directional-only edge → **shares** (cheapest,
   §5); **option only with a volatility edge** — IVR < 30 naked, 30–50 spread,
   > 50 spread-only/skip (§2). [REQ-601]
5. **Vol-timing for long premium (§22):** prefer after low-vol clusters; avoid
   buying premium after 3+ high-vol days (variance premium headwind).
6. **No-trade filters (§3, §11, §23):** skip D-2 earnings (§23), macro blackout
   (FOMC/CPI/NFP), VIX > 30 spike, > 2×ATR climax bar (§11), RSI blow-off.
7. **Liquidity (§9):** OI ≥ 200, bid-ask < 5% of mid, min volume.
8. **KB-principles match ≥ 60% (REQ-004) + debate proceeds (REQ-005).**

### Exit — dynamic ladders + KB event overrides

- **Profit ladder (REQ-608, monotonic floor):** options +40% breakeven+trail →
  +80% step up → +200% lock ≥ +150%. stocks +20% breakeven+trail → +50% lock floor.
- **Loss ladder (REQ-609, de-escalating):** initial ATR/50%-premium stop → tighten
  on each KB warning (thesis-broken §11, VSA distribution §10, volume divergence) →
  time-decay tighten → hard cap (≤ $500 option / route budget).
- **KB event exits (override):** 80% of max spread profit (§24) · 7-DTE theta exit
  for options (§1) · D-2 earnings (§23) · VIX-spike de-risk (§22) · strategy signal
  exit (Connors RSI(2) > 70 §19) · time-stop on a stalled flat trade (§3).

**Every threshold above is a starting hypothesis → backtested before it goes live.**

---

## 15. Full autonomy (no manual intervention)

| ID | Requirement | Rationale / source | Status |
|----|-------------|--------------------|--------|
| **REQ-612** | **The system shall auto-trade everything end-to-end with NO manual intervention** — signal → KB-principles/debate gate → instrument route → size → execute → manage → dynamic exit — hands-off | Operator requirement #12 | 🔄 (partial) |
| REQ-612.1 | Autonomy spans **both routes** (stocks + options) and the **full lifecycle** (entry AND the dynamic exit ladders REQ-608/609), not just entries | dual-instrument | ⬜ |
| REQ-612.2 | **Autonomy lives INSIDE the safety envelope**: still dry-run by default (REQ-001), paper-only until edge proven (REQ-607), every trade gated (REQ-004/005), every limit enforced (REQ-602/605/606). Autonomy ≠ ungated | safety stack | ✅ (gates) |
| REQ-612.3 | **No approval modal** in the path — `auto_trade=True` already skips it for the screener; extend to the router + both executors + exit engine | trade_approval | 🔄 (screener only) |
| REQ-612.4 | **Operator override always available**: emergency flatten-all, disarm, and the kill/loss circuit breakers remain one click / always-on | safety | ✅ |
| REQ-612.5 | Runs **unattended** under the scheduler + watchdog (auto-restart, heartbeat health) — no human needed to keep it alive | §P2 #17 | ✅ |

**Reading:** REQ-612 = "set it and forget it" operation, but the autonomy is
*bounded* — it can only do what the gates, sleeves, caps, and dry-run/paper mode
allow. Achieved when Phases 1–3 are wired end-to-end on the scheduler with no
approval step. The operator still flips paper→live manually (REQ-607.3) and can
always intervene (REQ-612.4).

---

## 16. Live paper testing (always) + multi-account A/B

| ID | Requirement | Rationale / source | Status |
|----|-------------|--------------------|--------|
| **REQ-613** | **Always do LIVE testing on paper** — validate under real fills/slippage on the paper account, not just backtests/shadow | Operator: "the whole idea is testing" | 🔄 (building) |
| REQ-613.1 | **Support multiple paper accounts** for parallel testing — run different strategy configs / risk profiles side-by-side and compare (live A/B) | Operator: "we can create multiple paper accounts" | ⬜ |
| REQ-613.2 | Each account's credentials in `.env` (e.g. ALPACA_API_KEY_A/B); a config selects which account a given engine instance trades | infra | ⬜ |
| REQ-613.3 | All paper testing still runs through the full safety stack (regime-skip, KB/debate gate, sleeves/caps, dedup, hard caps) — "live paper" ≠ ungated | safety | 🔄 |

**Note:** "always live on paper" supersedes the dry-run-default for the autonomous
engine — it gets its OWN paper-execution path (places real PAPER orders, fake
money) so the legacy dry-run paths are undisturbed. Multiple paper accounts let
us A/B configs (e.g. regime-skip on vs off) under real fills simultaneously.

---

## 17. Two-step scale-out exit (KB §XM upgrade)

| ID | Requirement | Rationale / source | Status |
|----|-------------|--------------------|--------|
| **REQ-614** | The exit engine shall support **scaling OUT** of a winner in pieces instead of all-or-nothing, so it stops clipping fat-tail winners while still banking "enough" | KB §XM (Elder Ch.53 + Schwab/OIC + Fontanills); operator profit-taking review 2026-06-04 | ⬜ (gated) |
| REQ-614.1 | **Sizing prerequisite (the blocker)** — options must size at **≥ 2 contracts** (today hardcoded `qty=1` in `screener_executor.py`) and stocks at an **even lot** (today fixed 10, REQ-606), so a half exists to sell. Sizing stays inside the $500/trade + $1,500/week option caps (REQ-605) and the 6% monthly open-risk breaker (REQ-611) | you cannot halve a 1-lot | ⬜ |
| REQ-614.2 | **T1 partial close** — at the first target (**+50% premium gain**, Fontanills; or +1 ATR for shares) close **half** the position unconditionally | KB §XM-3 "mandatory discipline, not optional" | ⬜ |
| REQ-614.3 | **Breakeven the remainder** — after T1, move the runner's stop to breakeven → zero open risk → frees 6%-budget capacity. Already implemented by the **REQ-608 ladder** (now wired to live options via `OPT_DYNAMIC_EXIT_ENABLED`, default off) | KB §XM-4 | 🔄 (ladder exists) |
| REQ-614.4 | **Trail the runner** — let the remaining half ride the +2/+3 ATR / 30%-trail ladder so a rare burst isn't clipped; stall-timer + 21-day cap remain the backstops | KB §XM-5; Covel §8 fat-tail | ⬜ |
| REQ-614.5 | **Debit-spread variant** — use the Spread Close Hierarchy: T1 at +50% of debit, max-profit close at **75–85% of spread width**, −50% stop non-negotiable, forced close at **7 DTE** | KB spread-close-hierarchy (§24/§1) | ⬜ |
| REQ-614.6 | **Gated rollout** — ship behind a feature flag (default off), honor `paper_mode`, and **A/B against the current single-shot exits on the Polygon backtest** before defaulting on (blocked: the Polygon pull currently stops after underlying #60 / UNH) | CLAUDE.md trading safety rails; KB §XM "propose as REQ, A/B first" | ⬜ |

**Reading:** REQ-614 is the synthesis KB §XM flags — Covel "let the fat tail run"
+ Elder "bank enough", minus the all-or-nothing problem. The breakeven+trail half
(REQ-614.3/.4) **already exists** as the REQ-608 ladder. The missing pieces are
the **≥ 2-contract / even-lot sizing** (REQ-614.1 — the hard blocker; you can't
scale out of a single contract, which is exactly why today's 1-lot DIA/SMCI/XLF
positions are binary hold-or-close) and the **T1 partial-close** mechanic
(REQ-614.2). Until sizing is ≥ 2, "exact trim size" is not executable. Gated and
unvalidated until A/B'd on the backtest (REQ-614.6).

---

## 18. EOD self-improvement pipeline — propose → validate → apply (NOT auto-fix)

| ID | Requirement | Rationale | Status |
|----|-------------|-----------|--------|
| **REQ-615** | The EOD analysis may **PROPOSE** changes; it must **never auto-apply code or params to the live account.** Closes the "analyze + improve daily" loop safely | over-fitting one noisy day / unsupervised LLM edits = money risk | ⬜ |
| REQ-615.1 | **EOD emits structured proposals** — concrete param/flag diffs (not prose), each with the evidence (e.g. "OPT_RELAX_LIQUIDITY→False: 5 fills at >5% spread, 225bps slippage") | actionable, auditable | ⬜ |
| REQ-615.2 | **Debate gate scores each proposal** (bull/bear: is the change justified by the evidence, or a one-day artifact?) — reuse `debate.py` for change-review, not just per-trade | guard against noise | ⬜ |
| REQ-615.3 | **Backtest validates** every proposal against the cost-robust walk-forward (REQ-603.3 / 610.4) before it can go live — a proposal that fails the gate is rejected | non-negotiable: never silently retune live | ⬜ |
| REQ-615.4 | **PARAMS** that pass 615.2+615.3 may auto-apply (then restart); **CODE** changes always require the green test suite (`make test`) + a human glance — no LLM-written code deploys unreviewed | code risk ≫ param risk | ⬜ |
| REQ-615.5 | **Cautionary precedent (2026-06-04):** the EOD auto-summary's top rec was "tighten stops 2×" — the data showed stops were fine and illiquid market fills were the cause. Auto-apply would have made it worse. This REQ exists because of that day | why propose≠apply | ✅ logged |

**Reading:** auto-*propose* + auto-*score* + backtest-*validate* = yes. Auto-*apply
code/params live + restart* = no. The 2026-06-04 day is the proof: the right fix came
from reading the data (slippage + relaxation logs), not the summary's first instinct.
