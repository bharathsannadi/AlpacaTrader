# Connors RSI(2) — Experiment Sweep (MIN_ATR_PCT + H-SEL-REGIME)
_Run 2026-05-31 12:11  ·  cost gate: Test PF ≥ 1.10 @ BOTH 3 & 5 bp OOS_

| Variant | n | Train PF 3/5bp | Test PF 3bp | Test PF 5bp | Test win% | Test $ |
|---|---|---|---|---|---|---|
| baseline (frozen) | 790 | 1.27/1.24 | 1.35 ✅ | 1.32 ✅ | 66.1% | $6840 |
| EXP1 MIN_ATR_PCT=1.5% | 780 | 1.27/1.24 | 1.33 ✅ | 1.3 ✅ | 65.7% | $6425 |
| EXP1 MIN_ATR_PCT=1.0% | 790 | 1.27/1.24 | 1.35 ✅ | 1.32 ✅ | 66.1% | $6840 |
| EXP2a regime-gate (block) | 689 | 1.28/1.24 | 1.31 ✅ | 1.28 ✅ | 65.5% | $5077 |
| EXP2b regime+tiered RSI | 745 | 1.33/1.3 | 1.29 ✅ | 1.26 ✅ | 64.8% | $5397 |
| EXP1+2b combined | 735 | 1.31/1.28 | 1.29 ✅ | 1.26 ✅ | 64.7% | $5366 |

## Per-year Test PF @3bp (the 2022 bear-year weakness)

| Variant | 2024 | 2025 | 2026 |
|---|---|---|---|
| baseline (frozen) | 1.63 | 1.25 | 1.2 |
| EXP1 MIN_ATR_PCT=1.5% | 1.54 | 1.24 | 1.24 |
| EXP1 MIN_ATR_PCT=1.0% | 1.63 | 1.25 | 1.2 |
| EXP2a regime-gate (block) | 1.45 | 1.24 | 1.31 |
| EXP2b regime+tiered RSI | 1.28 | 1.33 | 1.22 |
| EXP1+2b combined | 1.26 | 1.32 | 1.27 |

## Full-sample per-year PF @3bp (exposes the 2022 bear year — in TRAIN half of the WF split)

| Variant | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|
| baseline (frozen) | 1.87 | **0.85** | 1.50 | 1.48 | 1.25 | 1.20 |
| EXP1 ATR≥1.5% | 1.87 | **0.85** | 1.38 | 1.53 | 1.24 | 1.24 |
| EXP2a regime-block | 1.87 | **0.38** | 1.49 | 1.48 | 1.24 | 1.31 |
| EXP2b regime+tiered | 1.87 | **0.61** | 1.50 | 1.48 | 1.33 | 1.22 |

## VERDICT (2026-05-31)

- **EXP-1 (MIN_ATR_PCT=1.5%): NOT validated.** Removes only 10/790 trades, leaves 2022 unchanged (0.85), and slightly LOWERS OOS Test PF (1.35→1.33 @3bp) and total ($6840→$6425). The live `daily_trader.MIN_ATR_PCT=0.015` is not justified by this data — it is ~neutral, marginally negative. Do not change live mid-incubation (frozen); flag as unvalidated for post-incubation review.
- **EXP-2 (H-SEL-REGIME): REFUTED.** Both the regime-block and regime+tiered-RSI variants make the 2022 bear year WORSE (0.85 → 0.38 / 0.61), not better. The hypothesis that selectivity fixes the bear-year weakness is wrong here: the regime gate removes the trades that WOULD have recovered and keeps the worst ones. KB §19 H-SEL-REGIME candidate is closed as REFUTED.
- **Methodology note:** with the cache now through 2026-05-29, the 50/50 walk-forward split puts 2024–2026 (all risk-on) in the OOS test half and 2021–2023 (incl. the 2022 bear) in train. The current OOS window therefore does NOT stress the bear regime. The 2022 weakness is a real, known, in-sample limitation; it remains accepted (per §19 Known Limitations) rather than "fixable" by these candidates.
- **Net:** frozen baseline stays. No live change. Discipline held — neither hand-tune beat the baseline OOS.
