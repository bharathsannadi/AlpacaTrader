# Options Trading Knowledge Base

> Distilled from 10 professional options trading books:
> - Natenberg, *Option Volatility and Pricing* (2nd ed.)
> - Passarelli, *Trading Option Greeks*
> - Saliba, *Option Spread Strategies*
> - Smith, *Option Strategies* (Wiley, 3rd ed.)
> - Lowell, *Get Rich With Options*
> - Benklifa, *Think Like an Option Trader*
> - Thomsett, *Put Option Strategies for Smarter Trading*
> - Optionetics, *Trading Options For Dummies*
> - Toghraie, *Options Trading for the Conservative Investor*
> - McMillan, *The Complete Guide to Option Strategies*
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
