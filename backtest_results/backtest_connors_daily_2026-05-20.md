# Path A — Connors RSI(2) Daily-Bar Backtest

_Generated 2026-05-20 10:34_

**Pre-specified rules (no sweeping):** RSI(2) < 10 above SMA200 (bull), enter next-day open, exit when RSI > 70 at prior close or 2.0×ATR14 stop or 10-day cap. LONG-only. Same \$200 risk budget. Same 3 & 5 bp cost gate.

## Full-sample (context; split at training midpoint)

| bp | n | Win% | PF | Avg\$ | Total\$ |
|---|---|---|---|---|---|
| 1 | 2325 | 66.6 | 1.43 ✅ | +21.37 | +49690.0 |
| 3 | 2325 | 66.2 | 1.39 ✅ | +19.77 | +45962.0 |
| 5 | 2325 | 66.1 | 1.36 ✅ | +18.17 | +42235.0 |
| 10 | 2325 | 65.5 | 1.27 ✅ | +14.16 | +32917.0 |

## Walk-forward — TEST half (the honest read)

_Split date: 2024-05-22  |  train n=1178  test n=1147_

| bp | Train PF | **Test PF** | Test Win% | Test \$ |
|---|---|---|---|---|
| **3** | 1.48 | **1.31** ✅ | 65.5 | +18439.0 |
| **5** | 1.44 | **1.28** ✅ | 65.1 | +16654.0 |

## Per-symbol breadth (@ 3 bp, TEST half)

| Symbol | n | Win% | PF | Total\$ |
|---|---|---|---|---|
| AAPL | 41 | 58.5 | 0.96 ⛔ | -85.0 |
| ADBE | 2 | 50.0 | 0.34 ⛔ | -134.0 |
| AMD | 24 | 75.0 | 1.53 ✅ | +542.0 |
| AMZN | 46 | 50.0 | 0.61 ⛔ | -1116.0 |
| ARM | 24 | 62.5 | 0.83 ⛔ | -227.0 |
| AVGO | 42 | 69.0 | 1.49 ✅ | +827.0 |
| BAC | 46 | 63.0 | 1.15 ✅ | +440.0 |
| C | 40 | 75.0 | 2.5 ✅ | +2197.0 |
| CBRE | 31 | 87.1 | 5.69 ✅ | +1952.0 |
| CRM | 17 | 23.5 | 0.23 ⛔ | -1782.0 |
| CRWD | 36 | 52.8 | 0.58 ⛔ | -1138.0 |
| CRWV | 1 | 0.0 | 0.0 ⛔ | -118.0 |
| GLW | 39 | 61.5 | 1.21 ✅ | +505.0 |
| GOOG | 40 | 67.5 | 1.23 ✅ | +486.0 |
| HOOD | 33 | 54.5 | 1.09 ⚠️ | +213.0 |
| IBM | 43 | 76.7 | 1.78 ✅ | +1283.0 |
| INTC | 16 | 68.8 | 1.77 ✅ | +284.0 |
| JPM | 33 | 57.6 | 1.15 ✅ | +224.0 |
| LRCX | 19 | 68.4 | 1.57 ✅ | +487.0 |
| MA | 38 | 76.3 | 1.75 ✅ | +1057.0 |
| META | 35 | 65.7 | 0.89 ⛔ | -236.0 |
| MSFT | 28 | 53.6 | 0.95 ⛔ | -67.0 |
| MU | 23 | 43.5 | 0.45 ⛔ | -1123.0 |
| NET | 28 | 60.7 | 0.88 ⛔ | -209.0 |
| NFLX | 36 | 61.1 | 1.36 ✅ | +861.0 |
| NKE | 4 | 25.0 | 0.52 ⛔ | -229.0 |
| NOW | 18 | 66.7 | 0.98 ⛔ | -27.0 |
| NVDA | 34 | 82.4 | 3.46 ✅ | +2477.0 |
| ORCL | 33 | 69.7 | 1.35 ✅ | +582.0 |
| PLTR | 41 | 68.3 | 2.2 ✅ | +1857.0 |
| QQQ | 40 | 82.5 | 2.28 ✅ | +1822.0 |
| SOFI | 21 | 57.1 | 0.79 ⛔ | -319.0 |
| SPY | 38 | 71.1 | 1.8 ✅ | +1640.0 |
| TEAM | 13 | 38.5 | 0.55 ⛔ | -476.0 |
| TSM | 32 | 68.8 | 2.15 ✅ | +1539.0 |
| UBER | 29 | 65.5 | 1.34 ✅ | +333.0 |
| UNH | 9 | 66.7 | 0.81 ⛔ | -114.0 |
| V | 33 | 75.8 | 2.82 ✅ | +1925.0 |
| WFC | 41 | 73.2 | 2.68 ✅ | +2307.0 |

**23/39 symbols PF ≥ 1.0 @3bp in test half.**

## Exit breakdown (TEST half)

| Exit type | n | % |
|---|---|---|
| mean_revert | 860 | 75% |
| atr_stop | 264 | 23% |
| time_cap | 23 | 2% |

## Per-year PF (@ 3 bp, all years)

| Year | n | PF |
|---|---|---|
| 2021 | 100 | 1.59 ✅ |
| 2022 | 175 | 0.79 ⛔ |
| 2023 | 592 | 1.5 ✅ |
| 2024 | 682 | 1.75 ✅ |
| 2025 | 615 | 1.16 ✅ |
| 2026 | 161 | 1.65 ✅ |

## Verdict

**✅ CANDIDATE — Test PF 1.31@3bp / 1.28@5bp, BOTH ≥ 1.10 OOS.**

First strategy to clear the cost-robust gate. **Next steps (mandatory before live):** (1) paper incubation per Davey rung; (2) GO_LIVE_CHECKLIST all boxes; (3) Kelly sizing from these stats; (4) build daily execution layer. NOT auto-live.

_Data: yfinance daily bars (5yr, free). Pre-specified Connors RSI(2) rules. Same \$200 risk budget + 3 & 5 bp cost gate as all prior tests._