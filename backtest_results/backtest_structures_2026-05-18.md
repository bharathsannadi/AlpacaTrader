# Structure Comparison — REAL Polygon 3yr

_Generated 2026-05-18 19:04 ET_

Same **vwap_momentum** entries (the one signal with proven directional edge — signal_diagnostic: 55→60% hit-rate, +0.62 ATR @60m) run through 4 structures. Headline = **Profit Factor** (scale-invariant). $ P&L sized to a $200/trade risk budget so shares vs options are directly comparable. Costs: options ±2% half-spread + $0.65/contract RT; shares 1bp slippage.

## Walk-forward (50/50 split, ranked by TEST PF)

| Structure | n | Train PF | **Test PF** | Test Win% | Test Avg$ | Test Total$ | Test MaxDD$ |
|---|---|---|---|---|---|---|---|
| S3 shares (control) | 1510 | 1.41 | **1.38** | 53.0 | +46.5 | +70212.0 | -4537.0 |
| S0 naked 7-14d (CURRENT) | 1477 | 0.75 | **0.92** | 38.4 | -2.44 | -3601.0 | -7446.0 |
| S1 naked 25-45d +ATR-exit | 1509 | 0.32 | **0.41** | 33.1 | -21.47 | -32396.0 | -32437.0 |
| S2 debit spread +ATR-exit | 629 | 0.0 | **0.0** | 0.2 | -95.45 | -60040.0 | -60040.0 |

## Verdict

- **Current production (S0)** Test PF = **0.92** (net-negative — confirms the 2/10).
- **Shares (S3) is the only/best positive structure (Test PF 1.38).** This confirms the diagnosis exactly: the edge is a STOCK edge; every option wrapper (theta/vega/spread) destroys it. Actionable → build the shares/ETF swing path; drop options.

_REAL Polygon 3yr, real option OHLC, conservative modeled spread. Not a go-live signal on its own — ranks structures; the winner still needs robustness + true-NBBO sensitivity + GO_LIVE_CHECKLIST._