# Tradable Symbols — Single Source of Truth

_Last refreshed 2026-05-19. Honest per-symbol verdicts from REAL Polygon 3yr backtests.
Cross-references: [ANALYSIS_LOG.md](ANALYSIS_LOG.md), [knowledge_base.md](knowledge_base.md), authoritative list in [`scripts/universe.py`](scripts/universe.py)._

> ## 🚨 Standing rule (non-negotiable)
> **No symbol is approved for real-money trading.** The system has no validated edge yet (Tier-1 + Tier-2 both failed the cost-robust ≥3 bp walk-forward gate; ANALYSIS_LOG 2026-05-19). This file tracks **what we know per symbol**, not what we should trade. Per-symbol PF @3bp is **informational**, NOT permission — even the strongest individual names don't survive 5 bp slippage in aggregate.

---

## Verdict legend

| Symbol | Stock 3yr cached | Options cached | **PF @ 3bp** (robust) | Verdict | Trade real $? |
|---|---|---|---|---|---|
| ⛔ AVOID | PF < 1.00 — systematically negative-EV at realistic cost |
| ⚠️ MARGINAL | PF 1.00–1.10 — coin flip; noise |
| 🟡 LOOKS-POSITIVE | PF ≥ 1.10 @ 3bp — BUT survivorship-suspect; doesn't survive 5bp in aggregate |
| ✅ APPROVED | passing cost-robust gate (≥1.10 @ both 3 *and* 5 bp OOS) — **CURRENTLY ZERO SYMBOLS** |

---

## The 39-symbol research universe (existing 6 + new 33)

PF @ 3 bp values from `backtest_shares_robust.py ALL` (2026-05-19, 18,790 trades, walk-forward).
Options cache status from `backtest_structures.py ALL` (BK-B, in progress; ✅ = cached, 🔄 = pending).

### Existing universe (original 6)

| Symbol | Stock | Options | PF @3bp | Verdict | Real $ |
|---|---|---|---|---|---|
| SPY  | ✅ | ✅ | **0.70** | ⛔ AVOID | ❌ |
| AMZN | ✅ | ✅ | 1.22 | 🟡 looks-positive | ❌ |
| GOOG | ✅ | ✅ | **0.87** | ⛔ AVOID | ❌ |
| MSFT | ✅ | ✅ | **0.79** | ⛔ AVOID | ❌ |
| NVDA | ✅ | ✅ | 1.55 | 🟡 looks-positive *(highest PF; still survivorship-suspect)* | ❌ |
| META | ✅ | ✅ | 1.04 | ⚠️ marginal | ❌ |

### New universe (added 2026-05-19; user request)

| Symbol | Stock | Options | PF @3bp | Verdict | Real $ | Note |
|---|---|---|---|---|---|---|
| AAPL | ✅ | ✅ | 1.10 | 🟡 looks-positive *(borderline)* | ❌ | |
| ADBE | ✅ | ✅ | 1.24 | 🟡 looks-positive | ❌ | |
| AMD  | ✅ | ✅ | 1.15 | 🟡 looks-positive | ❌ | |
| ARM  | ✅ | ✅ | 1.48 | 🟡 looks-positive | ❌ | ~2.5yr partial history (IPO 2023-09) |
| AVGO | ✅ | ✅ | 1.06 | ⚠️ marginal | ❌ | |
| BAC  | ✅ | ✅ | 1.18 | 🟡 looks-positive | ❌ | |
| C    | ✅ | ✅ | 1.13 | 🟡 looks-positive | ❌ | |
| CBRE | ✅ | ✅ | **0.88** | ⛔ AVOID | ❌ | (was CBRS in original request — typo-corrected) |
| CRM  | ✅ | ✅ | 1.12 | 🟡 looks-positive | ❌ | |
| CRWD | ✅ | ✅ | 1.17 | 🟡 looks-positive | ❌ | |
| CRWV | ✅ | ✅ | 1.51 | 🟡 looks-positive | ❌ | ~1yr partial history (IPO 2025) — smallest sample, weakest evidence |
| GLW  | ✅ | 🔄 | 1.01 | ⚠️ marginal | ❌ | BK-B in progress on this symbol |
| HOOD | ✅ | 🔄 | 1.42 | 🟡 looks-positive | ❌ | |
| IBM  | ✅ | 🔄 | 1.14 | 🟡 looks-positive | ❌ | |
| INTC | ✅ | 🔄 | 1.34 | 🟡 looks-positive | ❌ | |
| JPM  | ✅ | 🔄 | 1.01 | ⚠️ marginal | ❌ | |
| LRCX | ✅ | 🔄 | 1.21 | 🟡 looks-positive | ❌ | |
| MA   | ✅ | 🔄 | **0.97** | ⛔ AVOID | ❌ | |
| MU   | ✅ | 🔄 | 1.24 | 🟡 looks-positive | ❌ | |
| NET  | ✅ | 🔄 | 1.22 | 🟡 looks-positive | ❌ | |
| NFLX | ✅ | 🔄 | 1.13 | 🟡 looks-positive | ❌ | |
| NKE  | ✅ | 🔄 | 1.08 | ⚠️ marginal | ❌ | |
| NOW  | ✅ | 🔄 | 1.08 | ⚠️ marginal | ❌ | |
| ORCL | ✅ | 🔄 | 1.12 | 🟡 looks-positive | ❌ | |
| PLTR | ✅ | 🔄 | 1.33 | 🟡 looks-positive | ❌ | |
| QQQ  | ✅ | 🔄 | **0.91** | ⛔ AVOID | ❌ | |
| SOFI | ✅ | 🔄 | 1.48 | 🟡 looks-positive | ❌ | |
| TEAM | ✅ | 🔄 | 1.45 | 🟡 looks-positive | ❌ | |
| TSM  | ✅ | 🔄 | **0.94** | ⛔ AVOID | ❌ | |
| UBER | ✅ | 🔄 | 1.28 | 🟡 looks-positive | ❌ | |
| UNH  | ✅ | 🔄 | **0.96** | ⛔ AVOID | ❌ | |
| V    | ✅ | 🔄 | **0.79** | ⛔ AVOID | ❌ | |
| WFC  | ✅ | 🔄 | 1.00 | ⚠️ marginal | ❌ | |

---

## Summary counts (this universe)

| Bucket | Count | Symbols |
|---|---|---|
| ⛔ AVOID (PF<1.0 @3bp) | **9** | SPY, MSFT, V, GOOG, CBRE, QQQ, TSM, UNH, MA |
| ⚠️ MARGINAL (1.0–1.10) | 7 | AVGO, GLW, JPM, META, NKE, NOW, WFC |
| 🟡 LOOKS-POSITIVE @3bp | 22 | AAPL, ADBE, AMD, AMZN, ARM, BAC, C, CRM, CRWD, CRWV, HOOD, IBM, INTC, LRCX, MU, NET, NFLX, NVDA, ORCL, PLTR, SOFI, TEAM, UBER |
| ✅ APPROVED real-money | **0** | none — no strategy clears the cost-robust ≥3&5bp gate |

**Pattern observed:** ⛔ AVOID skews to **low-volatility index/mega-cap** names (SPY/QQQ/MSFT/V/GOOG/MA). 🟡 looks-positive skews to **high-volatility single names** (NVDA/CRWV/ARM/SOFI/TEAM/HOOD/PLTR/INTC). This is structurally coherent (Sinclair: fixed costs vs movement) but does NOT clear the gate — picking only the winners is the survivorship trap.

---

## S&P 500 cache (broader research universe)

| Status | Detail |
|---|---|
| ✅ Cached | 503/503 (BK-A complete 2026-05-19; 4.2 GB; cache `~/Desktop/AlpacaTrader_Data/polygon_cache`) |
| Partial history | 11 names — recent IPOs/spinoffs (GE Vernova, Solventum, Veralto, Block→XYZ, SanDisk, etc.). Max-available history, not data errors. |
| Per-symbol backtest | NOT run on full 503 yet — would need ~13× the 39-ticker runtime. Available for Path A (daily-bar harness) or targeted future tests at $0. |

List: see [`scripts/sp500.json`](scripts/sp500.json) (authoritative — pulled via pandas.read_html, **not** WebFetch which hallucinated a garbage tail).

---

## How this file gets updated

| Event | Update |
|---|---|
| New backtest run | Update PF column, refresh "Last refreshed" date, log in ANALYSIS_LOG |
| BK-B options cache progress | Flip 🔄 → ✅ in Options column per symbol |
| A strategy clears the cost-robust gate (≥1.10 @ both 3 & 5 bp OOS) | THAT strategy gets a section here listing approved symbols; "Real $" column flips to "paper-only" until GO_LIVE_CHECKLIST signed |
| Universe expansion | Add to `scripts/universe.py` first, then append row here |
| Symbol delisting / corporate action | Move to "Excluded" section with reason |

## Excluded / problematic symbols

_(none yet — when one fails BK-A or fragments via corporate action, log it here with reason and date)_

---

## Sources

- Per-symbol PF @3bp: `backtest_results/backtest_shares_robust_2026-05-19.md`
- Options cache progress: `/tmp/optbackup39.log` (BK-B run)
- Cost-robust gate definition: KB §12 (Davey validation ladder)
- Survivorship-trap warning: ANALYSIS_LOG 2026-05-19 (S3 correction, 39-ticker structural finding)
