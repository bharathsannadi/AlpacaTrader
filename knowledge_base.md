# Options Trading Knowledge Base

> Distilled from 30+ professional options & trading books in `/Users/bsannadi/Desktop/books/Trading/Options Trading`:
> **Foundations:** Natenberg (*Option Volatility and Pricing*), Passarelli (*Trading Option Greeks*), Saliba (*Option Spread Strategies*, *Option Strategies for Stock/Index/Commodity*), Hull (*Options, Futures and Other Derivatives*)
> **Pricing & Quant:** Sinclair (*Option Trading: Pricing & Volatility*), Haug (*Complete Guide to Option Pricing Formulas*), Statistics of Financial Markets (2013), Option Pricing Models (2007)
> **Strategies & Spreads:** Lowell (*Get Rich With Options*), Smith (*The Complete Guide to Option Strategies*), Saliba (*Option Spread Strategies*), Levy (*Your Options Handbook*)
> **Price Action & Volume:** Holmes (*Complete Volume Spread Analysis System* — VSA/Wyckoff), Brooks (*Trading Price Action Trends*)
> **Put-Specific:** Thomsett (*Put Option Strategies for Smarter Trading*, *Options Trading for the Conservative Investor*)
> **Risk & Discipline:** Fontanills (*The Options Course*, *Trade Options Online*), Benklifa (*Think Like an Option Trader*), Schwager (*Complete Guide to the Futures Market*)
> **Specialty:** Cofnas (*Trading Binary Options* — sentiment/NFP analysis applicable to intraday bias)
> **Quick reference:** OIC (*Option Strategies Quick Guide*), Danes (*Options Trading QuickStart*, *Options Trading Strategies*), Optionetics, Trading Options For Dummies
>
> **Purpose:** AI trading system reference for debate gate, signal evaluation, and trade approval.
> **System trades:** SPY + AMZN, GOOG, MSFT, NVDA, META long calls/puts, 7-14 DTE, ORB/VWAP/EMA signals on 5-min bars.

---

## 1. Greeks Quick Reference

### Delta (Δ)
- **Definition:** Rate of change in option price per $1 move in underlying. Call deltas: 0 to +1.00. Put deltas: −1.00 to 0.
- **ATM options:** Delta ≈ 0.50 (call) / −0.50 (put). Moves at ~50% of underlying.
- **ITM options:** Delta approaches 1.00 (call) / −1.00 (put). Behaves increasingly like the underlying.
- **OTM options:** Delta < 0.30 (call) / > −0.30 (put). High leverage but low probability.
- **Directional plays (intraday ORB/VWAP):** Target delta **0.40–0.60**. Enough leverage without theta-destroying deep OTM.
- **Aggressive momentum plays:** Delta 0.30–0.45 acceptable if entry is clean and move is expected to be fast.
- **Delta as probability proxy:** A 0.40-delta option has approximately 40% chance of expiring ITM.
- **Delta changes with price:** As underlying moves toward your strike, delta accelerates (gamma effect). A 0.40-delta call can become 0.60-delta after a $2 SPY move — this is your exit zone.
- **Hedge ratio:** To fully hedge 1 option contract (~100 shares equivalent), sell/buy 100/delta shares of underlying.

### Gamma (Γ)
- **Definition:** Rate of change of delta per $1 move in underlying. Long options = long gamma (always positive). Short options = short gamma.
- **Gamma is highest at ATM, near expiration.** A 7 DTE ATM option has dramatically more gamma than a 30 DTE ATM option.
- **Intraday implication:** High gamma near expiration means your delta changes rapidly — a $1 SPY move can shift your delta by 5–15 points on a 7 DTE option. This is a double-edged sword: faster gains on winners, faster losses on reversals.
- **Gamma risk:** Short gamma positions (credit spreads) blow up on large fast moves. Long gamma positions (debit spreads, long options) benefit from large moves.
- **Gamma scalping:** Professional traders delta-hedge and profit from gamma by rebalancing when underlying moves. Retail traders should simply close long options when they hit profit targets rather than try to gamma-scalp.
- **Rule:** Never hold short gamma positions (naked short calls/puts or credit spreads) through a catalyst event or expected large move.

### Theta (Θ)
- **Definition:** Dollar amount an option loses per calendar day (all else equal). Always negative for long options.
- **Theta acceleration:** Theta decay is **not linear** — it accelerates in the final 30 days and becomes extreme in the last 7 days.
  - 30 DTE option: theta might be −$0.05/day
  - 14 DTE option: theta might be −$0.10/day
  - 7 DTE option: theta might be −$0.20/day
  - 2 DTE option: theta might be −$0.50+/day
- **ATM theta is highest** — theta decays fastest for ATM options, not deep ITM or deep OTM.
- **Weekend theta:** Friday close prices in weekend time decay (Saturday + Sunday). Expect options to open lower Monday morning by ~2–3 days of theta even though only 1 trading day passed.
- **Intraday theta:** On 7 DTE options, theta decay in one trading session (~6.5 hours) is approximately 1/7th of remaining weekly value. On strong days, a $0.20 daily theta loss is $0.13 by 3PM even if the underlying hasn't moved.
- **Rule:** Do NOT hold 7 DTE options overnight unless the position is profitable and the underlying thesis is intact. Overnight theta is free money to the seller and costs you.

### Vega (ν)
- **Definition:** Dollar change in option price per 1% change in implied volatility (IV). Always positive for long options.
- **Vega is highest for ATM options and longer-dated options.** A 30 DTE ATM option has ~3x the vega of a 7 DTE ATM option.
- **IV spike = windfall for long option holders.** A 5-point IV spike on a 14 DTE option might add $0.30–0.60 to the option price independent of directional move.
- **IV crush = disaster for option buyers.** Post-earnings IV can collapse 30–60%. Never buy options right before an expected IV crush event.
- **Intraday vega moves:** SPY IV can swing 2–4 points intraday during news events. For a 14 DTE ATM SPY option with vega ≈ 0.15, a 3-point IV spike adds $0.45.
- **Vega vs. theta trade-off:** Buying longer-dated options (30+ DTE) gives you more vega exposure but also more theta bleed. Buying shorter-dated (7–14 DTE) reduces vega but amplifies theta risk.
- **Rule:** Buy options when IV is low (IV rank < 30%) to maximize vega gains if IV expands. Avoid buying when IV rank > 50% — you are overpaying and subject to vega headwind.

### Rho (ρ)
- **Definition:** Option price sensitivity to interest rate changes. Calls increase with rising rates; puts decrease.
- **Relevance for intraday:** Minimal. Rho matters for LEAPS (1+ year options). For 7–14 DTE intraday trades, rho is essentially zero and can be ignored.

### Greeks Summary Table

| Greek | Long Call | Long Put | Impact on Intraday Trade |
|-------|-----------|----------|--------------------------|
| Delta | +0 to +1 | −1 to 0 | Primary P&L driver |
| Gamma | Positive | Positive | Accelerates delta on moves; highest near expiration |
| Theta | Negative | Negative | Constant drag; fatal if underlying stalls |
| Vega | Positive | Positive | IV expansion = bonus; IV contraction = loss |
| Rho | Positive | Negative | Negligible for <30 DTE |

---

## 2. IV & Volatility Rules

### IV Rank (IVR) vs. IV Percentile
- **IV Rank (IVR):** Where current IV sits relative to its 52-week range. `IVR = (Current IV − 52wk Low) / (52wk High − 52wk Low) × 100`
- **IV Percentile:** What % of days over the past 52 weeks had IV lower than today's IV.
- **When to BUY options (long premium):** IVR < 25–30%. IV is historically cheap; you are buying vega at a discount. If IV reverts to mean, you get a tailwind.
- **When to SELL premium (credit spreads, covered calls):** IVR > 50%. IV is elevated; mean reversion will compress premium.
- **Gray zone (30–50% IVR):** Neutral. Use debit spreads to limit vega risk.
- **Rule:** For this system's long calls/puts strategy, **only buy naked options when IVR < 30%**. Between 30–50%, prefer debit vertical spreads. Above 50%, avoid buying naked premium entirely.

### IV Mean Reversion
- IV is strongly mean-reverting. When IV is at the top of its 52-week range and significantly above historical volatility (HV), expect it to decline toward the mean. (Wiley/Smith)
- When IV is at the bottom of its range and below HV, expect it to expand.
- **Practical rule:** If current IV > 1.5× its 30-day HV, IV is overpriced. Debit spreads or wait.
- **VIX as market-wide IV proxy:** VIX < 15 = low volatility regime (buy premium cheaply). VIX 15–25 = normal. VIX > 25 = elevated fear (IV rich, be cautious buying naked). VIX > 30 = extreme fear; IV crush risk is high post-spike.

### Implied vs. Historical Volatility Divergence
- **IV >> HV (IV premium):** Market is paying more for protection than realized moves justify. Signals: sell premium via spreads, or avoid buying naked options.
- **IV << HV (IV discount):** Market is underpricing options relative to actual moves. Signals: buy premium aggressively; debit spreads make sense.
- **Rule of thumb:** If IV is more than 20% above recent 10-day HV, options are expensive. If IV is more than 20% below recent 10-day HV, options are cheap.

### Volatility Regimes
- **Low vol regime (VIX < 15):** Trending market, small daily ranges. Best for: directional debit spreads, trend-following long calls/puts. Gamma scalping less effective.
- **Normal vol regime (VIX 15–25):** Standard conditions. ORB breakouts and VWAP momentum plays have good follow-through. Options fairly priced.
- **High vol regime (VIX 25–40):** Large intraday swings. Options expensive but moves justify premium. Use tighter stops (underlying can reverse sharply). Debit spreads preferred over naked long options.
- **Spike regime (VIX > 40):** Crisis conditions. IV is extremely elevated. Selling premium has edge but risk is enormous. For directional traders: if you must trade, use spreads with defined risk.

### VIX-SPY Relationship
- VIX and SPY move inversely ~80% of the time. VIX spike = SPY drop.
- VIX reaching key levels (20, 25, 30, 35) often marks short-term SPY turning points.
- When VIX spikes and SPY sells off hard, put IV can be extremely inflated — selling put spreads has edge here, NOT buying puts.
- When VIX is subdued and SPY is grinding up, call options are cheap relative to the trend.

---

## 3. Entry & Exit Timing

### When NOT to Enter

1. **Within 30 minutes of market open (9:30–10:00 AM ET):** Price discovery is chaotic. Bid-ask spreads are widest. IV spikes on open then collapses. Wait for the ORB to define itself. Exception: pre-planned gap trades with defined risk.
2. **12:00–2:00 PM ET (lunch lull):** Lowest volume of the day. Options spreads widen. Theta bleeds with no movement. Avoid new entries; only manage existing positions.
3. **Within 5–10 minutes before/after major economic data releases (CPI, FOMC, NFP, GDP):** IV spikes into the print and collapses immediately after. Buying before data = buying the IV premium. If you want to play data, enter after the release once direction is clear.
4. **After 3:30 PM ET:** Positions can reverse into close on portfolio rebalancing and options pinning. Last 30 minutes are unreliable for new entries; focus on exits.
5. **DTE < 3 (excluding 0DTE strategy):** Theta decay is catastrophic unless the trade is already profitable and in-the-money. A 2 DTE option that is OTM needs an immediate large move to be profitable — the house edge is enormous.
6. **When IV rank > 50% for single-leg long options:** You are overpaying. The IV premium will crush you if the underlying doesn't move immediately.
7. **Earnings within 2 trading days:** IV will spike into earnings and implode after. Never buy naked calls/puts into earnings for this system. Use earnings plays only if explicitly designed for IV crush (e.g., iron condors).
8. **When the ORB has not confirmed direction:** The first 15-minute candle defines the range. Do not enter a long call until price closes above the ORB high, and vice versa. A false breakout within the first 30 minutes is extremely common.

### When to Enter (Best Conditions)
- **10:00–11:30 AM ET:** After ORB confirmation. Volume is strong. IV has settled from open spike. Best window for fresh breakout entries.
- **2:00–3:30 PM ET:** Second window. Late-day momentum often drives continuation. VWAP reclaims and breakouts are reliable in trending markets.
- **ORB breakout confirmation:** Price closes one full 5-min candle above (calls) or below (puts) the ORB high/low with volume above the 20-period average.
- **VWAP reclaim:** Price bounces from VWAP with a bullish candle (calls) or breaks below VWAP and retests from below (puts).
- **EMA alignment:** 8 EMA > 21 EMA > 50 EMA (bullish stack) = call entries. Reverse for puts.

### Profit Targets and Exits
- **Intraday long options: take 50% of max expected move.** Do not hold for "the full move" — theta and gamma reversal risk eats into profits.
- **Preferred profit target:** 50–100% of premium paid, taken on the same day.
- **Time-based exit:** If position is not profitable by 2:30 PM, exit to avoid last-hour reversal and overnight theta.
- **Do not average down on losing options.** A losing option that requires averaging down is a thesis violation — exit and reassess.
- **IV-based exit:** If IV spikes sharply in your favor (e.g., fear spike benefits your put), consider taking 50%+ of the gain even if the underlying hasn't moved as far as expected, because IV crush may eliminate gains quickly.

---

## 4. Position Sizing & Risk

### Risk Per Trade
- **Maximum risk per trade: 1–2% of total trading capital.** This is the professional standard (McMillan, Natenberg). For a $25,000 account: max $250–500 per trade.
- **Never risk more than 5% of account on a single trade** under any circumstances. For $25,000 account: max $1,250 hard stop.
- **Options position sizing:** Since options can go to zero, size based on maximum dollar loss (full premium paid), not notional exposure.
  - Example: If you risk $300 per trade and the option costs $1.50 ($150/contract), buy 2 contracts. If it costs $3.00 ($300/contract), buy 1 contract.

### Maximum Exposure
- **Maximum simultaneous exposure: 5–10% of account in open option premium at risk.** For $25,000 account: max $1,250–2,500 in open positions.
- **Correlation warning:** SPY + AMZN + GOOG + NVDA calls are all long beta. In a market-wide selloff, all positions move against you simultaneously. Treat them as a single correlated book.
- **Maximum correlated positions:** No more than 3 simultaneous long-premium positions in the same direction. Long call + long call + long call = 3× correlated beta risk.
- **Hard daily loss limit: 3–5% of account.** For $25,000 account: $750–1,250 max daily loss. Hit it, stop trading for the day.

### Stop-Loss Philosophy

**Underlying-move-based stops:**
- For 5-min ORB plays: Stop the underlying move below the ORB high (if long call) or above the ORB low (if long put). If SPY breaks back inside the ORB, the trade thesis is invalidated — exit immediately.
- For VWAP plays: Stop if SPY closes a 5-min candle on the wrong side of VWAP by more than 0.15%.

**Premium-percentage stops:**
- **Standard intraday stop: 50% of premium paid.** If you pay $2.00 for an option and it drops to $1.00, exit. Do not wait for total loss.
- **Aggressive stop: 30% of premium paid** in trending/volatile conditions where a losing trade can go to near-zero quickly (high gamma, short DTE).
- **Maximum hold to: 80% loss.** Under no circumstances hold an option position that has lost more than 80% of its value hoping for a reversal. The math of recovery is brutal: a position down 80% needs a 400% gain to break even.

**Why premium-% stops matter more than underlying-% stops for short DTE:**
- A 7 DTE OTM option can lose 50% of its value on a 0.3% adverse move in SPY due to delta + negative theta compounding. An underlying-only stop misses this.
- Always monitor the OPTION price, not just the underlying.

### Position Sizing Formula
```
Contracts = Floor(Max_Dollar_Risk / Option_Premium_Per_Contract)
Max_Dollar_Risk = Account_Size × Risk_Percent (0.01 to 0.02)
Option_Premium_Per_Contract = Ask_Price × 100
```
Example: Account $25,000, 1.5% risk = $375 max risk. Option at $1.80 ($180/contract) → 2 contracts ($360 at risk).

### Kelly Criterion & Risk of Ruin (Sinclair, *Volatility Trading* Ch.8) — added 2026-05-19
- **Sizing is determinative of returns, not a detail.** Two traders with the *same* winning edge can have opposite outcomes purely from bet size.
- **Kelly fraction** ≈ edge / odds = the bet size that maximizes long-run geometric growth. For a realistic intraday edge (~53% hit, reward ≈ risk) the full-Kelly fraction is *small* (low single-digit % of bankroll).
- **Hard rule: betting > 2× Kelly turns a positive-edge strategy's growth rate NEGATIVE** and tends to ruin — a sound method then *looks* like a failure purely from oversizing. Never let stated risk tolerance exceed 2× the Kelly of the *validated* edge.
- **Use ≤ ½-Kelly in practice** — captures most of the growth at far lower volatility and drawdown. This (not a flat %) is the correct mechanism for scaling an account up as edge is confirmed.
- **Estimate Kelly from the strategy's own backtested win-rate / payoff**, not from hope. No validated edge ⇒ no basis for sizing ⇒ do not size up.

---

## 5. Strategy Selection (Naked vs. Spreads)

### Decision Framework: When to Use Each Strategy

| Condition | Strategy | Reason |
|-----------|----------|--------|
| IVR < 25%, strong directional signal | Naked long call/put | Cheap premium; full delta exposure; IV expansion bonus |
| IVR 25–50%, directional signal | Debit vertical spread | Cap vega risk; reduce cost; defined risk |
| IVR > 50%, directional signal | Debit spread only, or skip | Naked long options overpriced |
| Neutral/range market, IVR > 40% | Iron condor or skip | Sell elevated premium |
| Strong trend + breakout | Naked call/put or bull/bear call/put spread | Maximize delta exposure |
| Uncertain magnitude, strong direction | ATM debit spread | Cheaper entry, limited upside |

### Debit Vertical Spreads (Bull Call / Bear Put Spread)

**When debit spreads beat naked long options:**
1. IV rank > 30%: Spreads reduce your vega exposure. You buy the near strike (paying IV) and sell the far strike (receiving IV), netting to a lower overall vega.
2. You need to reduce cost basis when premium is expensive.
3. You have a target price level — spreads let you define a range and collect maximum profit if underlying lands between the strikes.
4. Theta drag is reduced: The sold leg partially offsets theta decay on the long leg.

**Construction rules for debit spreads:**
- **Strike selection:** Buy ATM (delta ~0.50) or slightly OTM (delta ~0.40). Sell 1–2 strikes further OTM (delta ~0.20–0.30).
- **Width:** For SPY, typical spread width is $1–$3 for intraday/weekly plays. Wider spreads cost more but have higher max profit.
- **Max profit zone:** Price needs to close above (bull call spread) or below (bear put spread) the short strike at expiration.
- **Break-even:** Long strike + net debit paid.
- **Debit paid:** Should be 30–40% of the spread width for a good risk/reward. Example: $2 wide spread, pay no more than $0.70–0.80.
- **Max risk = debit paid. Max reward = spread width − debit paid.**

**Example (from Saliba, *Option Spread Strategies*):**
- Bull Call Spread: Buy Sept 95 call at $5.00, sell Sept 100 call at $3.50. Net debit = $1.50. Max profit = $3.50. Break-even = $96.50.

### Naked Long Options

**When naked long options beat spreads:**
1. IVR < 20%: premium is cheap; paying full vega is not punishing.
2. You expect a large, fast move: spread caps your upside. If you're right about a big move, spreads leave money on the table.
3. DTE is short (7–14 days): The sold leg of a spread adds complexity and doesn't help much with theta when both legs decay quickly.
4. Breakout plays with momentum: ORB confirmed breakout — you want maximum delta exposure, not capped upside.

**Danger of naked long options:**
- Full premium at risk. Can lose 100%.
- Vega headwind if IV compresses.
- Theta erodes constantly.
- For this system: use naked options ONLY with strict 50% premium stop-loss.

### Spread Slippage Consideration
- Spreads have two legs → two bid-ask spreads → higher total slippage. For liquid SPY options: spread slippage is minimal ($0.02–0.05 per leg). For less-liquid names (NVDA, GOOG pre-split), spread slippage can be $0.05–0.15 per leg — use limit orders.

### Transaction-Cost Hierarchy (Sinclair, p.67) — added 2026-05-19
- **Total round-trip cost, lowest → highest: shares < futures ≪ single options ≪ multi-leg option spreads.** Option costs (wide bid/ask relative to price + per-contract fees + clearing) are *materially* higher than equity costs.
- **Decision rule for a thin directional edge:** express it in the **cheapest instrument that carries it**. A small directional edge (no volatility edge) is structurally destroyed by option-level costs but can survive in shares. Only move it into options when a *separate volatility edge* is present to pay for the higher cost (Natenberg §8 / Smith §8 — "no edge without a volatility edge").

---

## 6. Intraday Patterns & Setups

### Opening Range Breakout (ORB)

**The setup:**
- Define the opening range as the high and low of the **first 15 minutes** (9:30–9:45 AM). Some traders use 30-minute ORB.
- **Long signal:** SPY closes a 5-min candle **above** the ORB high with above-average volume. Buy calls.
- **Short signal:** SPY closes a 5-min candle **below** the ORB low with above-average volume. Buy puts.

**ORB rules of thumb:**
- Wait for the **second** 5-min close confirmation to avoid fakeouts. The initial breakout candle can be a trap.
- Strongest ORB days: gap up + hold above ORB = trend day up. Gap down + hold below ORB = trend day down.
- ORB breakouts before 10:30 AM that are NOT confirmed by volume are 40–60% likely to fail (fade). Volume confirmation is mandatory.
- **Avoid ORB entries after 11:00 AM** — the "ORB" at that point is just yesterday's news.

**Target and stop for ORB:**
- Target: 1× ORB range above breakout (if ORB is 1.0 points wide, target is 1.0 points above breakout level).
- Stop: Option premium 50% loss OR underlying closes back inside the ORB.

### VWAP Momentum

**VWAP rules:**
- **Bullish:** Price is above VWAP AND bounces off VWAP with a bullish candle → buy calls.
- **Bearish:** Price is below VWAP AND retests VWAP from below and rejects → buy puts.
- VWAP reclaim (price crosses above from below with volume) = potential long entry.
- VWAP breakdown (price crosses below from above with volume) = potential short/put entry.
- **Do not enter** if price is oscillating around VWAP (choppy/sideways) — no directional edge.

### Gap Fills

- SPY gaps of 0.2–0.5% frequently fill the same day (50–65% fill rate in normal conditions).
- Gaps > 1% from previous close fill the same day ~35% of the time.
- **Gap fill trade:** If SPY opens down 0.4% below previous close, look for a VWAP reclaim within the first 45 min as entry for calls targeting the gap fill.
- **Gap & Go:** If SPY opens above previous close and holds above VWAP for 2 consecutive 5-min candles, the gap may extend rather than fill. In this case, buy calls with stop below VWAP.

### EMA Signal Alignment

**EMA stack (5-min chart):**
- **Bullish alignment:** 8 EMA > 21 EMA > 50 EMA (EMAs fanning out upward, price above all three).
- **Bearish alignment:** 8 EMA < 21 EMA < 50 EMA (EMAs fanning out downward, price below all three).
- **Golden trigger:** 8 EMA crosses above 21 EMA from below while 50 EMA is also curling up = buy calls.
- **Death trigger:** 8 EMA crosses below 21 EMA from above while 50 EMA is curling down = buy puts.
- **EMA compression:** When all three EMAs are converging tightly (within 0.1%), the market is coiling. Do not enter; wait for a directional break.

### Key Intraday Price Levels

- **Previous day's high/low:** Major resistance/support. Strong magnets for price. ORB breakout through previous day's high with volume = very strong bull signal.
- **Round numbers (SPY: 500, 505, 510 etc.):** Psychological levels where options are heavily struck. Price tends to pin near these levels near expiration.
- **Pivot points:** Weekly and daily pivots act as intraday support/resistance.
- **Pre-market high/low:** If SPY breaks above pre-market high after open = momentum long. Break below pre-market low = momentum short.

### Time-of-Day Patterns

- **9:30–10:00:** ORB formation. High volatility, wide spreads, often directional. Wait and observe.
- **10:00–11:30:** Best window. Direction usually set. ORB breakout entries. Best liquidity.
- **11:30–12:00:** Volume declining, potential reversal of morning move.
- **12:00–2:00:** Lunch lull. Avoid new entries. Options bleed theta with no movement.
- **2:00–3:00:** Fed-induced moves, late institutional positioning. Momentum plays resume.
- **3:00–3:30:** Power hour. Strong trend continuation or sharp reversal. High volume.
- **3:30–4:00:** Last 30 minutes — options pinning, portfolio hedging, erratic. Close profitable positions; do not open new ones.

---

## 7. Common Mistakes to Avoid

### Greek-Related Mistakes

1. **Buying deep OTM options (delta < 0.20) expecting lottery payoffs.** These options need massive moves to profit. They are 70–80% likely to expire worthless. A $0.30 OTM call on SPY has 1-in-5 odds — fine for speculation, not for systematic trading.

2. **Ignoring theta on 7 DTE options.** A $1.00 ATM option with 7 DTE loses ~$0.14/day in theta alone. If the underlying moves 0.3% in your favor but it takes 3 days to happen, you may still lose money.

3. **Not accounting for vega when buying ahead of data.** IV before FOMC/CPI can be 5–10 vol points higher than baseline. After the print, IV collapses to baseline — even if you're directionally right, you can lose money on the trade. **Buy post-announcement, not pre-announcement.**

4. **Confusing delta with probability of profit.** Delta ≈ probability of expiring ITM, but the probability of MAKING money on the option is lower due to theta and the premium paid.

### Entry/Exit Mistakes

5. **Entering at market open (9:30–9:45 AM).** Spreads are widest, IV is highest of the day, price action is chaotic. The first 15 minutes are not for entering — they are for observing.

6. **Holding losing options into expiration hoping for a reversal.** A 7 DTE OTM option that is down 60% at 1 PM on a non-directional day is almost certainly going to zero. Cut losses and redeploy capital.

7. **Chasing entries after a big move.** If SPY has already moved 1% in the first hour, the options have priced in the move. Entering a call after a 1% gap up is buying at the top of the move — expensive delta with maximum theta ahead.

8. **Not using limit orders.** Market orders on options result in immediate slippage of $0.05–0.20 per contract. Always use limit orders at the mid or 1 cent below mid.

### Risk Management Mistakes

9. **Sizing too large on high-conviction trades.** "High conviction" does not mean higher success probability. It means higher emotional attachment, which impairs exit discipline. Use the same size rule for every trade.

10. **Averaging down on losing options.** Adding to a losing option position increases your capital at risk. It is valid in equities; it is **not** valid in options where the position can go to zero. Every additional contract you buy on a loser extends your maximum loss.

11. **Not having a pre-defined stop before entry.** Without a pre-defined exit, emotion takes over. The stop should be stated in the trade record: "I exit if this option loses 50% OR if SPY breaks back below [specific level]."

12. **Letting small losses become catastrophic losses.** The distribution of option losses is asymmetric: you lose 100% of the premium (maximum), but the average loser, if disciplined, should be −40 to −50%. A single undisciplined 90% loss wipes out the equivalent of 3–4 disciplined 50% losses.

### Strategy Selection Mistakes

13. **Buying naked options when IVR > 50%.** You are paying a premium for expected volatility that likely won't materialize. The deck is stacked against you from the start.

14. **Using spreads so narrow that slippage eliminates the edge.** A $0.50-wide spread with $0.05 slippage per leg = $0.10 slippage on a $0.20–$0.25 edge. The spread is barely worth trading.

15. **Treating options as "cheap" because the premium is low in dollar terms.** A $0.30 OTM weekly option is not cheap — it has a 70–80% chance of expiring worthless and the risk-adjusted return may be negative.

16. **Ignoring liquidity.** Low open interest options have wide bid-ask spreads. If the spread between bid and ask is $0.30 on a $1.00 option, you immediately lose 30% of your value on entry. Only trade liquid options: SPY, SPX, QQQ and liquid mega-caps. Check that bid-ask spread < 5% of mid price before entering.

---

## 8. Key Rules from the Masters

### Natenberg (*Option Volatility and Pricing*)
- "Volatility is perhaps the most important dimension in options trading. A trader who ignores volatility will find it much more difficult to be consistently profitable."
- **The delta is only an approximation** — it is the instantaneous rate of change, not the actual P&L for a $1 move. Gamma means the delta itself changes as price moves.
- **Implied volatility IS the option market's opinion** of future realized volatility. When you buy an option, you are expressing a bet that future realized volatility will EXCEED current implied volatility.
- Key insight: **You can be directionally right and still lose money** on a long option if: (a) the move is too slow (theta kills you), (b) IV collapses (vega kills you), or (c) the move is smaller than priced in.
- "Traders who fail to consider the risks associated with their position are certain to have a short and unhappy career."

### Saliba (*Option Spread Strategies*)
- **Covered writes and credit positions are NOT "fire and forget."** They require active management. If the underlying's behavior deviates from forecast, exit or neutralize immediately.
- **Never use rate of return to determine if a covered-write is appropriate** — that is a trap. Use forecast direction first; rate of return is only a measure of the risk being priced.
- **Short gamma positions (all credit positions) must be managed ruthlessly** when the underlying moves outside expected range.
- **IV is the primary tool for strategy selection:** High IV = sell premium (spreads). Low IV = buy premium (naked options or debit spreads).

### Smith (*Option Strategies*, Wiley)
- **Implied volatility is mean-reverting.** Trade with mean reversion: sell premium when IV is at the top of its range; buy premium when IV is at the bottom.
- The options market is too efficient to simply buy or sell indiscriminately. "70–80% of options expire worthless" is a misleading statistic — the winners are large enough to balance the losers. Neither pure buying nor pure selling has an inherent edge without a volatility edge.
- **Liquidity first:** "An illiquid market is like a Roach Motel — you can get in but you can't get out."
- **Monitor all Greeks** during a trade, not just delta. A delta-neutral position can still have large P&L swings from gamma, vega, and theta.

### Benklifa (*Think Like an Option Trader*)
- **Options expire — everything about options pricing revolves around this deadline.** Stock traders who enter options without internalizing the deadline will fail.
- **The biggest reason stock traders lose money in options: they don't understand how pricing works.** They lose even when their directional prediction is correct.
- **Time decay is your friend OR your enemy** — understand which side you are on at all times. Sellers of premium benefit from theta. Buyers of premium fight theta.
- **Weekend theta:** At end of Friday, options price in 3 days of theta (Sat, Sun, Mon). Holding long options over the weekend without a strong directional thesis is giving away free money.
- **Known events (earnings, FOMC, CPI) cause predictable IV patterns.** IV rises into the event and collapses after. You can trade this IV pattern directly.

### Lowell (*Get Rich With Options*)
- **Be a net seller of premium when conditions warrant** — professional floor traders are net short premium because customers want to buy options, not because selling is inherently superior.
- **The four winning strategies: covered calls, selling naked puts, bull call spreads, bear put spreads.** Premium selling strategies with defined risk outperform naked long options as a systematic approach.
- **Sell OTM options with 30–45 DTE** at the sweet spot of theta decay vs. gamma risk.

### Thomsett (*Put Option Strategies*)
- **Stops must be pre-planned.** "The mistake most traders make is that they watch their positions going against them without a plan to exit."
- **Use puts as insurance on existing positions.** The value of a put is not just directional — it is protection value.
- **Avoid holding long puts through periods of low IV** — you are paying time premium that will decay without IV expansion to compensate.

### Sinclair (*Volatility Trading*) — added 2026-05-19
- **The options edge is a volatility-forecasting edge, not a directional one** (p.14). A directional view alone, expressed as long premium, has no edge — you are paying the market's implied volatility for movement already priced in.
- **Option transaction costs (brokerage + bid/ask + fees + clearing) are *far larger* than the costs of trading stocks or futures** (p.67). Implication: a *thin* directional edge belongs in the **lowest-cost instrument** (shares), not options, unless a genuine volatility edge is also present to overcome the higher option cost.
- **Volatility stylized facts:** vol mean-reverts and clusters; more large up-moves than down; vol is positively correlated with both price level and volume (p.54–90).
- **Money management is determinative, not a detail:** betting **more than 2× the Kelly fraction turns a *positive-edge* strategy's growth rate negative** and courts ruin (Ch. 8, p.149). Half-Kelly captures most of the growth at far lower drawdown. Kelly applies to all return distributions, not just binary.

### Gunn (*Trading Regime Analysis*) — added 2026-05-19
- **There is no holy grail; the edge is regime selection.** A trend/directional strategy "loses heavily" in non-trending (range) regimes and "wins superbly" in trending regimes (p.24). Net P&L is decided by the regime mix, *not* the signal in isolation.
- **Practical rule:** never evaluate or deploy a directional/momentum strategy *un-conditioned on regime*. Gate entries to the trending regime (ADX, Bollinger-band-width, or a chop detector); a strategy that looks marginal on aggregate is often strong-in-trend diluted by negative-in-chop.

---

## 9. Checklist Before Every Trade

Use this checklist before submitting any order. Each item should have a definitive YES or NO.

### Market Conditions
- [ ] **VIX level noted.** VIX < 20: low vol regime. VIX 20–25: normal. VIX > 25: elevated. Adjust size down if VIX > 25.
- [ ] **IV Rank (IVR) checked.** IVR < 30%: OK for naked long. 30–50%: use spread. > 50%: do not buy naked options.
- [ ] **Major catalyst within 24 hours?** FOMC, CPI, earnings within 24 hours = NO naked options. Use defined-risk spread or skip.
- [ ] **Current time of day.** 9:30–10:00 AM: do not enter. 10:00–11:30 AM or 2:00–3:30 PM: optimal. 12:00–2:00 PM: avoid.

### Signal Quality
- [ ] **ORB confirmed?** (If ORB strategy): Price closed one full 5-min candle above/below ORB high/low with above-average volume.
- [ ] **VWAP confirmation?** Price direction aligned with VWAP (above for calls, below for puts).
- [ ] **EMA alignment?** 8 > 21 > 50 (calls) or 8 < 21 < 50 (puts). All three pointing in trade direction.
- [ ] **At least 2 of 3 signals align** (ORB + VWAP + EMA). Do not trade on a single signal.

### Option Selection
- [ ] **DTE is 7–14 days.** Less than 7 DTE for non-0DTE strategy = reject.
- [ ] **Delta is 0.35–0.65.** Below 0.35 (too OTM) or above 0.65 (overpaying for ITM) = reconsider.
- [ ] **Bid-ask spread < 5% of mid price.** Wide spreads kill edge.
- [ ] **Open interest > 500 contracts on selected strike.** Liquidity check.

### Risk/Size
- [ ] **Maximum loss calculated.** Premium paid × number of contracts × 100 = Max loss in dollars.
- [ ] **Max loss ≤ 1.5% of account.** If not, reduce contracts.
- [ ] **Daily loss limit not already hit.** If already down 3–5% on the day, NO new trades.
- [ ] **Not adding to a losing position.** No averaging down on options.

### Exit Plan
- [ ] **Stop defined: 50% of premium paid** (or option price at which I exit unconditionally).
- [ ] **Underlying stop defined** (specific price level that invalidates the thesis).
- [ ] **Profit target defined** (50–100% of premium paid, or specific option price).
- [ ] **Time stop defined** (exit by 2:30 PM if not at profit target; do not hold into close).

### Pre-Trade Statement (complete this before every trade)
> "I am buying [N] contracts of [TICKER] [EXPIRY] [STRIKE] [CALL/PUT] at approximately $[PRICE]. My max loss is $[DOLLARS]. I will exit if the option drops to $[STOP_PRICE] (50% of premium) or if [UNDERLYING] moves to $[UNDERLYING_STOP]. My profit target is $[TARGET_PRICE] on the option. I expect to be out by [TIME] today."

---

---

## 10. Volume Spread Analysis (VSA) — Smart Money Rules
*Distilled from Holmes, "The Complete Volume Spread Analysis System" (Wyckoff/Tom Williams)*

### Core VSA Principle
- Every bar tells a story of Supply vs. Demand. Price + Spread (bar range) + Volume together reveal **smart money intent**.
- Lagging indicators (MACD, RSI, stochastics) give buy signals as price rises — exactly when smart money is SELLING into strength. VSA reads the actual supply/demand imbalance.
- Smart money (institutions, syndicates) **must act in the opposite direction of what they want**: to buy large quantities they must first create fear/selling (distribute noise); to sell large quantities they drive price up first (accumulation → mark-up → distribution).

### The Two Master VSA Rules
- **Rule 1 — Weakness appears on an Up Bar:** In a rising market, if a bar closes UP but has an ULTRA-HIGH VOLUME relative to recent bars AND a NARROW SPREAD (small bar range), smart money is selling into retail buying. This is distribution — bearish background.
- **Rule 2 — Strength appears on a Down Bar:** In a falling market, if a bar closes DOWN but has ULTRA-HIGH VOLUME AND NARROW SPREAD (small bar range), smart money is buying into retail panic. This is accumulation — bullish background.

### VSA Signal Types (actionable for our system)
- **No Demand Up Bar:** Up bar on LOW volume with narrow spread. Weak hands buying; no institutional backing. Do NOT enter long — signal will likely fail.
- **Selling Climax (SC):** Extremely wide spread DOWN bar on ULTRA-HIGH volume, closes near low. Marks end of panic selling. Potential long entry after confirmation.
- **Upthrust (UT):** Price spikes above resistance on high volume but closes BELOW the resistance level (wide spread up, closes low). Smart money distributed into the breakout. FALSE breakout — bearish signal. Avoid calls; consider puts.
- **Stopping Volume:** Very high volume DOWN bar that closes ABOVE mid-range (not at lows). Professionals absorbed selling. Bullish background beginning.
- **Test Bar:** Up bar on LOW volume after a prior high-volume decline. Tests whether supply remains. If it closes near high = demand is present = bullish entry confirmation.
- **Suckers Rally:** Price rises sharply on declining volume after a prior down trend. No institutional backing. Retail chasing. Do not enter calls.

### VSA Rules for This System
- **Volume spike on up bar (vol ratio > 2.0) + narrow bar (range < 0.3× ATR) = DISTRIBUTION WARNING.** Suppress bullish signal even if ORB fired.
- **Volume spike on down bar (vol ratio > 2.0) + narrow bar + price closes above mid-bar = ACCUMULATION.** Bullish background; calls supported.
- **ORB breakout on ultra-high volume that immediately stalls (next bar narrow) = UPTHRUST.** Exit longs immediately.
- **Always check if breakout volume is genuine:** Vol ratio > 1.5× is minimum for ORB. Vol ratio < 1.0× on a breakout = "No Demand" — reject the signal.
- Background matters: if the prior 5–10 bars show a pattern of high-volume down bars with narrow spreads (accumulation), bullish signals are higher quality. If prior bars show high-volume up bars with narrow spreads, bearish setup.

---

## 11. Price Action Rules — Al Brooks Framework
*Distilled from Brooks, "Trading Price Action Trends"*

### Core Price Action Principles
- **The 5-minute chart is the optimal timeframe** for intraday scalping. The 1-minute chart creates illusions of opportunity and leads to over-trading and cherry-picking bad entries.
- "If you cannot figure out what the chart is telling you, do not trade. Wait for clarity. It will always come."
- **Every bar is a trade.** Bulls tried to push up; bears tried to push down. The result (close location, bar size, volume) tells you who won each 5-minute battle.
- "Keep things simple and follow your simple rules. It is extremely difficult to consistently do something simple, but it is the best way to trade."

### Trend vs. Trading Range (Critical Distinction)
- **Trend day (strong):** Consecutive bars in one direction, EMA(s) consistently below (bull) or above (bear) price, pullbacks are shallow (< 3 bars) and immediately resume trend. In a strong trend, EVERY entry in the trend direction is valid.
- **Trading range day:** Bars overlap heavily, price oscillates around EMAs, EMA fans are flat. In a trading range, ALL breakout entries have ~50% chance of failing. Wait for a breakout candle that closes well beyond the range boundary.
- **Identifying trend vs. range:** If the last 10 bars have at least 6 trend bars (bars that close in their upper or lower third) in one direction = trend. If bars are mostly doji/overlap bars = range.

### Key Price Action Signal Bars
- **Bull signal bar:** Strong up bar (closes in upper 1/3), body takes up > 60% of bar range, small upper wick. Buy the break of the high of this bar.
- **Bear signal bar:** Strong down bar (closes in lower 1/3), body > 60% range, small lower wick. Sell break of the low.
- **Doji (inside bar) at resistance:** Indecision — price is testing resistance and failing to break cleanly. Do NOT enter; wait for resolution.
- **Reversal bar (climax bar):** Very large bar (> 2× ATR) after an extended trend. Often marks exhaustion. Do not chase — the move may be over.

### The Trader's Equation (Brooks) — added 2026-05-19
- **Only take a trade when:  P(win) × reward  >  P(loss) × risk.** This expectancy inequality is the single gate every setup must pass. A 53% edge with reward = risk barely clears it — and transaction costs subtract from *reward*, so a marginal raw edge becomes negative after costs.
- **Edges are always small and fleeting** — "the market is filled with smart traders who won't allow an edge to be big and persistent." Do not hunt for a bigger signal; assume the edge is thin and engineer around it.
- **The four levers for a thin edge (Brooks' single most important message, p.36):** (1) take *only* the best setups (selectivity), (2) avoid the worst setups, (3) reward ≥ risk, (4) increase **size**, *not* trade frequency.
- **Let winners run (p.85):** the best trades go 4×+ initial risk. Take a partial, move stop to breakeven, and let the remainder run. A *fixed* profit target caps exactly the fat-tail winners that carry the entire expectancy — prefer partial + breakeven + trail over a fixed target.

### Brooks Rules for ORB / Intraday Breakouts
- A breakout that closes BEYOND the level with a strong trend bar AND is followed by another trend bar in the same direction = high-probability continuation.
- A breakout on a weak bar (small body, large wicks) is likely to fail. At minimum, wait for the next bar to confirm.
- **Measured move targets:** After an ORB breakout, a reasonable target = ORB range added to breakout level (1× extension). For trending markets, 2× is achievable.
- **Two legs of a move:** Many profitable intraday moves have two legs. After the initial ORB breakout (leg 1) and a shallow pullback, a second leg of similar size follows. This is the optimal entry for options (after leg 1 pullback to VWAP or EMA).

### Brooks Rules for This System
- **Strong ORB breakout + follow-through bar = high quality.** Both bars must close in the top (bull) or bottom (bear) 25% of the bar range.
- **After a large climax bar (> 2× ATR), do not chase.** A reversal bar or doji following a climax bar is a WARNING — the trend may be exhausted.
- **Pullback to EMA on low volume, then resumption bar = ideal entry.** This is better than chasing the initial breakout.
- **In a trading range, fade breakouts:** If price breaks above a level on a weak bar and the prior 10 bars are in a range, the breakout is likely a trap (50/50 at best). Only enter on trend-day characteristics.

---

## 12. Volatility Trading — Sinclair & Hull Framework
*Distilled from Sinclair, "Option Trading: Pricing and Volatility Strategies" and Hull, "Options, Futures and Other Derivatives"*

### Statistical vs. Implied Volatility (Sinclair)
- **Realized/Statistical Vol (HV):** What the underlying actually did. Calculated from historical returns.
- **Implied Vol (IV):** What the options market implies future vol will be.
- **The edge in options trading:** Buy when IV < expected HV; sell when IV > expected HV. This is the ONLY sustainable edge in options — everything else is directional speculation.
- **IV tends to be systematically overpriced** vs. realized vol (the "variance risk premium"). This means net sellers of vol outperform net buyers over long periods — but only if they hedge gamma and manage risk properly.
- **Short-term mean reversion in IV:** When IV spikes sharply (e.g., VIX jumps 5 points in a day), it tends to mean-revert within 2–5 trading days. This is the basis for selling vol after spikes.

### Hull's Risk Management Framework
- **Delta-neutral hedging:** Professionals constantly re-hedge delta to isolate vega/gamma exposure. For retail directional traders: this means understanding that when you hold a long call, your delta exposure GROWS as the underlying moves in your favor (gamma effect). This is when to TAKE PROFITS, not add more.
- **Put-call parity:** C − P = S − Ke^(−rT). Any violation is an arbitrage. For practical trading: the put and call of the same strike/expiry must be priced consistently. If they're not (in paper trading or backtests), treat as data error.
- **Binomial vs. Black-Scholes:** Black-Scholes assumes constant volatility — a fiction. Real vol is stochastic (varies). This means OTM options are systematically underpriced by B-S (volatility smile). For buyers: OTM puts on SPY are more expensive than B-S implies because institutions buy them for tail-risk insurance.
- **Key insight for SPY options:** SPY has a persistent **negative skew** — OTM puts cost more than OTM calls at the same distance from ATM. This means: put buying is expensive (you pay the skew); call buying is relatively cheap (you receive the skew benefit).

### Volatility Forecasting Rules (Sinclair)
- Best simple forecast of near-term vol: blend of IV and recent HV. Neither alone is optimal.
- **GARCH effect:** Volatility clusters — high vol follows high vol, low vol follows low vol. If SPY has had 3 days of > 1% moves, expect more high-vol days. If it has had 10 days of < 0.3% moves, the vol regime is low and likely stays low.
- **Mean reversion speed:** SPY IV typically mean-reverts to its 30-day average within 10–15 trading days after a spike.
- **Practical rule:** After VIX spikes above 25, expect a 3–7 day elevated vol regime before normalization. After VIX below 12–13, expect the low-vol regime to persist 2–6 weeks on average.

### Rules for This System
- **Negative skew = always compare call vs. put pricing.** When VIX is below 15, OTM calls are relatively cheap vs. their probability of profit. Calls have a vol-pricing tailwind.
- **After a VIX spike > 5 points in 1 day:** IV is elevated. Do NOT buy naked options (you are buying at vol highs). Wait for IV to normalize (2–3 days) or use debit spreads.
- **Vol clustering rule:** If SPY has moved > 1% per day for 3+ consecutive days, options premium is rich; switch to debit spreads. If SPY has moved < 0.4% per day for 5+ consecutive days, options are cheap; naked long options are favored.

---

## 13. Conservative & Risk-First Rules
*Distilled from Thomsett, "Options Trading for the Conservative Investor"; Fontanills, "The Options Course" & "Trade Options Online"; McMillan, "Complete Guide to Option Strategies"*

### Thomsett's Conservative Rules
- **"Never trade options you don't understand."** Before entering any position, be able to explain: what the maximum loss is, what event would trigger the exit, and what the expected P&L is at expiration.
- **Sell covered calls on underlying equity as a primary strategy.** For directional plays, use vertical spreads instead of naked long options to cap downside.
- **The conservative test for an options trade:** Would you be willing to hold the underlying (stock/ETF) long-term if the option expired worthless? If no, the trade is speculation — size it accordingly (< 1% risk).
- **Avoid selling naked puts on downtrending stocks.** The premium received does not justify the assignment risk when the underlying has weak technicals.
- **Paper trading for 60 days minimum** before live trading any new strategy. (Relevant to new signal types we add to the system.)

### Fontanills' Trade Entry Discipline
- **"Plan your trade and trade your plan."** Options trading requires written plans because the P&L complexity (multiple greeks) makes in-the-moment decisions unreliable.
- **The 5-step approach:** (1) Identify market direction (bullish/bearish/neutral). (2) Choose IV regime (buy or sell premium). (3) Select strategy matching both. (4) Choose strike/expiry. (5) Define exit rules BEFORE entering.
- **Rolling options:** If the trade is working but time is running out, consider rolling to the next expiry rather than holding to expiration. This resets theta while capturing the existing P&L.
- **Scaling out:** Take 50% of the position off at the first profit target (+50% of premium). Let the remaining 50% run to the second target (+100%). This locks in gains while maintaining exposure.
- **Adjusting losing trades:** If an option has lost 30% of premium but thesis is intact, consider a "repair spread" — sell an OTM call (for calls) against the losing long call to reduce the break-even. Only do this if you have high conviction the underlying will recover.

### McMillan's Strategy Selection Framework
- **Market direction first, volatility second.** Never select a strategy based on premium levels alone — the underlying direction determines whether you are long or short options.
- **Use the simplest strategy that accomplishes the goal.** A long call beats a complex spread if IV is low. A debit spread beats a naked call if IV is high. Don't over-engineer.
- **For index options (SPY, SPX):** European exercise removes early assignment risk. Assignment can only happen at expiration. This simplifies management significantly.
- **SPX vs. SPY:** SPX options are cash-settled, European-style, 10× the size. SPY options are American-style, share-settled. For this system (SPY), be aware that SPY options CAN be exercised early — monitor if deep ITM and near ex-dividend date.
- **Synthetic positions:** A long call + short put (same strike/expiry) = synthetic long stock. For complex positions, decompose into synthetics to verify net greek exposure.

### Rules for This System
- **Scale out rule (Fontanills):** When a position hits +50% premium gain, close HALF the position. Let the other half run with a stop at breakeven. This is mandatory discipline, not optional.
- **No new entries after 3 consecutive losses in one day.** Three losses = system or market misread. Take the rest of the day to diagnose, not to recover.
- **Repair rule:** If position is −30% but underlying is consolidating and time remains, evaluate rolling. If position is −50% or more, exit with no exceptions (per Natenberg stop rule).

---

## 14. Futures & ETF-Specific Rules
*Distilled from Schwager, "Complete Guide to the Futures Market"; McMillan ETF sections*

### SPY ETF Options Specifics
- **SPY tracks S&P 500 at 1/10th the index price** (approximately). SPX = S&P 500 index; SPY ≈ SPX / 10.
- **SPY pays dividends quarterly** (March, June, September, December). Near ex-dividend dates, deep ITM calls may be exercised early to capture dividend. System should avoid holding deep ITM calls (delta > 0.85) within 3 days of ex-dividend.
- **SPY options are highly liquid** — among the most liquid options in the world. Bid-ask spreads on ATM options are typically $0.01–0.03. This system should always trade at or better than the mid.
- **SPY gamma is high on 0DTE and weekly options.** A $1 move in SPY on a 0DTE ATM option can move the option price by $0.40–0.70. This system uses 7–14 DTE but should be aware that as DTE shrinks, gamma accelerates.
- **SPY vs. SPX choice:** For positions < $50,000 capital, SPY options are more size-flexible. SPX is 10× larger per contract — minimum risk is ~$500–1000+ per trade, too large for small accounts.

### Schwager's Technical Analysis Rules for Trend Identification
- **Volume confirms trend:** In a genuine uptrend, advancing days have higher volume than declining days. If SPY rallies on light volume (vol ratio < 0.8) and declines on heavy volume, the trend is suspect.
- **Open interest as sentiment indicator (futures concept applied to options):** Rising open interest on call options while price rises = new money entering = genuine demand. Falling open interest while price rises = short covering, not new buying = weaker signal.
- **Support/Resistance with volume:** A prior resistance level that was broken with high volume becomes stronger support on retest. A level broken on low volume (no-demand breakout) is a weak support.
- **The 3% filter:** For weekly/daily charts, Schwager recommends a breakout beyond a prior high/low by > 3% before confirming a new trend. For 5-minute intraday: apply a 0.15–0.20% filter (SPY $0.80–$1.00) above the ORB level before entering to avoid false breakouts.
- **Avoid trading against the weekly trend.** If SPY's weekly chart shows a downtrend (lower highs + lower lows), call options have a structural headwind. Only trade puts or use aggressive stops on calls.

### Rules for This System
- **Weekly trend alignment rule:** Before entering a call, check: is SPY making higher highs and higher lows on the 60-minute or daily chart? If no = use puts or reduce call position size 50%.
- **Ex-dividend alert:** Do not hold deep ITM calls (delta > 0.85) within 3 calendar days of SPY's ex-dividend date (check quarterly calendar).
- **Volume trend confirmation:** If vol ratio on the entry bar is < 0.8 (below-average volume), reduce position size by 50% regardless of other signals.

---

## 15. Professional Trader Habits (Pro vs Retail)

*Distilled from Levy, "Your Options Handbook" (2011) — "Top 10 Things Professionals Do That The Average Retail Trader Doesn't" + cross-referenced with Lowell, Saliba, Fontanills*

### The 10 Habits

| # | Habit | Why it matters for this system |
|---|-------|--------------------------------|
| 10 | **Hedge / diversify with beta, not just sectors** | SPY + AMZN/GOOG/MSFT/NVDA/META all have β > 1.1 to SPY. Six high-beta tech names are functionally one bet. Already a P1 TODO (#7 correlation cap). |
| 9 | **Plan max downside dollar BEFORE the trade** | Already enforced: stop_loss% + risk_per_trade%. Debate prompt should explicitly cite both numbers. |
| 8 | **Be a contrarian — buy the rumour, sell the news** | Earnings filter already vetoes pre-earnings entries. Post-earnings IV crush is the perfect "sell-on-news" context for credit spreads (we're long-only — known gap). |
| 7 | **Sell/protect while the trend is still strong** | T1 partial close at +50% premium gain executes this rule. After T1, trailing stop is the protection-while-strong mechanism. |
| 6 | **Learn from losses, not just profits** | EOD review covers winners + losers. The "stalled trade" time-stop (60 min in -15% to +10% range) is direct loss-discipline enforcement. |
| 5 | **Be consistent in the types of issues you trade** | Watchlist is locked to 6 mega-caps + SPY. No random tickers, no penny stocks, no earnings plays. |
| 4 | **Think three steps ahead — plan flat AND adverse scenarios, not just best case** | Trade approval modal must show: max_loss, stop, T1, T2. All four are pre-computed and emitted. |
| 3 | **Trust yourself / your plan** | Auto-trade ON = trust the rules. Manual override available but should be rare. |
| 2 | **Be adaptable, yet adept** | Knowledge base updates (this doc!) refine the plan. Don't trade strategies you don't understand. |
| 1 | **Ask questions** | The bull/bear debate IS the "asking questions" gate — three Haiku calls explicitly poking holes in every signal. |

### Levy's "Mechanic's Checklist" Philosophy
- **Treat each trade like a pre-flight checklist.** Pilots, mechanics, surgeons all use checklists. Discretionary "feel" is the enemy.
- **Each data point gets a pass/fail rating** with explicit tolerance. If any item fails → skip the trade, don't force it.
- **"There will always be trades out there; don't force anything when it comes to your money."**
- **Our checklist** (the 18 risk-control gates in [ARCHITECTURE.md §5](ARCHITECTURE.md)): news → earnings → IVR → VIX → lunch → chop → sector cap → PDT → daily loss → daily profit → portfolio risk → per-trade sizing → cooldown → whipsaw → daily entry cap → time of day → spread → debate. Every signal must pass ALL.

### The Three Mantras
1. **"Hope" is not a strategy.** Lowell (*Get Rich With Options*): "Are you in an investment based on hope?" If a trade requires hope, the math is wrong — re-check IVR, delta, theta budget.
2. **"Insurance is cheaper before the accident."** Buy puts when complacent, not panicking. For long-call holders: trail stop while strong, don't wait for the reversal.
3. **"It's the little things that make the biggest difference."** A 5 bps slippage tax × 200 trades/year = 1% annual drag. Track slippage. Tighter limit fills > marketable orders.

---

## 16. Put-Specific Strategy Rules

*Distilled from Thomsett, "Put Option Strategies for Smarter Trading" (2010)*

### When to Prefer Puts Over Calls
- **Bearish weekly trend on underlying.** If 50-DMA crossing below 200-DMA + price below both, put bias is structural, not contrarian.
- **VIX rising from < 15 toward 20+.** Volatility expansion days favor puts (markets fall faster than they rise).
- **IV term structure in backwardation** (front-month IV > back-month IV) → put protection demand spiking = bearish institutional positioning.
- **Negative gamma in dealer positioning** (rare retail data, but VIX > 25 + steepening skew is a proxy).

### Put Entry Rules
- **Don't buy puts after a 2%+ down day.** IV is already inflated; you're paying for fear that's already priced in. Wait for a relief bounce, then buy puts on rejection.
- **Best put setups:** lower highs forming + below VWAP + EMA9 < EMA21 + RSI 40–55 (NOT < 30 — oversold = bounce coming).
- **Put delta target same as calls:** 0.40–0.60. Deep OTM puts (delta < 0.25) are lottery tickets; deep ITM puts are stock-replacement positions.

### Put Risk Asymmetry vs Calls
- **Puts have a hard floor:** stock can only go to $0. Max profit on a put is bounded; max profit on a call is theoretically unbounded.
- **Practical implication:** put profit targets should be more aggressive (close at +75–100%, don't wait for moonshots).
- **Put theta is slightly worse than call theta** at the same strike due to put-call parity + interest rate effect. Subtract ~5% from call theta to estimate put theta on equivalent strikes.

---

## 17. Discipline & Systematic Trading (Smith, Dummies, Cofnas)

*Distilled from a second-pass review of all 27 PDFs in `/Users/bsannadi/Desktop/books/Trading/Options Trading` — focused on chapters with highest rule/checklist density that weren't already captured.*

### 17a. Self-Discipline as the Differentiator (Smith, *Option Strategies*, ch. 24)

> "I can teach the intellectual knowledge necessary to trade options, but it is much more difficult to teach self-discipline." — Courtney Smith

Smith's hiring filter for traders: looks for **Marines, military veterans, athletes, or STEM degrees** — proxies for discipline. The intellectual content is teachable; the discipline isn't.

**Why it matters for an AI-assisted system:** the LLM debate gate substitutes some of the discipline burden. The system *enforces* discipline by:
- Refusing entries that fail any of the 18 risk gates (mechanical, not discretionary)
- Auto-trade ON eliminates the "I'll just take this one" override
- Logged decision trail enables post-trade audit (what Smith calls the "bizarre twists of the mind" — minds that find creative ways to lose money)

**Rule for this system:** every manual override (skip in modal, manual close, DRY_RUN flip mid-session) must be logged with a *reason field* so the EOD review can catch discipline drift.

### 17b. What Makes a Good Trading System (*Trading Options For Dummies*, ch. 7)

A system is fit to trade real money only if it has ALL of these properties:

| # | Property | How we measure |
|---|----------|----------------|
| 1 | Average win > average loss | EOD review `expectancy` field |
| 2 | Low standard deviation (system profit close to median) | Need to add: rolling 20-day Sharpe |
| 3 | Manageable drawdowns | `WEEKLY_LOSS_HALT_PCT = 4%` + intraday max-DD tracking |
| 4 | **Does NOT rely on a handful of trades** for profitability | New TODO: log "top-3 trade contribution %" — if > 50%, system has fat-tail risk masking lack of edge |
| 5 | Wins on *more than one* market regime | New TODO: split EOD review by VIX regime (low/normal/high) |

**Dummies' 9-step backtest framework** (already partly implemented in `scripts/backtest.py`):
1. Identify strategy basis
2. Identify entry/exit rules
3. Identify market + period
4. Identify account assumptions (system + trade allocations)
5. Test, evaluate
6. Identify reasonable filters to minimize losers
7. Add filter, retest
8. **Add risk-management component** ← this is where 95% of retail backtests skip
9. Final test

**Rule:** never trust a backtest result that hasn't been through step 8.

### 17c. Cofnas's 11 Practice-Trade Categories (*Trading Binary Options*, ch. 11)

Cofnas defines a self-assessment grid: every trader should run 10 trades in each of 11 distinct setup types to **find which they're actually good at**. We can map these to our system's signal types:

| Cofnas Type | What it tests | Our system equivalent |
|-------------|---------------|----------------------|
| 10 ATM trades | Entry-timing skill on momentum | VWAP-momentum signals |
| 10 ITM trades | Joining confirmed trends | Trend-continuation signals |
| 10 OTM trades | Contrarian breakouts | ORB breakout (low-prob, high-payoff) |
| 10 DOOM (deep OTM) trades | Mathematics of low-prob/high-payoff | We avoid these (Delta < 0.30 = reject) |
| 10 DITM trades | High-probability spotting | We avoid these (Delta > 0.70 = reject — overpaying) |
| 10 Gut trades | "Blink" intuition for paralysis-by-analysis | **System refuses** — no rule-less entries |
| 10 Headline trades | News-sentiment skill | News filter (pre-veto, not entry signal) |
| 10 Contrarian trades | When is the crowd wrong? | Mean-reversion signals at extremes |
| 10 Bounce trades | Range/channel trading | Bollinger-band touch + RSI-extreme entries |
| 10 Breakout trades | Range-break trading | ORB breakout |
| 10 Data-release trades | FOMC/CPI/NFP | **Should be vetoed** (TODO #5 macro blackout) |

**Edge implication:** the system covers 5–6 of Cofnas's 11 categories cleanly. If EOD attribution shows we lose money on, say, "10 Contrarian trades" cluster, we should temporarily disable mean-reversion signals while we tune.

**Rule for this system:** persist signal-type per trade (`signal_class: orb_breakout | vwap_momentum | trend_cont | mean_rev | range_bounce`) and split EOD P&L by class. Currently aggregated.

### 17d. Order-Type Discipline (Fontanills, *Trade Options Online*, App A)

The 17 order types Fontanills enumerates collapse into 3 categories for our system:

1. **Limit** — primary execution. Cap price at mid → walk to ask × 1.002 if unfilled.
2. **Stop-limit** — for protective stops (avoid market-order slippage on illiquid options at the stop trigger).
3. **Market-on-close** (15:50 ET) — hard-close branch uses this for the final flatten.

**Rule:** never use plain `Market` orders on options. Spreads can be 5%+ on stocks during fast moves; on options, bid/ask collapse and you can pay 20%+ over fair value. Always limit, even on emergency closes.

---

## 18. Candidate / Experimental Indicators — NOT YET VALIDATED

> ⚠️ **Reference only. None of these are wired into the live signal stack.**
> They are captured here so the definitions exist and the debate gate can
> *reason about* them, but per the project's standing discipline (KB §17b:
> "robust systems work in a neighborhood of params; fragile ones cliff-edge")
> a new factor is added to live trading **only after the backtest (TODO
> item 1) proves it adds out-of-sample expectancy** — never hand-wired on
> an unproven base. Tracked as TODO §🆕-P1-J.

### 18a. Force Index (Elder)

- **Definition:** `FI_raw = volume × (close − prev_close)`. Smoothed:
  `FI(N) = EMA_N(FI_raw)`. Common: FI(2) short-term entry timing, FI(13)
  trend confirmation, FI(18) (seen on the reference TSLA chart) a slightly
  slower trend filter.
- **Reads:** FI > 0 = buyers in control (price up *and* volume backing it);
  FI < 0 = sellers. The magnitude scales with conviction (volume × move).
- **Signals:**
  - FI crossing zero with price = momentum regime shift.
  - **Bullish divergence:** price makes a lower low, FI makes a higher low
    → selling exhausting → reversal-up watch.
  - **Bearish divergence:** price higher high, FI lower high → rally on
    fading volume (Suckers Rally, ties to §10 VSA) → exit/avoid calls.
- **Why it fits this system:** it is literally "volume confirms the move"
  quantified — the same principle as the ORB `vol_ratio > 1.3` gate
  (§6), Schwager's volume-confirms-trend (§14), and VSA (§10). Strong
  candidate as a **confluence factor** (entry) and a **fade-exit trigger**
  (FI rolling through zero against an open long).

### 18b. Supertrend (ATR-banded trend flip)

- **Definition:** `mid = (high+low)/2`; `upper = mid + m×ATR`,
  `lower = mid − m×ATR` (typical `m`=3, ATR period 7–10). Final bands use
  trailing logic; the indicator "flips": **long while close > Supertrend
  line, short while close < it.** The flip bar is the signal.
- **Reads:** a clean, volatility-adaptive trend direction + a built-in
  trailing stop (the line itself).
- **Strengths:** excellent in trends, the trailing band is a natural,
  ATR-scaled exit (overlaps the post-T1 trailing stop already shipped).
- **Weakness:** **whipsaws badly in chop** — must be paired with a
  range/chop filter (we already have `is_chop_regime()` and the
  Bollinger-width compression check, §6/§11 Brooks "in a trading range,
  fade breakouts"). Never run Supertrend naked in a range.
- **Why it fits:** the codebase + KB already lean heavily on ATR (Brooks
  §11, `MIN_ORB_ATR_MULT`, the trailing stop). Supertrend is a coherent
  ATR-trend candidate for **entry confluence** and an **exit-variant**
  (use the Supertrend line as the dynamic stop in §P1-G's sweep).

### 18c. Momentum-Fade Soft Exit

- **Definition:** exit (or scale down) an open long *before* the hard
  premium/ATR stop when the entry thesis quietly breaks: e.g.
  `RSI < 50` **or** `close < EMA9` (mirror for shorts/puts).
- **Origin:** observed in a separate stock-momentum bot
  (`alpaca_momentum_v20.py`) and independently visible on the reference
  TSLA chart (Force 18 rolled to zero + price snapped below EMA9 the same
  day price fell −4.75%).
- **Concept:** a "thesis-broken" exit distinct from the disaster stop.
  Long-option math (theta) punishes round-trips to the hard stop; getting
  out when momentum *first* fades preserves premium. Aligns with KB §3
  ("take 50% of the move, don't hold for the full move; exit if not
  profitable by 2:30") and §16 Thomsett (harvest faster on puts).
- **Status:** candidate **exit variant** for §P1-G's backtest sweep,
  alongside ATR-stop / signal-class targets.

### 18d. SMA vs EMA note

The reference chart used **SMA 20 / SMA 100**; this system uses **EMA21 /
daily-EMA200**. EMA weights recent bars more (faster, more whipsaw); SMA
is smoother/laggier. Not a gap — a deliberate parameterization choice.
If the backtest sweep tests MA type, SMA variants can be included, but
there is no a-priori reason to switch; EMA is the documented choice and
both are valid (KB §6 EMA Signal Alignment).

---

## Appendix: Quick Rules Summary

| Rule | Threshold | Action |
|------|-----------|--------|
| IVR | < 30% | Buy naked options |
| IVR | 30–50% | Use debit spread |
| IVR | > 50% | No naked long premium |
| DTE | < 7 days | Reject (unless 0DTE system) |
| DTE | 7–14 days | Target zone |
| Delta | < 0.30 | Too OTM, reject |
| Delta | 0.35–0.65 | Target zone |
| Delta | > 0.70 | Overpaying, reconsider |
| Premium stop | 50% loss | Exit unconditionally |
| Daily loss | > 3–5% account | Stop trading for day |
| Risk per trade | > 1.5% account | Reduce size |
| Bid-ask spread | > 5% of mid | Do not trade (illiquid) |
| VIX | > 30 | Reduce all sizes 50% |
| Time of day | 9:30–10:00 AM | Observe only, no entry |
| Time of day | 12:00–2:00 PM | Avoid new entries |
| Time of day | After 3:30 PM | Close existing, no new |
| Catalyst within | 24 hours | No naked options |
| Open interest | < 500 | Reject (illiquid) |
| Max simultaneous | > 3 correlated | Too much exposure |
| Vol ratio on entry | < 0.8 | Reduce size 50% (no institutional backing) |
| Vol spike on up bar | ratio > 2.0 + narrow range | VSA distribution warning — suppress bull signal |
| Vol spike on down bar | ratio > 2.0 + closes above mid | VSA accumulation — bull background |
| ORB breakout bar | closes in lower 50% of bar | Weak breakout (Brooks) — wait for confirmation |
| After VIX spike | > 5 pts in 1 day | Use spreads only for next 2–3 days |
| Weekly trend | Lower highs + lower lows | Suppress calls or reduce size 50% |
| DTE and dividend | Delta > 0.85 within 3 days of ex-div | Do not hold long calls |
| Scale out | +50% premium gain | Close half position unconditionally |
| Consecutive losses | 3 in one day | No new entries rest of day |
| Pro habit (Levy #9) | Plan max-loss $ before entry | Every signal must show stop + max-loss in approval |
| Pro habit (Levy #7) | Sell/protect while strong | After T1, trail stop; don't wait for reversal |
| Pro habit (Levy #4) | Plan 3 scenarios | Best-case, flat, adverse — all pre-computed (T2, time-stop, stop) |
| Pro habit (Lowell) | "Hope" is not a strategy | If trade requires hope (deep OTM, IVR > 50%), reject |
| Thomsett put rule | Don't buy puts after 2%+ down day | IV already inflated; wait for relief bounce |
| Thomsett put rule | Put RSI sweet spot | 40–55, NOT < 30 (oversold = bounce risk) |
| Thomsett put rule | Put profit target | +75–100% (more aggressive than calls — bounded upside) |
| Smith discipline | Mind plays tricks | Manual overrides must be logged with reason — catch discipline drift |
| Dummies system rule | Top-3 trade share | If > 50% of P&L from 3 trades → no edge, fat-tail luck |
| Cofnas no-go | Pure "gut" entries | System refuses — every entry must trace to rules |
| Cofnas no-go | Data-release trades (NFP/CPI/FOMC) | Vetoed (overlaps with macro blackout TODO #5) |
| Fontanills order rule | Never use Market orders on options | Always Limit (5–20% slippage risk on Market) |
| Davey too-good rule | Backtest looks astonishing | Treat as a BUG/curve-fit signal, not a discovery — investigate before believing |
| Davey validation ladder | Result tier | historical < out-of-sample < walk-forward < real-time(paper) — credibility rises down the ladder |
| Davey optimization rule | Optimized on full data set | Invalid by construction — always hold out / walk-forward |

---

## 12. Backtest & Validation Discipline (Davey, *Building Winning Algorithmic Trading Systems*) — added 2026-05-19

- **"If it is too good to be true, it probably is."** Future performance is *almost never* as good as historical; the *better* a system tests historically, the *less* likely it repeats. An astonishing backtest is a **red flag to investigate**, not a green light. (Mirrors our S3: PF 1.38 @1 bp collapsed to 0.97 @3 bp — the optimistic assumption *was* the "too good" tell.)
- **The validation ladder (credibility rises at each rung):** historical backtest → out-of-sample → walk-forward → **real-time / paper (incubation)** → live. Never skip a rung; each kills survivors the prior one missed.
- **Never optimize on the whole data set.** Optimizing and testing on the same data is invalid by construction. Hold out; walk-forward; gently optimize (few degrees of freedom).
- **Cost/assumption sensitivity is mandatory, not optional.** A real edge survives pessimistic cost assumptions; an edge that only exists at optimistic costs is an artifact (this is *why* the ≥3 bp gate exists).
- **Monte Carlo + incubation before capital.** Stress trade-order/equity-path randomness; then *incubate* (paper) the finalized, frozen system before any real money — paper trading is the "real-time" rung of the ladder, not a formality.
- **Make discretionary rules statistically testable or discard them.** "Intuition" cannot be validated; only mechanical rules can. If it can't be backtested cost-aware and walk-forward, it doesn't go live.
