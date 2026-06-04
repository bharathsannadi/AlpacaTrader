# Implementation Plan — operator requirements REQ-601…611

Phased plan to take the system from "validated signal core + safety scaffolding"
to the full operator spec. Sequenced by dependency and value, every phase on
**paper + dry-run, behind the existing gates**.

## Non-negotiable guardrails (apply to every phase)
- **Paper-only** until the edge-proven criteria (REQ-607.1) are met. No real money.
- **Backtest before live**: any strategy/exit/sizing change ships only via a
  cost-robust (≥3 bp AND ≥5 bp OOS) walk-forward variant (REQ-202/603.3).
- **Frozen during incubation**: the live Connors strategy's entry/exit/params are
  NOT edited mid-incubation. New behavior lands on *new variants/strategies* or
  *post-incubation*, validated first.
- **No auto-tuning**: the self-learning loop proposes; it never mutates live params (REQ-610.4).
- **Tests + feature flags**: each phase ships behind a flag defaulting safe, with unit tests.

## Dependency / data notes
- **Options route** (spreads) is blocked on **2S-B** (spread-data harness) and on
  the **options data pull finishing** (running now, ETFs-first, before 2026-06-16).
- Shares route + naked options can proceed without 2S-B.
- The **risk brain (Phase 1)** is the central unlock — 5 requirements depend on it.

---

## Phase 0 — Architecture scaffolding (no behavior change)
**Goal:** the plug-in skeleton so strategies, routes, and the risk brain compose.
**Satisfies (groundwork):** REQ-601, 602
**Deliverables**
- `strategy.py` — `Strategy` protocol (`generate(symbol) -> Signal`), registry of
  validated strategies (Connors S1 + S2/S3/S4 from the multi-strategy backtest).
- `signal.py` — `Signal` dataclass (symbol, direction, strength, ATR ctx, KB tags).
- `risk_brain.py` — skeleton holding per-route state (sleeves, weekly risk, open
  positions), no enforcement yet.
**Acceptance:** modules import; existing behavior unchanged; unit tests for the
registry + signal object.
**Effort:** ~0.5 day · **Blocked by:** none

## Phase 1 — Risk brain + money management (paper)
**Goal:** enforce capital sleeves, caps, and sizing rules. The biggest unlock.
**Satisfies:** REQ-602, 605, 606, 604.2 (and REQ-007 reconciled)
**Deliverables**
- **Capital sleeves (REQ-602):** `risk_brain` tracks deployed $ per route; refuses
  an entry that would exceed the **$95K stock** / **remaining-equity options** sleeve.
- **Options caps (REQ-605):** per-trade ≤ $500, rolling **weekly** ≤ $1,500
  (confirm window: rolling-5-day vs Mon–Fri). Track cumulative weekly options risk.
- **Stock sizing (REQ-606):** fixed **10 shares** per buy signal (flag:
  `STOCK_SIZE_MODE = fixed10 | risk_based`), full close on sell signal.
- **Tier prioritization (REQ-604.2):** when slots/sleeve limited, fill ETF → large
  → small (dollar-volume proxy) order.
**Acceptance:** paper trades respect every limit; deterministic unit tests for
sleeve overflow, weekly-cap block, 10-share sizing, tier order.
**Effort:** ~2 days · **Blocked by:** Phase 0

## Phase 2 — KB-driven instrument router (paper)
**Goal:** per-signal choice of shares vs option (and structure), per KB §5/§2.
**Satisfies:** REQ-601 (.1/.2/.3)
**Deliverables**
- `router.py` — policy: directional-only edge → **shares** (§5 cost hierarchy);
  option only with a **volatility edge** → IVR<30 naked, 30–50 spread, >50
  spread-only/skip (§2). Affordability fallback to shares at small sleeves (REQ-601.3).
- Route abstraction: `shares_executor` / `options_executor` behind one signal+risk core.
- Wire router → risk_brain → executors.
**Acceptance:** signals route correctly + logged with the KB reason; spreads remain
disabled until 2S-B passes (naked/shares route live in paper).
**Effort:** ~2 days · **Blocked by:** Phase 1; spreads also on 2S-B

## Phase 3 — Dynamic exit ladders (BACKTEST → then paper)
**Goal:** escalating profit floor + de-escalating loss cut, KB-driven.
**Satisfies:** REQ-603, 608, 609
**Deliverables**
- `backtest_exit_ladders.py` — test the profit ladder (REQ-608: opt +40/+80/+200→
  ≥150; stk +20/+50) and loss ladder (REQ-609: tighten on KB warnings) as variants
  on the validated strategies. Question: do they beat the fixed-stop baseline OOS
  net of whipsaw?
- If pass → `exit_engine.py` implementing the monotonic profit floor + de-escalating
  loss tiers + KB event overrides (Appendix A), applied to NEW strategies /
  post-incubation Connors.
**Acceptance:** ladder variant beats fixed-stop baseline on OOS PF/expectancy &
max-DD; only then wired live (paper).
**Effort:** ~2 days backtest + ~1 day wire · **Blocked by:** Phase 0; runs in parallel

### Phase 3b — Two-step scale-out (REQ-614, KB §XM) — gated follow-on
**Goal:** replace all-or-nothing exits with T1-partial + breakeven + trail, so
fat-tail winners aren't clipped (KB §XM synthesis).
**Done so far (2026-06-04):** REQ-608 breakeven+trail ladder wired to the **live
option stop** behind `OPT_DYNAMIC_EXIT_ENABLED` (default off) — covers REQ-614.3/.4.
**Still to do:** REQ-614.1 sizing (options `qty=1`→≥2, stock fixed-10→even lot,
inside the $500/$1500 caps + 6% breaker) — the hard blocker; then REQ-614.2 T1
partial-close + REQ-614.5 spread variant.
**Acceptance:** scale-out beats single-shot on OOS PF/max-DD on the Polygon
backtest (currently blocked — pull stops after underlying #60); only then default on.

## Phase 4 — Multi-strategy portfolio + regime overlay (paper)
**Goal:** more than one validated strategy live (fix single-strategy fragility),
plus the non-equity sleeve for tail risk.
**Satisfies:** REQ-201, 205, 611.2
**Deliverables**
- Incubate S2/S3/S4 (validated 2026-05-31) alongside Connors via the registry.
- Research + backtest a **regime/size overlay** with a non-equity sleeve (TLT/GLD/
  inverse — data now pulling) that scales exposure down in risk-off (the real 2022 fix).
**Acceptance:** portfolio runs in paper; per-strategy attribution + correlation
tracked; overlay backtested before enabling.
**Effort:** ~2 days + incubation weeks · **Blocked by:** Phases 0-1; overlay needs ETF/bond data

## Phase 5 — Self-learning loop + go-live signal (paper)
**Goal:** EOD learning that proposes (not applies), and a proactive go-live signal.
**Satisfies:** REQ-610, 607.2
**Deliverables**
- EOD: auto-write lessons + KB cross-ref to ANALYSIS_LOG; emit **backtest-candidate
  proposals** (e.g. "disable NVDA×breakout, OOS -8%") — never auto-applied (REQ-610.4).
- **Go-live readiness monitor:** background check of the numeric edge criteria
  (GO_LIVE §0); when all green → dashboard banner + notification "✅ ready to consider
  live" (REQ-607.2). Never auto-switches (REQ-607.3).
**Acceptance:** EOD produces lessons + proposals; readiness signal fires only when
every objective criterion is met.
**Effort:** ~2 days · **Blocked by:** Phase 3 (attribution feeds proposals)

## Phase 5b — Full autonomy integration (paper)
**Goal:** the whole pipeline runs hands-off, no manual step. "Set and forget."
**Satisfies:** REQ-612
**Deliverables**
- Wire signal → gate → router → risk_brain → executor → exit_engine on the
  scheduler with **no approval modal** on EITHER route (extend `auto_trade=True`
  beyond the screener to the router + both executors + exit engine).
- Continuous position management loop drives the dynamic exit ladders (608/609)
  unattended.
- Keep operator overrides hot: emergency flatten-all, disarm, circuit breakers.
**Acceptance:** a full paper day runs entry→exit on both routes with zero manual
input; every gate/limit still enforced; overrides verified one-click.
**Effort:** ~1 day (integration) · **Blocked by:** Phases 1, 2, 3
**Note:** autonomy stays INSIDE the envelope — dry-run default + paper + gates
mean "auto-trade everything" can't place a real or ungated order. Paper→live is
still a manual operator flip (REQ-607.3).

## Phase 6 — Conservative objective + validation (ongoing)
**Goal:** make "green, small, steady" the operating point and run toward edge-proven.
**Satisfies:** REQ-611, 607.1
**Deliverables**
- Apply selectivity (be picky, REQ-611.1), confirm paper mirrors the disciplined
  profile (REQ-611.4 — confirm with operator), monitor expectancy-after-costs.
- Drive the full system through ≥4-week incubation toward the go-live criteria.
**Acceptance:** positive expectancy after realistic costs in paper; clean mechanics;
GO_LIVE_CHECKLIST progressing.
**Effort:** ongoing · **Blocked by:** all prior

---

## Sequence summary

```
Phase 0 ─► Phase 1 ─► Phase 2 ─┬─► Phase 5b (autonomy) ─► Phase 4 ─► Phase 6
                └─► Phase 3 ───┴─► Phase 5 ───────────────┘
```

| Phase | Satisfies | Effort | Can start |
|---|---|---|---|
| 0 Scaffolding | groundwork 601/602 | 0.5d | now |
| 1 Risk brain + money mgmt | 602, 605, 606, 604.2 | 2d | after 0 |
| 2 Instrument router | 601 | 2d | after 1 (spreads on 2S-B) |
| 3 Exit ladders (backtest→wire) | 603, 608, 609 | 3d | parallel after 0 |
| 5b Full autonomy integration | 612 | 1d | after 1,2,3 |
| 4 Multi-strategy + overlay | 201, 205, 611.2 | 2d + weeks | after 1 |
| 5 Self-learning + go-live signal | 610, 607.2 | 2d | after 3 |
| 6 Conservative + validate | 611, 607.1 | ongoing | last |

**Already done (this session):** safety defaults (REQ-001/006), KB-principles gate
(004), debate gate (005), confidence column (401), 15-row screener (402), ETF
universe (101/103/104), EOD mechanics/edge split (403/610.1), data archival (301-304),
multi-strategy validation (4 strategies), cost-robust gate (202/611.3).

**Recommended start:** Phase 0 → Phase 1 (the risk brain unlocks 5 requirements),
with Phase 3's exit-ladder backtest running in parallel. All paper, all gated.
