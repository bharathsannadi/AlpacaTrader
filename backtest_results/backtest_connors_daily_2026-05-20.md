# Path A — Connors RSI(2) Daily-Bar Backtest

_Generated 2026-05-20 11:42_

**Pre-specified rules (no sweeping):** RSI(2) < 10 above SMA200 (bull), enter next-day open, exit when RSI > 70 at prior close or 2.0×ATR14 stop or 10-day cap. LONG-only. Same \$200 risk budget. Same 3 & 5 bp cost gate.

## Full-sample (context; split at training midpoint)

| bp | n | Win% | PF | Avg\$ | Total\$ |
|---|---|---|---|---|---|
| 1 | 785 | 65.7 | 1.34 ✅ | +17.44 | +13689.0 |
| 3 | 785 | 65.6 | 1.31 ✅ | +15.91 | +12490.0 |
| 5 | 785 | 65.5 | 1.27 ✅ | +14.38 | +11291.0 |
| 10 | 785 | 65.0 | 1.2 ✅ | +10.56 | +8292.0 |

## Walk-forward — TEST half (the honest read)

_Split date: 2024-05-31  |  train n=395  test n=390_

| bp | Train PF | **Test PF** | Test Win% | Test \$ |
|---|---|---|---|---|
| **3** | 1.29 | **1.32** ✅ | 66.4 | +6434.0 |
| **5** | 1.26 | **1.29** ✅ | 66.2 | +5867.0 |

## Per-symbol breadth (@ 3 bp, TEST half)

| Symbol | n | Win% | PF | Total\$ |
|---|---|---|---|---|
| AAPL | 28 | 53.6 | 0.78 ⛔ | -421.0 |
| ADBE | 1 | 100.0 | 99.9 ✅ | +69.0 |
| AMD | 15 | 73.3 | 1.55 ✅ | +340.0 |
| AMZN | 25 | 40.0 | 0.35 ⛔ | -1495.0 |
| ARM | 14 | 57.1 | 0.8 ⛔ | -174.0 |
| AVGO | 21 | 66.7 | 1.56 ✅ | +534.0 |
| BAC | 27 | 51.9 | 0.59 ⛔ | -922.0 |
| C | 19 | 68.4 | 2.73 ✅ | +1139.0 |
| CBRE | 14 | 85.7 | 5.7 ✅ | +825.0 |
| CRM | 3 | 66.7 | 0.68 ⛔ | -64.0 |
| CRWD | 14 | 85.7 | 1.83 ✅ | +335.0 |
| CRWV | 1 | 0.0 | 0.0 ⛔ | -118.0 |
| GLW | 14 | 71.4 | 3.01 ✅ | +969.0 |
| GOOG | 13 | 53.8 | 0.6 ⛔ | -480.0 |
| HOOD | 14 | 78.6 | 4.38 ✅ | +1438.0 |
| IBM | 12 | 75.0 | 1.62 ✅ | +374.0 |
| INTC | 7 | 100.0 | 99.9 ✅ | +420.0 |
| JPM | 12 | 58.3 | 1.6 ✅ | +284.0 |
| LRCX | 2 | 50.0 | 0.7 ⛔ | -61.0 |
| MA | 13 | 61.5 | 1.14 ✅ | +116.0 |
| META | 9 | 66.7 | 0.59 ⛔ | -176.0 |
| MSFT | 6 | 33.3 | 0.46 ⛔ | -149.0 |
| MU | 7 | 57.1 | 0.73 ⛔ | -163.0 |
| NET | 6 | 66.7 | 0.96 ⛔ | -15.0 |
| NFLX | 11 | 90.9 | 9.01 ✅ | +1622.0 |
| NKE | 2 | 0.0 | 0.0 ⛔ | -405.0 |
| NOW | 4 | 75.0 | 2.05 ✅ | +141.0 |
| NVDA | 14 | 92.9 | 1789.21 ✅ | +1671.0 |
| ORCL | 9 | 66.7 | 1.39 ✅ | +161.0 |
| PLTR | 10 | 70.0 | 0.88 ⛔ | -73.0 |
| QQQ | 2 | 100.0 | 99.9 ✅ | +83.0 |
| SOFI | 6 | 50.0 | 0.14 ⛔ | -516.0 |
| SPY | 1 | 0.0 | 0.0 ⛔ | -204.0 |
| TSM | 7 | 71.4 | 2.81 ✅ | +395.0 |
| UBER | 9 | 100.0 | 99.9 ✅ | +662.0 |
| UNH | 5 | 80.0 | 1.79 ✅ | +159.0 |
| V | 5 | 100.0 | 99.9 ✅ | +501.0 |
| WFC | 8 | 50.0 | 0.44 ⛔ | -368.0 |

**21/38 symbols PF ≥ 1.0 @3bp in test half.**

## Exit breakdown (TEST half)

| Exit type | n | % |
|---|---|---|
| mean_revert | 289 | 74% |
| atr_stop | 88 | 23% |
| time_cap | 13 | 3% |

## Per-year PF (@ 3 bp, all years)

| Year | n | PF |
|---|---|---|
| 2021 | 45 | 2.1 ✅ |
| 2022 | 96 | 0.85 ⛔ |
| 2023 | 170 | 1.49 ✅ |
| 2024 | 212 | 1.52 ✅ |
| 2025 | 183 | 1.21 ✅ |
| 2026 | 79 | 1.09 ✅ |

## Verdict

**✅ CANDIDATE — Test PF 1.32@3bp / 1.29@5bp, BOTH ≥ 1.10 OOS.**

Clears cost-robust gate. **Not auto-live** — GO_LIVE_CHECKLIST and paper incubation still required (see checklist section below).

## GO_LIVE_CHECKLIST — §1 Edge metrics (test half, @3bp)

_Account size assumed: \$5,000 · test window: 2024-05-31 → 2026-05-19 (2.0 yr)_

| Metric | Value | Threshold | Status |
|---|---|---|---|
| Annualized return (on account) | +65.5%/yr | > 0 | ✅ |
| Test PF @3bp (OOS) | 1.32 | ≥ 1.10 | ✅ |
| Test PF @5bp (OOS) | 1.29 | ≥ 1.10 | ✅ |
| Test PF last 18 months (n=291) | 1.11 | ≥ 1.10 | ✅ |
| OOS decay (train→test) | 2.3% | < −25% = fail | ✅ |
| Annualized Sharpe (@3bp) | 1.32 | ≥ 0.8 | ✅ |
| Max drawdown (% of account) | 38.5% | < 12% | ⛔ |
| Top-3 trades as % of gross profit | 5.5% | < 40% | ✅ |
| SPY B&H total return (same window) | +42.5% | strategy beats SPY ann. | ✅ |

_Note: \$5K account size means strategy P&L is a large % of account — Sharpe and DD figures are sensitive to account-size assumption. Short-selling (bear side) may require margin; borrowing costs not modelled._

_Data: yfinance daily bars (5yr, free). Pre-specified Connors RSI(2) rules. Same \$200 risk budget + 3 & 5 bp cost gate as all prior tests._