# Shares-Path Robustness — REAL Polygon 3yr

_Generated 2026-05-19 11:05 ET_

Stress-test of the S3 shares finding. Headline uses **3 bp** round-trip slippage (3× the optimistic 1 bp in the structure run — deliberately pessimistic). Same vwap_momentum entries, ATR stop/target, $200/trade risk sizing.

## 1. Per-symbol (@ 3 bp) — is the edge broad?

| Symbol | n | Win% | PF | Avg$ | Total$ | MaxDD$ |
|---|---|---|---|---|---|---|
| AMZN | 505 | 55.0 | 1.22 ✅ | +27.91 | +14095.0 | -6726.0 |
| GOOG | 499 | 48.7 | 0.87 ⛔ | -19.72 | -9841.0 | -15021.0 |
| META | 487 | 49.7 | 1.04 ⚠️ | +5.9 | +2874.0 | -3967.0 |
| MSFT | 509 | 46.6 | 0.79 ⛔ | -33.89 | -17249.0 | -17818.0 |
| NVDA | 461 | 56.6 | 1.55 ✅ | +61.59 | +28395.0 | -3415.0 |
| SPY | 633 | 51.7 | 0.7 ⛔ | -50.87 | -32198.0 | -33585.0 |

## 2. Per-year (@ 3 bp) — does it hold every regime?

| Year | n | Win% | PF | Avg$ | Total$ |
|---|---|---|---|---|---|
| 2023 | 654 | 52.3 | 1.04 ⚠️ | +5.34 | +3495.0 |
| 2024 | 1072 | 50.7 | 0.91 ⛔ | -12.91 | -13837.0 |
| 2025 | 1032 | 52.2 | 1.02 ⚠️ | +3.25 | +3353.0 |
| 2026 | 336 | 48.5 | 0.86 ⛔ | -20.64 | -6935.0 |

## 3. Symbol × Year PF grid (@ 3 bp) — the strict test

| Symbol | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|
| AMZN | 1.34 | 1.16 | 1.28 | 1.01 |
| GOOG | 0.77 | 0.72 | 1.18 | 0.78 |
| META | 0.97 | 1.06 | 1.08 | 1.03 |
| MSFT | 0.79 | 0.65 | 0.92 | 0.88 |
| NVDA | 1.96 | 1.94 | 1.21 | 0.99 |
| SPY | 0.86 | 0.64 | 0.7 | 0.65 |

**11/24 symbol-year cells have PF ≥ 1.0.** ⚠️ concentrated — edge not robust across the matrix


## 4. Cost sensitivity — does the edge survive worse fills?

| Slippage (bp RT) | n | Win% | PF | Avg$ | Total$ |
|---|---|---|---|---|---|
| 1 | 3094 | 53.3 | 1.39 ✅ | +47.52 | +147028.0 |
| 3 | 3094 | 51.3 | 0.97 ⛔ | -4.5 | -13924.0 |
| 5 | 3094 | 48.4 | 0.67 ⛔ | -56.52 | -174876.0 |
| 10 | 3094 | 38.4 | 0.26 ⛔ | -186.57 | -577257.0 |

## 5. Per-symbol walk-forward (@ 3 bp) — OOS decay

| Symbol | Train PF | Test PF | Decay% |
|---|---|---|---|
| AMZN | 1.34 | 1.11 | +17% ✅ |
| GOOG | 0.75 | 1.01 | -35% ✅ |
| META | 0.97 | 1.12 | -15% ✅ |
| MSFT | 0.75 | 0.82 | -9% ⚠️ |
| NVDA | 1.95 | 1.24 | +36% ⚠️ |
| SPY | 0.73 | 0.67 | +8% ⚠️ |

## Verdict

**⛔ FAILS robustness.** Aggregate PF 0.97 @ a realistic 3 bp. The S3 1.38 was an artifact of the optimistic 1 bp assumption. Shares path is NOT validated. Re-examine the entry signal itself; do not deploy.

_REAL Polygon 3yr 5-min bars, cached. Shares execution is conservatively modeled; this RANKS robustness, it is not a live-trading green light (paper + GO_LIVE_CHECKLIST still required)._