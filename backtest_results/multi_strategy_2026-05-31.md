# KB Multi-Strategy Backtest — 2026-05-31 17:52
_Cost gate: Test PF ≥ 1.10 at BOTH 3 & 5 bp, OOS 50/50 walk-forward. Survivors → paper incubation, NOT live (multiple-comparisons caveat)._

| Strategy | n | Train PF | Test PF 3bp | Test PF 5bp | Win% | 2022 PF | Verdict |
|---|---|---|---|---|---|---|---|
| S1 Connors RSI2 (MR §19) | 790 | 1.27 | 1.35 | 1.32 | 66.1% | 0.85 | ✅ PASS → incubate |
| S2 Bollinger rev (MR §1) | 348 | 1.14 | 1.4 | 1.37 | 57.1% | 0.62 | ✅ PASS → incubate |
| S3 Trend pullback (§8/§14) | 350 | 1.41 | 2.11 | 2.08 | 42.2% | 0.68 | ✅ PASS → incubate |
| S4 52w breakout (§15) | 133 | 2.34 | 1.96 | 1.94 | 40.0% | 0.03 | ✅ PASS → incubate |

## Monthly-P&L correlation

```
                            S1 Connors RSI2 (MR §19)  S2 Bollinger rev (MR §1)  S3 Trend pullback (§8/§14)  S4 52w breakout (§15)
S1 Connors RSI2 (MR §19)                        1.00                      0.49                        0.31                   0.32
S2 Bollinger rev (MR §1)                        0.49                      1.00                        0.19                   0.30
S3 Trend pullback (§8/§14)                      0.31                      0.19                        1.00                   0.35
S4 52w breakout (§15)                           0.32                      0.30                        0.35                   1.00
```
