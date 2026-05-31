# Trading, Day Trading & Options Knowledge Base

> **Last updated: 2026-05-25** — Added §T17-T27 and §DT14-DT17: Candlesticks, Weis/Wyckoff, Minervini SEPA, 25 Rules, Sinclair vol edge, Cooper intraday, Wyckoff intraday, Bulkowski/Bandy risk; Velez Pristine 4-Stage, 18 Champions cross-trader rules, Person Pivot P3T, Rhoads VIX derivatives, Heitkoetter/McDowell day trading, Murphy intermarket, McMillan covered calls & collars. 300 PDFs catalogued, ~50 books deeply read.
>
> Distilled from 300+ professional trading books in `/Users/bsannadi/Desktop/bharath/books/Trading/`:
> **Foundations:** Natenberg (*Option Volatility and Pricing*), Passarelli (*Trading Option Greeks*), Saliba (*Option Spread Strategies*, *Option Strategies for Stock/Index/Commodity*), Hull (*Options, Futures and Other Derivatives*)
> **Pricing & Quant:** Sinclair (*Volatility Trading* 2013), Haug (*Complete Guide to Option Pricing Formulas*), Statistics of Financial Markets (2013), Option Pricing Models (2007)
> **Strategies & Spreads:** Lowell (*Get Rich With Options*), Smith (*The Complete Guide to Option Strategies*), Saliba (*Option Spread Strategies*), Levy (*Your Options Handbook*)
> **Price Action & Volume:** Holmes (*Complete Volume Spread Analysis System* — VSA/Wyckoff), Brooks (*Trading Price Action Trends*), Weis (*Trades About to Happen* 2013 — Wyckoff)
> **Candlesticks:** INO.com (*17 Money Making Candle Formations*), Nison framework
> **Momentum/Breakout:** Minervini (*Trade Like a Stock Market Wizard* 2013 — SEPA/VCP/Stage 2), Bulkowski (*Successful Stock Signals* 2013)
> **Intraday:** Cooper (*Intra-Day Trading Strategies* 2003 — Thrust/Pause/NR7/Gap'nGo), Aziz (*How to Day Trade for a Living*), Velez (*Swing Trading Tactics*)
> **Put-Specific:** Thomsett (*Put Option Strategies for Smarter Trading*, *Options Trading for the Conservative Investor*)
> **Risk & Discipline:** Fontanills (*The Options Course*, *Trade Options Online*), Benklifa (*Think Like an Option Trader*), Zalesky (*25 Rules of Day Trading*), Bandy (*Money Management Risk Control*)
> **Specialty:** Cofnas (*Trading Binary Options* — sentiment/NFP), Elder (*Step by Step Trading*, *New Trading for a Living*), Douglas (*Trading in the Zone*), Connors (*Short Selling with ConnorsRSI*)
> **Quick reference:** OIC (*Option Strategies Quick Guide*), Danes (*Options Trading QuickStart*, *Options Trading Strategies*), Optionetics, Trading Options For Dummies
>
> **Purpose:** AI trading system reference for debate gate, signal evaluation, trade approval, and the live screener.
> **System trades:** Day trading stocks (25 S&P 500 universe) + directional options on validated setups. 4 backtested setups: Breakout PF 1.88, Bull Flag PF 1.44, RSI Dip PF 1.41, Gap+Vol PF 1.37.
> **Sections:** §1–25 = Options KB · §T1–T21 = Trading KB · §DT1–DT16 = Day Trading KB · §BT1 = Backtest results

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

### "A Good Spread" — Margin for Error Over Max Profit (Natenberg, p.248–260) — added 2026-05-31
- **Theoretical edge is meaningless without risk context.** Any spread's edge can be scaled to any size by trading more contracts — so "this spread has more edge" is never a reason to take it (Natenberg p.248). Always normalize edge against the loss if the view is wrong.
- > **"A good spread is not necessarily the one that shows the greatest profit when things go well; it [is the one that] allows... a reasonable margin for error [so that] even his losses will not lead to financial ruin."** — Natenberg, p.260
- **Corollary (the over-optimization trap):** "a spread that passed every risk test would probably have so little theoretical edge that it would not be worth doing." The goal is not zero risk — it is *survivable* risk. Size for the bad case, not the good case.
- **For our $5K account (cost-fragility context):** this is the antidote to the curve-fit/over-size trap. Do NOT size a debit spread to maximize best-case edge; size it so a full loss is within the per-trade budget ($200) AND a correlated bad day stays within the daily limit. A spread that only "works" at max size is a ruin risk, not an edge.

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

### Covel (*Trend Following*) — added 2026-05-19
- **Win rate is the WRONG success metric for a directional/trend edge.** The healthy, *normal* shape is **many small losses + a few outsized winners**. A 40–55% win rate is a *feature*, not a defect — do not "fix" a strategy because its win rate looks low; judge it by expectancy and payoff asymmetry.
- **The edge lives in the fat tail.** A *fixed* profit target clips exactly the outlier winners that pay for all the small losses. Trend money arrives "in sudden bursts" — clipping the burst destroys the edge. (LTCM blew up assuming no fat tails; the tail is not noise, it *is* the profit.) → strongest possible argument for runner/trailing exits over fixed targets.
- **Prediction is futile — react to the realized trend, don't forecast it.** Reinforces regime-gating (Gunn): follow the trend that exists, don't predict the next one.
- **Risk asymmetry cuts both ways:** risk no more than you can afford, *and also risk **enough** that a win is meaningful* — chronic under-betting a real edge is also a failure mode (complements Kelly §4: ≤½-Kelly, but not so small the edge can't compound).
- **Volatility is the source of profit, not the enemy** — converges with the empirical finding that a thin directional edge survives on high-volatility names and dies on low-volatility ones (cost vs movement).

### Connors & Raschke (*Street Smarts*) — added 2026-05-19
- **The recipe (independent third-lineage confirmation):** a single-variable setup with a statistically significant edge becomes a real system only when you "**apply a longer-term trend indicator, a volatility filter, and a money-management algorithm**" (p.51). This is *exactly* the regime-gate + vol-filter + Kelly stack converged on from Natenberg/Sinclair/Gunn/Brooks — arrived at from a different author lineage.
- **Mean-reversion / pullback-in-trend is a distinct, ORTHOGONAL edge family** to momentum/breakout: enter *in the direction of the longer-term trend after a counter-trend pullback* ("Anti", retracement patterns); or fade short-term RSI extremes (e.g., 3-period RSI of 1-period ROC < 30 = oversold, enter on the next breakout). Low-correlation to a continuation/breakout signal → a true diversifier for a portfolio-of-strategies.
- **Multiple setups that "test out independently" should be combined.** Independent thin edges stacked = robustness; this is the empirical basis for a portfolio-of-strategies rather than one hero signal.
- **Caution on full mechanization:** a *fully* mechanical, widely-known short-term edge invites large funds to arbitrage it away (p.6). Thin retail-scale edges survive partly *because* they are small/uncrowded — a reason to expect modest, not spectacular, expectancy (echoes Brooks "edges are small and fleeting").

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

## 19. Daily Mean-Reversion (Connors RSI-2) — Path A Rules
*Validated 2026-05-20. Backtest: Test PF 1.32@3bp / 1.29@5bp OOS walk-forward. Paper incubation started 2026-05-20.*

> These rules govern the **only cost-robust validated strategy** in this project as of 2026-05-20.
> They are pre-specified and frozen — do not modify mid-incubation.

### Strategy Rules (pre-specified, non-negotiable)

| Parameter | Value | Rationale |
|---|---|---|
| Trend filter | Close > SMA(200) | Long only in bull regime (§8 Gunn: un-conditioned = no edge) |
| Entry trigger | RSI(2) < 10 | Extreme short-term oversold in uptrend = mean-reversion setup |
| Exit trigger | RSI(2) > 70 at prior close | Oversold condition resolved — exit next open |
| Stop loss | 2 × ATR(14) below entry | Volatility-scaled hard stop (§8 Connors/Raschke: volatility filter) |
| Time cap | 10 trading days | Trade does not resolve → exit regardless |
| Risk per trade | $200 | Fixed dollar risk, sized via shares = RISK_BUDGET / (2 × ATR14) |
| Max concurrent | 5 positions | 20% portfolio risk / 4% per trade (§4: maximum exposure) |
| Direction | Long only | Bear-side tested and failed (PF 1.05 @3bp) — long-only is the keeper |
| Universe | 39 large-cap stocks | Pre-specified; no cherry-picking mid-incubation |
| Data | yfinance daily EOD bars | Free, sufficient for daily strategy; no intraday data needed |
| Execution | Alpaca market order at next open | Enter/exit at open after EOD signal fires |

### What This Strategy Is NOT

- It is **not a trend-following strategy** — it fades short-term pullbacks within a longer uptrend
- It is **not an options strategy** — shares only; options costs destroy this edge (§5 Sinclair transaction-cost hierarchy)
- It is **not a prediction** — it reacts to a mechanical RSI condition, no forecast required (§8 Covel)
- It is **not discretionary** — the LLM debate gate does NOT apply; RSI<10 above SMA200 = enter, full stop

### Rules Inherited from KB (applicable sections only)

1. **Regime gate is mandatory** (§8 Gunn): SMA200 IS the regime filter. Never remove it. A raw RSI(2)<10 signal without the SMA200 filter fires in bear markets where mean-reversion fails.
2. **Expectancy over win rate** (§8 Covel): 66% win rate is a feature; the edge lives in the payoff ratio. Do not "fix" the strategy because some symbols have 50-55% win rates — judge by PF, not win%.
3. **Cost-robust gate is non-negotiable** (§12 Davey): PF must hold at BOTH 3bp AND 5bp slippage OOS. This strategy cleared it. If re-run on new data and it fails, strategy goes back to paper-only regardless of live P&L.
4. **Validation ladder** (§12 Davey): we are at rung 3 (paper incubation). Do not skip to real money. 4-week minimum before GO_LIVE_CHECKLIST §4 box can be checked.
5. **Fixed risk per trade** (§4 KB + §8 Sinclair Kelly): $200/trade = 4% of $5K account. Do NOT size up on "high conviction" symbols — every signal gets the same size (§7 rule 9: "same size rule for every trade").
6. **Pre-defined stop before entry** (§4 + §7): ATR stop is computed at signal time and placed as a native Alpaca stop order immediately. No discretion on stop placement.
7. **Do not over-optimize** (§12 Davey): the RSI thresholds (10 entry / 70 exit), SMA window (200), ATR multiplier (2.0) are FROZEN from the pre-specified backtest. Do not tune them on new data — that is curve-fitting.
8. **Paper trading minimum before live** (§13 Thomsett): 4 weeks / ~15-20 paper trades minimum. Check mechanics, not P&L.

### Paper Incubation Checklist (4-week clock, started 2026-05-20)

What to verify — mechanics only, P&L verdict comes later:

- [ ] EOD scheduler fires at 4:10 PM ET on every trading day (no misses)
- [ ] Morning confirm fires at 9:35 AM ET (fills confirmed, stops updated)
- [ ] Fill prices within reasonable range of prior close (slippage check)
- [ ] Native stop orders activate and fill on adverse moves
- [ ] Position file stays accurate across restarts / crashes
- [ ] launchd auto-restarts app on crash with no data loss
- [ ] No Python exceptions or scheduler hangs over 4 weeks

### Known Limitations (documented, not excuses)

- **38.5% max drawdown** on $5K account (OOS, 5-concurrent cap): concentrated in Feb 2025 multi-name selloff. Acceptable per user's stated $1K/day (20%) loss tolerance. Would be ~4% on a $50K account.
- **16/39 symbols lose in OOS test**: universe filter (ATR%/liquidity rule) is a pending TODO — must be pre-specified and OOS-tested before applying, not cherry-picked.
- **2022 bear year PF 0.85**: strategy is regime-dependent. SMA200 filter reduces exposure in bear markets but does not eliminate it entirely. This is expected and acceptable.
- **Long-only**: no short/bear side. Acceptable given long-only passed and bear-side failed the cost-robust gate.

### Candidate Mitigation for the Bear-Year / Regime Weakness (book-dig 2026-05-31) — NOT YET VALIDATED

> Source: Connors, *Short Selling Stocks with ConnorsRSI* (2013), p.26. Backtest finding (long ConnorsRSI variations): tightening the entry threshold (e.g. CRSI 95 vs 75) produced **roughly half the signals but nearly 2× the average P/L per trade.** Selectivity raises per-trade expectancy.

- **Hypothesis (H-SEL-REGIME):** the 2022 PF<1 weakness is a *selectivity* problem, not a signal-failure problem. In weak/bear regimes the RSI(2)<10 entry fires too often on continuation, not reversal. A **stricter entry in adverse regimes** (e.g. RSI(2) < 5 when SPY itself is below its 200-SMA, or when the broad-market regime is risk-off) should fire fewer, higher-expectancy trades — exactly what the $5K / 3-trades-week profile needs (CONTEXT.md "be picky").
- **Discipline guardrail (§12 Davey):** this is a **candidate to backtest, NOT a hand-tune.** The frozen params (RSI<10 entry, SMA200, ATR×2) stay frozen during the current paper incubation. Any regime-conditioned tightening must be pre-specified and pass its OWN cost-robust ≥3bp walk-forward (and beat the frozen baseline OOS) before it ships. Do not adjust live thresholds because a book says "be pickier."
- **Where it would be tested:** add a `regime_strictness` axis to `backtest_connors_daily.py` (broad-market SMA200 gate + tiered RSI entry), compare OOS PF/maxDD vs the frozen baseline. Zero data cost (yfinance daily).

---

## 20. Vertical Spread Greeks — Position Anatomy
*Distilled from Saliba, "Option Spread Strategies" (2009) Ch. 2; Passarelli, "Trading Option Greeks" (2nd ed.)*

### Spread Delta — The Central Metric

A vertical spread's delta is the **sum** of the two component deltas (Saliba, p.37):

```
Bull call spread delta  = delta(long call) − delta(short call)
Bear put spread delta   = delta(long put)  − delta(short put)   [both negative; result is negative]

Example (from Saliba Ch.2):
  Long 100 call, delta = 0.75
  Short 105 call, delta = 0.25
  Spread delta = 0.75 − 0.25 = 0.50
```

**Critical behaviour: delta returns to zero at the extremes.** When the underlying is far below both strikes (spread worthless, delta ≈ 0) or far above both strikes (spread at max value, delta ≈ 0 again — you've captured all the profit). The delta is **maximum when the underlying is between the two strikes**, near the long strike. This is where the spread is most sensitive and earns the fastest.

**Delta evolution as underlying moves toward short strike:**
- Underlying at long strike → spread delta is highest (~0.45–0.55 net)
- Underlying halfway between strikes → spread delta begins to shrink
- Underlying at short strike → spread delta collapses toward zero (spread near max value)
- **Action signal:** when underlying reaches the short strike and delta collapses → EXIT the spread (maximum profit zone, nothing more to gain from holding)

### Spread Gamma

Net gamma of a debit spread = gamma(long leg) − gamma(short leg). Like delta, gamma returns to zero at the extremes and **peaks when the underlying is between the strikes** — specifically, it is most positive near the long strike and most negative near the short strike (Saliba, p.38):
- Near long strike: positive gamma → spread gaining delta quickly on favorable move ✅
- Near short strike: gamma of spread turns **negative** → delta is being stripped away by the short leg's increasing gamma → **spread is near max and will not gain further**

**For our system:** positive gamma between the strikes = the spread is "earning its keep." Negative gamma at or past the short strike = **exit signal, you are working against yourself.**

### Spread Theta (Time Decay)

Spread theta = theta(long leg) + theta(short leg). Since long options have negative theta and short options have positive theta:
- **Net theta of a debit spread is negative** — you pay time decay on net (the short leg partially offsets the long leg's decay)
- **Key advantage over naked long options:** the sold leg contributes positive theta that reduces the overall drag. A debit spread's daily theta cost is **40–60% less** than holding the long leg naked (Saliba, p.40)

Typical theta for a 21-DTE, $2-wide debit spread on a $200 underlying:
- Long leg theta: ~−$0.06/day
- Short leg theta: +$0.03/day (offset)
- **Net spread theta: ~−$0.03/day** (vs. −$0.06/day naked)

**For our system:** lower theta drag is the primary reason to use spreads when IVR is elevated. The sold leg is not just reducing cost — it is reducing the daily theta tax in half.

### Spread Vega (IV Sensitivity)

Net vega of a debit spread = vega(long leg) − vega(short leg). Both legs have positive vega (long premium), but the spread's net vega is **30–50% of the long leg alone:**
- Long leg vega: ~0.12
- Short leg vega: ~0.06 (offset, same expiry but further OTM)
- **Net spread vega: ~0.06** (vs. 0.12 naked)

**Two-sided implication:**
1. If IV rises after entry → spread gains less than a naked long option would (you sold some vega)
2. If IV falls after entry → spread loses less than a naked long option would (sold leg partly protects you)

**For our system:** in high-IV environments (IVR > 40%), the spread's reduced vega is protective. You are not as exposed to IV crush. This is precisely why the IVR routing rule (§2/§5) switches from naked to spreads above 30%.

### Quick Spread Greeks Reference Table

| Condition | Net Delta | Net Gamma | Net Theta | Net Vega | Action |
|-----------|-----------|-----------|-----------|----------|--------|
| Underlying at long strike | Maximum | Positive | Most negative | Positive | Hold — earning fastest |
| Underlying between strikes | Moderate | Near-zero | Moderate | Moderate | Hold — on track |
| Underlying at short strike | Near zero | Negative | Near-zero | Near-zero | **EXIT — near max profit** |
| Underlying below long strike | Minimal | Near-zero | Near-zero | Near-zero | **EXIT — approaching stop** |

### Leg Selection by IV — Which Strike Should Be ATM (Natenberg, p.236–240) — added 2026-05-31

The single most actionable rule for **building** a vertical spread (the 2S-B harness): which of the two strikes you make at-the-money depends on whether implied vol is cheap or rich. The ATM option is always the most vega-sensitive, therefore the most mispriced when IV is wrong.

> **"If implied volatility is low, the choice of spreads should focus on *purchasing* the at-the-money option. If implied volatility is high, the choice should focus on *selling* the at-the-money option."** — Natenberg, p.238

| IV regime (IVR) | Make ATM the… | Resulting structure | Why |
|---|---|---|---|
| Low (IVR < 30%) | **long** leg | Buy ATM call, sell further-OTM call | ATM is most underpriced when IV is too low — you want to own the most mispriced option |
| High (IVR > 50%) | **short** leg | Sell ATM call, buy further-OTM call (credit structure) | ATM is most overpriced when IV is too high — you want to sell the most mispriced option |
| Mid (30–50%) | balanced | ATM long / ~0.25-delta short debit spread (KB §5) | the standard debit vertical; neither leg has a strong vol edge |

**For the harness (2S-B):** strike placement must be IVR-conditioned, not fixed. A spread that always buys ATM regardless of IVR pays the variance premium (§22) in exactly the high-IV regime where it should be a net seller. This is the concrete mechanism behind the dual-instrument rule "the options route must carry its OWN vol edge" — leg selection *is* the vol edge.

**Theoretical edge is necessary but NOT sufficient (Natenberg, p.248):** any spread can be made to show arbitrarily large theoretical edge simply by trading it in larger size, so edge alone never justifies a trade. Edge must always be weighed against the position's risk if the volatility/direction view is wrong. See §5 "A Good Spread."

---

## 21. Volatility Skew — Negative Skew in Indexes
*Distilled from Natenberg, "Option Volatility and Pricing" Ch. 23–24; Hull, "Options, Futures and Other Derivatives"*

### What the Skew Is (Natenberg, p.502–520)

In a perfectly efficient Black-Scholes world, every option on the same underlying would have the same implied volatility regardless of strike. In reality, this **never happens.** The distribution of implied volatilities across strikes is called the **volatility skew** (or volatility smile/smirk depending on its shape).

**Cause:** Most investors are long equity. They use OTM puts as insurance against a decline. This hedging demand drives OTM put prices (and therefore IV) higher than the model implies. There is no equivalent demand for OTM calls. Result: a persistent **downward-sloping skew** in stock indexes.

### The Negative Skew — Empirical Data (Natenberg, p.512–515)

Natenberg's direct market data for S&P 500 (FTSE 100 also shown as typical):
- **Skewness = −0.536** (empirically measured in S&P 500 daily returns)
- This means: the left tail (down moves) is longer than the right tail (up moves)
- OTM puts are systematically priced with **higher IV than equidistant OTM calls**

Practical illustration (approximate, from Ch. 24):
```
Strike (relative to ATM)  | Implied Vol
ATM (100%)               | 20%  (baseline)
5% OTM call (105%)       | 18%  (-2 vol pts — calls are "cheap")
5% OTM put  ( 95%)       | 23%  (+3 vol pts — puts are "expensive")
10% OTM call (110%)      | 16%  (-4 vol pts — further OTM calls even cheaper)
10% OTM put  ( 90%)      | 27%  (+7 vol pts — puts become very expensive)
```

Lowell (p.218) confirms: "Ever since the market crash of 1987, the OTM put options in the Dow Jones, S&P, and NASDAQ have all exhibited a large reverse skew."

### Practical Implications for Our System

**1. Call spreads have a structural vol tailwind; put spreads have a structural headwind.**

For a bull call spread (buy ATM, sell OTM call): you buy at the baseline IV and sell a call that is already priced at *below* baseline IV. The spread's vega cost is lower than a flat-vol model would suggest. **This is beneficial — you are not overpaying for the spread.**

For a bear put spread (buy ATM put, sell OTM put): you buy at elevated IV (ATM put) and sell a put that is priced at *even higher* IV (OTM put is more expensive). The spread's net cost is actually reduced by the elevated short-leg premium. **The high skew makes put spreads naturally cheaper in dollar terms — but this is the market's pricing efficiency at work, not free money.**

**2. The "skewed delta" effect (Natenberg, p.517).**

Because OTM puts carry higher IV, their effective ("skewed") delta is larger than the standard Black-Scholes delta suggests. A put that B-S says has delta −0.20 might effectively behave like a −0.25 delta put because the IV input is higher. For our option system: when selecting put strikes for bear put spreads, the OTM short put leg has more delta exposure than you think. Do not go further OTM just because the nominal delta looks small.

**3. Post-crash skew steepens; low-vol regimes flatten it.**

- VIX > 25: skew steepens dramatically. OTM put IV can jump 5–10 vol points. This further inflates the cost of buying puts and rewards put sellers.
- VIX < 15: skew flattens. OTM puts and calls are closer in vol. Better environment for buying put protection.

**Rule: in low-vol regimes (VIX < 15), put protection is cheapest relative to calls — if you want directional put plays, enter them in low-vol environments.** In high-vol environments, the skew makes put buying expensive; prefer call buying on the upside recovery or use debit spreads.

---

## 22. Variance Risk Premium & Volatility Forecasting
*Distilled from Sinclair, "Option Trading: Pricing and Volatility Strategies" (2010) Ch. 7–8; "Volatility Trading" (2013)*

### The Variance Risk Premium (VRP) — Sinclair Ch. 8

The **variance risk premium** is the persistent tendency for implied volatility to **exceed realized volatility**. It is the most structurally important fact in options for a long-premium trader to understand:

- **Magnitude:** IV runs ~2–4 volatility points above subsequent realized vol on average for SPY/large-cap names.
- **Frequency:** IV exceeds realized vol approximately **70% of trading months** (Sinclair's empirical measure).
- **Direction:** the VRP is a structural premium earned by net vol sellers (credit spreads, naked puts) at the expense of net vol buyers (debit spreads, naked calls/puts).

**What this means for our system (long premium, debit buyers):**
The VRP is a **structural headwind** against long premium strategies. On average, you are paying ~2–4 vol points more than the underlying will actually move. For a 21-DTE debit spread costing $1.00, the VRP headwind might cost $0.08–0.15 of expected value.

**How to overcome the VRP:**
1. **Directional edge must be large enough** to overcome the VRP. The Connors RSI(2) strategy has a validated PF 1.31@3bp — this directional edge must carry the options trade.
2. **Enter only when IV is below or near HV** (IVR < 30%): this is when the VRP headwind is smallest — you are buying when IV is already compressed, leaving less room for further compression.
3. **Use spreads** to reduce vega exposure and thus VRP sensitivity.

### Volatility Forecasting — Practical Blend (Sinclair Ch. 7)

Sinclair's volatility forecasting hierarchy (best predictors of near-term realized vol):

| Forecaster | Predictive power (5-day horizon) |
|---|---|
| Recent 5-day realized vol (GARCH effect) | ~45% |
| 30-day implied vol (VIX-type measure) | ~35% |
| Combination blend | ~55% (best available) |

**Practical blend formula:**
```
Expected_5d_vol = 0.45 × HV5 + 0.35 × IV30 + 0.20 × HV30
```
Where HV5 = 5-day realized vol annualized, IV30 = current 30-day ATM implied vol, HV30 = 30-day historical realized vol.

**For our system:** options are "cheap" (favourable entry) when `Expected_5d_vol > IV30`. This means the underlying is moving more than options currently imply.

### GARCH Effect — Volatility Clustering (Sinclair Ch. 7)

The single most actionable empirical finding from Sinclair:
- **Vol clusters:** high-vol days follow high-vol days, low-vol days follow low-vol days.
- If SPY has had ≥ 3 consecutive days with moves > 1%: probability next 5 days > 0.8% daily = ~65%
- If SPY has had ≥ 5 consecutive days with moves < 0.4%: probability next week < 0.5% daily = ~70%

**Rules for our system:**
- **Entering AFTER 3+ high-vol days:** options are expensive (GARCH inflates IV expectations). Use debit spreads; reduce size. The current move is already "priced in."
- **Entering AFTER 5+ low-vol days:** options are cheap relative to recent movement. Naked longs are acceptable if IVR < 30%. Best window for long premium entry.
- **Vol clustering → trend persistence for our Connors strategy:** if we are in a high-vol cluster, the RSI(2) mean-reversion signal has stronger context. The mean-reversion from an oversold extreme is amplified when surrounding vol is high.

### Term Structure — Contango vs. Backwardation (Sinclair Ch. 8)

**Normal (contango):** front-month IV < back-month IV. Market is calm. Rolling options to later months is expensive (you pay up for time).

**Inverted (backwardation):** front-month IV > back-month IV. Market is fearful about near-term events. The front month is being "bid up" due to hedging demand for the short-term period.

**Reading term structure at entry:**
- If 21-day IV significantly above 60-day IV → backwardation → near-term fear premium is elevated. For debit buyers: the options you want to buy are expensive. Consider buying the 45–60 day expiry instead (where IV is lower) even if it means more theta.
- If 21-day IV approximately equal to 60-day IV → normal contango → buy the 21-30 day expiry as planned.
- **Rule:** check IV at target DTE vs. next-month IV. If front-month IV is more than 3 vol points above next-month, you are buying at the wrong expiry — roll the entry to the calmer month.

---

## 23. Earnings & Event IV — Build/Crush Mechanics
*Distilled from Lowell, "Get Rich With Options" (2009) p.45, 59–60; Benklifa, "Think Like an Option Trader"; Saliba, "Option Spread Strategies" Ch. 1*

### The Earnings IV Buildup (Lowell, p.59–60)

Lowell (former NYMEX floor trader): *"Have you ever bought call or put options right before a stock was about to have its earnings announced? I'm sure many of you thought that buying options as a fast-money play was going to be a quick and easy way to make a fortune. But in almost every instance, you saw the price of all options rise significantly before the announcement... The option market makers are no dummies. They will reprice the options based on the level of uncertainty of the earnings announcement."*

**The pattern (applies to our 39-symbol universe):**
1. **D-10 to D-5 before earnings:** IV begins rising steadily. The implied move (straddle price / stock price) starts to expand.
2. **D-2 to D-1:** IV peaks. Market makers price in maximum uncertainty. This is the **most expensive time to buy options**.
3. **Post-announcement (typically overnight or pre-market):** IV collapses immediately, often 30–55%. Even a large directional move is frequently priced in — you can be directionally right and LOSE money.

**Why long premium fails into earnings:**
- You buy at peak IV (D-1)
- Stock moves, say, +5% as expected
- IV collapses 40% on the open
- Net result: option price unchanged or DOWN despite the directional win

### IV Crush Magnitude by Event Type

| Event | When IV spikes | Typical pre-event IV rise | Post-event IV crush | Duration of elevated IV |
|-------|---------------|--------------------------|--------------------|-----------------------|
| Quarterly earnings | 5-10 days before | +15–35% above normal | 30–55% immediately | 1–2 days before → 0 after |
| FOMC decision | 1–2 days before | +10–25% | 10–25% after announcement | Day before → partial crush |
| CPI release | Morning of | +8–15% | 8–15% after 8:30 AM ET | Single day |
| NFP | Morning of | +8–15% | 8–15% after 8:30 AM ET | Single day |

*Note: Our macro blackout calendar (§19) already blocks FOMC, CPI, NFP day entries. This table explains WHY.*

### Rules for Existing Positions Approaching Earnings

Our earnings exclusion blocks **new entries** within 2 days of earnings. But what about positions already held?

**If an open position has earnings within its DTE window:**
- D-5: monitor. If the position is profitable (+30% or more), consider closing.
- D-2: **hard close trigger.** Close the position on D-2 before earnings regardless of P&L. You are about to hold through peak IV buildup that will invert when the event resolves.
- **Exception:** if already at the profit target (80% of max spread value), close immediately regardless of DTE to earnings.

**Rule: no position should be held through an earnings announcement unless the strategy was explicitly designed for it (e.g., an iron condor betting on IV crush — which this system does not run).**

### Post-Earnings Re-Entry Window

After earnings IV crush, options briefly become **underpriced** relative to normal levels (IV below 30-day moving average). This creates a 2–5 day window of favorable long-premium entry conditions.

**Specific case for Connors RSI(2) signals post-earnings:**
- A stock beaten down on earnings can trigger RSI(2) < 10
- At the same time, IV has just crushed back to below-normal levels
- This is a **double-quality entry signal**: directional mean-reversion setup + cheap premium
- **Rule:** post-earnings RSI(2) < 10 + IV30 < 30-day HV = A-tier entry for debit spreads. Enter within 2 days of earnings release (not within 2 days of NEXT earnings).

---

## 24. Active Spread Management & Rolling Discipline
*Distilled from Saliba, "Option Spread Strategies" (2009) Ch. 1–2; Fontanills, "The Options Course" Ch. 12; Lowell, "Get Rich With Options" p.82, 105*

### The Core Principle: Active Management Is Mandatory

Saliba (p.29): *"Regardless of whether one falls into the short-term or long-term, high-risk or low-risk category, one thing is for sure: After the trade is selected and executed, it will have to be managed."*

Options are not "set and forget" positions. A vertical spread has Greeks that change every day as time passes and the underlying moves. Passive holding = guaranteed underperformance on losing trades and leaving profits on the table on winners.

### Lowell's Cardinal Rule (p.82)

*"DON'T HOLD THE OPTION TO EXPIRATION. SELL THE OPTION WHEN YOU HAVE A PROFIT!"*

This principle from a former market maker is the single most important practical management rule. The reasons:
1. Final-week theta decay is extreme — profits earned over 2 weeks can evaporate in 2 days
2. Gamma risk spikes — small adverse moves cause large P&L swings
3. Bid-ask widens — your exit price deteriorates as liquidity providers price in expiration risk
4. Pin risk — underlying can "pin" at the short strike, creating unpredictable assignment outcomes

**Rule: do not hold a debit spread to expiration. Take profit at 75–85% of max spread value and exit.**

### The Spread Close Hierarchy — When to Close

**Priority order (close at FIRST trigger hit):**

| Trigger | Threshold | Why |
|---------|-----------|-----|
| Max profit | 80% of spread width − debit paid | Last 20% requires expiration; gamma risk not worth it (Lowell p.82) |
| Scale-out T1 | +50% of debit paid | Half-position close; lock partial gain (Fontanills Ch.12) |
| Stop loss | −50% of debit paid | Non-negotiable; prevents catastrophic losses |
| Thesis broken | Underlying violates signal condition (RSI(2) > 70) | Signal resolved; don't hold for the trade to "come back" |
| DTE countdown | 7 DTE | Gamma risk too high; close regardless (Saliba Ch.2 Greeks) |
| Earnings approach | 2 days before earnings of underlying | IV build will inflate then crush (§23) |
| Time stop | Hold time > 2× average Connors exit days | Stale thesis; exit and redeploy |

### Rolling — When It Makes Sense vs. When It Doesn't

Rolling = closing the current spread and opening a new spread at different strikes or expiry.

**Roll when ALL three conditions are met (Saliba Ch.1 rolling examples, p.31–34):**
1. **Thesis is still intact** — the directional signal has not reversed (RSI(2) still < 70, underlying still in uptrend)
2. **Time remains** — there are at least 14 days until expiry; rolling to the next month adds meaningful time
3. **Roll improves your position** — the credit/debit of the roll operation is net-neutral or better (not paying a large additional debit to extend)

**Do NOT roll when:**
- Thesis is broken (RSI(2) resolved, underlying broke the opposite direction) → **close, do not extend**
- Position is −50% already → taking on more time adds capital at risk to a losing thesis
- The roll costs more than 50% of the original debit paid → too expensive to justify

**Rolling mechanics (Saliba p.31, rolling up example):**
```
Example: Bull call spread at 100/105, underlying moves to 106
- Position near max profit (spread worth ~$4.50 on $5.00 wide spread)
- To "roll up": buy the 100/105 spread to close ($4.50 debit to close), 
  open a new 105/110 spread ($2.00 credit) in the same expiry
- Net cost of roll: $4.50 − $2.00 = $2.50 debit → total cost basis rises
- New spread gives 5 more points of upside if bullish thesis continues
- Only makes sense if strong continued bullish conviction AND time remains
```

**Rule: rolling is a tool for extending profitable positions with intact thesis, NOT a way to avoid taking losses on broken trades. Saliba: "The downside risk must be managed ruthlessly so that when the forecast is proven wrong, the trader must exit or neutralize the position immediately."**

---

## 25. Options Liquidity, Strike Selection & Execution
*Synthesized from McMillan, Saliba (p.10: "spread books"), OIC Quick Reference; applied to our 39-symbol universe*

### Symbol Liquidity Tiers

Not all 39 symbols in our universe have equally liquid options chains. Liquidity determines fill quality, bid-ask drag, and whether a spread order can be executed as a unit.

**Tier 1 — Excellent (use freely, all strategies):**
SPY, QQQ, AAPL, AMZN, GOOG, MSFT, NVDA, META, NFLX
- ATM bid-ask: $0.01–0.05. OI at ATM strikes: 5,000–100,000+
- Spread orders fill at mid within 30–90 seconds
- All spread widths and strategies viable

**Tier 2 — Good (debit spreads viable, verify each strike):**
JPM, BAC, WFC, C, MA, V, AMD, PLTR, CRM, ADBE, CRWD, ORCL
- ATM bid-ask: $0.05–0.20. OI at ATM strikes: 500–5,000
- Spread orders fill at mid; may need 2–4 minutes
- Check OI at BOTH legs before entering; if either leg < 500 OI, skip

**Tier 3 — Moderate (single-leg checks required; spreads may gap):**
INTC, LRCX, AVGO, TSM, ARM, IBM, TEAM, NET, NOW, UBER, NKE, IWM
- ATM bid-ask: $0.10–0.40. OI: 200–1,000
- Leg-by-leg OI check mandatory; if short-leg OI < 200, **skip options, use shares instead**
- Per §5 transaction cost hierarchy: thin edge + illiquid options = negative expectancy

**Tier 4 — Potentially illiquid (shares preferred over options):**
SOFI, HOOD, CRWV, CBRE, GLW, C (small float names)
- Options chains may be sparse; bid-ask often > 5–10% of mid
- Cost of a round-trip in options can exceed the expected profit of the trade
- **Rule:** for Tier 4 names, default to shares (§19 KB rule: "shares only; options costs destroy this edge for thin directional signals")

### Strike Width by Price Level

Spread WIDTH relative to underlying price determines the meaningful risk/reward:
- Width < 0.5% of underlying price = too narrow (slippage eliminates edge)
- Width 1–3% of underlying price = target zone
- Width > 5% = overpaying for limited upside

| Symbol range | Min width | Target width | Notes |
|---|---|---|---|
| SPY $500–600 | $1 | $2–3 | $1 wide is minimal; $3 wide is optimal |
| AMZN, GOOG $150–220 | $1 | $2.50–5 | $1 wide is tight; prefer $5 |
| NVDA $600–1200 | $5 | $10–20 | $5 wide on NVDA is ~0.5%; $10–20 is right |
| META $400–600 | $2.50 | $5–10 | |
| MSFT $380–450 | $2.50 | $5–7.50 | |
| ARM $100–200 | $2.50 | $5 | |
| JPM, BAC, WFC $40–200 | $1 | $2.50–5 | |

**Rule: never trade a spread where the width is less than 3× the per-leg bid-ask spread. If the option bid-ask is $0.10 and the spread width is $0.50, slippage is 40% of max profit — not viable.**

### Strike Selection — DTE-Matched for Our Strategy

For the Connors RSI(2) daily-bar strategy with expected hold of 3–7 trading days:

- **Optimal DTE at entry: 21–28 days** — provides enough time for the mean-reversion to complete without excessive theta drag; leaves 14–21 DTE when the typical exit fires (RSI(2) > 70)
- **Acceptable DTE: 14–21 days** — higher theta exposure; trade must resolve in ≤ 5 days
- **Avoid: < 14 DTE** — theta too punishing for a multi-day hold; 7-DTE close rule would force exit before the signal can resolve

**Strike configuration (McMillan's optimal for directional debit spread):**
- Long strike: ATM or 1 strike ITM (delta 0.50–0.60) — ensures maximum delta sensitivity at entry
- Short strike: 1–2 strikes OTM (delta 0.25–0.35) — caps upside but sells enough premium to meaningfully reduce cost
- **Break-even check:** debit paid should be ≤ 40% of spread width. If debit is > 45% of width, the risk/reward is unfavorable — skip or widen the spread.

### Spread Order Execution

Saliba (p.10): *"Electronic spread books are accessible through the same front-end systems offered by most brokers. If a broker doesn't offer direct access to the spread books, it is time to switch brokers."*

**Always use a combo/spread order (not two separate legs):**
- A single spread order eliminates "leg risk" (one side fills, the other doesn't)
- In Alpaca: submit as a multi-leg option order with the natural mid price as the limit
- **Natural price = ask(long leg) − bid(short leg)** for a debit spread
- **Target fill price = mid = (ask(long) − bid(short) + bid(long) − ask(short)) / 2**
- If unfilled at mid after 2 minutes, walk price by $0.02–0.05 toward natural
- Hard cap: never pay more than the natural (ask of long − bid of short)

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

### Timeframe & Cost-Structure are First-Class Strategy Choices — added 2026-05-19 (this project's durable learning)
- **The corner of the market you search in matters more than the signal you pick.** 5-minute intraday + retail-cost shares/naked-options is the *single hardest* corner — HFTs/market-makers compete most fiercely there, spreads are the largest fraction of P&L, and edges decay fastest. Many promising signals (e.g., canonical Connors RSI-mean-reversion) *cannot even fire* at that timeframe because their indicators (long-period MAs) don't form. Tuning a signal at the wrong frame is fighting the friction, not the market.
- **Edge probability rises sharply at slower timeframes** for retail. Transaction costs are largely fixed *per trade*; expected return scales with *hold horizon*. A signal that dies at 5 bp intraday may clear it comfortably at daily/weekly bars with multi-day holds because the cost-to-edge ratio improves an order of magnitude.
- **Cost structure (broker tier, account type) is a strategy variable, not a constant.** Pro-tier per-share/per-contract pricing can move a 3 bp realistic gate to ~1 bp realistic — *same edge, opposite verdict.* Treat broker selection as part of strategy design, not a downstream detail.
- **Practical rule:** before tuning a signal further, ask *"is this signal in the timeframe and instrument it was designed for?"* If no, no amount of tuning rescues it — change the frame first. (This project's empirical evidence: Tier-1 + Tier-2 both failed in the 5-min intraday retail-cost frame, with no contradiction across 8 master texts.)

---

---

# TRADING KNOWLEDGE BASE

> **Added 2026-05-24.** Distilled from deep cover-to-cover reading of 20+ day trading and general trading books in `/Users/bsannadi/Desktop/bharath/books/`.
> **Primary sources:** Aziz (*How to Day Trade for a Living*, *Advanced Techniques in Day Trading*), Elder (*Step by Step Trading*, *The New Trading for a Living*), Connors/Alvarez (*Short-Term Trading Strategies That Work*), Volatile Markets Made Easy (Turner/Krausz), O'Neill/Morales/Kacher (*Trade Like an O'Neil Disciple*), Raschke/Williams (*Street Smarts*), Bernstein (*30 Days to Market Mastery*), Ways of Trade (Grimes), Keene (*Keene on the Market*).
> **Backtested:** 2yr · 25 S&P 500 symbols · next-day open→close · run 2026-05-24.

---

## §T1. The Three-M Framework — Mind, Method, Money (Elder)

Every professional trading system has three inseparable pillars. Weakness in any one destroys the other two.

### Mind
- **Trading is primarily a psychological problem.** Most retail traders lose not because their edge is wrong but because they cannot execute it consistently. (*The New Trading for a Living*, Elder)
- **Two enemies: fear and greed.** Fear causes early exits before targets. Greed causes holding winners into reversals and adding to losers.
- **The crowd is your counterparty.** When you buy at the top, a professional is selling to you. When you panic-sell at the bottom, a professional is buying from you. Think the opposite of the emotional crowd.
- **Write a trading plan before the market opens.** Every entry, every stop, every target — decided in advance when you are calm. In-the-moment decisions are almost always emotional.
- **"An amateur has a tendency to become excited when a stock moves in his favor, and frightened when it moves against him."** — Livermore. The professional feels neither; he executes the plan.
- **Three session journal entries:** Before open (plan), after close (result vs. plan), weekly (patterns in mistakes). Journaling is the single most productive habit difference between improving and stagnant traders.

### Method
- **A method must be rule-based, backtestable, and have demonstrable edge.** "Gut feel" is not a method. Gut feel that has been backtested and matches rules is experience.
- **One setup, mastered.** Beginning traders who try to trade every pattern learn none well. Pick one setup (e.g., RSI Dip mean-reversion), learn its nuances, trade it exclusively until you are consistently profitable.
- **Setup → Trigger → Follow-through (Bernstein, *30 Days to Market Mastery* p.18).** All three must be present:
  - **Setup:** The background condition (e.g., RSI14 < 35, stock in prior uptrend)
  - **Trigger:** The entry signal (e.g., price bounces off VWAP with volume, first green candle after dip)
  - **Follow-through:** Confirmation that the move is real (e.g., next candle closes higher, volume expanding)
  - Without follow-through, setups and triggers are noise.
- **Grade every trade A/B/C before entry.** Only take A and B-grade setups. C-grades kill accounts slowly.

### Money
- **Elder 2% Rule:** Never risk more than 2% of account on any single trade. (*The New Trading for a Living* p.173)
- **Elder 6% Rule:** If total open risk across all positions reaches 6% of account, stop opening new trades for the rest of the month. This hard cap prevents catastrophic drawdown months.
- **"The main purpose of a stop is not to give you an exit — it is to define your risk before you enter."** — Elder. Without a pre-defined stop, position sizing is impossible.
- **Losers are inevitable; catastrophic losers are a choice.** A 2% loser is a business expense. A 20% loser is a failure of money management, not trading skill.

---

## §T2. Market Climate & Session Windows (Grimes, Aziz, Elder)

### The Two Climates (Grimes, *Ways of the Trade* p.44)
Understanding which climate you are in is more important than any indicator.

| Climate | Characteristics | Trading Mode |
|---------|-----------------|--------------|
| **Wet** (Active) | Heavy volume, wide ranges, strong follow-through, news catalyst | Trade more setups, hold longer, size normally |
| **Dry** (Inactive) | Thin volume, tight ranges, choppy reversals, no catalyst | Trade smaller, fewer setups, quick exits, survive |

- **Check the pre-market:** volume > 1.5× 30-day average by 9:25 AM = likely Wet session. Act accordingly.
- **VIX:** VIX > 20 often signals Wet climate (large-range day). VIX < 15 typically means Dry (grind).
- **Wet does not mean easy.** Wet markets move faster, which means stops are also hit faster. Discipline matters more, not less.

### Thunder Periods — Best Entry Windows (Grimes p.38, Aziz)
| Window | Why | Best Action |
|--------|-----|-------------|
| **9:30–11:00 AM ET** | Highest volume, largest ranges, news absorption, institutional order flow | Primary session for day trades; ORB/Gap/RSI Dip entries |
| **11:00 AM–2:00 PM ET** | Lunch lull; volume drops 30–50%; choppy, mean-reverting | Avoid new entries; manage existing positions; reduce size |
| **2:00–3:30 PM ET** | Second thunder period; institutional rebalancing, algorithmic momentum | Re-enter on afternoon breakouts; Bull Flag continuation setups |
| **3:30–4:00 PM ET** | Options pinning, portfolio rebalancing, unpredictable spikes | Close day trades; do NOT open new positions |

**Rule:** All four backtested setups (RSI Dip, Breakout, Gap+Vol, Bull Flag) perform best when entered in the 9:30–11:00 AM or 2:00–3:30 PM windows. Avoid lunch-hour entries.

### Pre-Market Checklist (Aziz, *How to Day Trade for a Living* p.31)
Before 9:30 AM, run through:
1. **What is SPY doing?** Pre-market gap? Trend direction?
2. **What is VIX?** Above or below 20? Above 25 = reduce size.
3. **Any major economic releases today?** CPI, FOMC, NFP = no naked options; use spreads only.
4. **Which stocks gapped > 1% on elevated volume?** Candidates for Gap+Vol setup.
5. **Which stocks are at or near RSI14 < 35 on daily?** Candidates for RSI Dip.
6. **Which stocks made new 52-week or 50-day highs in pre-market?** Candidates for Breakout.
7. **What is my max daily loss limit today?** Set it before the open. Non-negotiable.

---

## §T3. Stock Selection — Universe & Stocks in Play (Aziz, Elder)

### What Makes a "Stock in Play" (Aziz, *How to Day Trade for a Living* p.31)
A stock is "in play" when it has a **reason to move** that retail can exploit. The reason must be fresh.
- **Earnings surprise** (beat or miss) — most powerful catalyst
- **Analyst upgrade/downgrade with large price target change**
- **FDA approval/rejection** (biotech/pharma)
- **Merger/acquisition news**
- **Large pre-market gap** (> $1 or > 2%) on volume > 1.5× 30-day average
- **Sector sympathy move** — when a leader gaps, related stocks often follow

**Without a catalyst, a stock is NOT in play.** Do not day-trade random stocks that are just moving intraday.

### The 25-Symbol Universe (Backtested, this system)
Selected for: high ADV > 5M shares/day, high options liquidity, sector leadership, intraday volatility, active institutional sponsorship.

```
Semis:      NVDA, INTC, AMD, MU, QCOM, AVGO, LRCX, AMAT, TXN, MCHP, ON
Tech/AI:    PLTR, ORCL, NOW, ANET, CRM, APP
EV/Growth:  TSLA
Specialty:  COHR (photonics), SMCI (servers), WDC (storage), GLW (fiber), VRT (power infra)
Other:      HOOD (fintech), CVNA (retail)
```

### Stock Quality Filter (Elder, Aziz)
Before taking any trade on a symbol, verify:
- **Relative Volume ≥ 1.3×** minimum; ≥ 1.5× preferred. Below 1.0× = avoid (institutional absent).
- **Bid-ask spread ≤ $0.05** on the stock, ≤ 5% of mid on its options.
- **Daily range ≥ 1.5% of price.** Below this = not enough room for profit after spread.
- **No earnings within 2 trading days.** IV will be distorted.
- **No halts in prior 5 sessions.** Unreliable price action.

---

## §T4. Chart Reading Essentials (Elder, Brooks, Aziz, Raschke)

### Key Moving Averages
| EMA | Role | Interpretation |
|-----|------|----------------|
| **EMA 9** | Intraday momentum | Price above = intraday bull; below = bear |
| **EMA 20** | Short-term trend | "Control line" for day trades (Aziz) |
| **EMA 50** | Medium-term trend | Institutional reference; major support/resistance |
| **EMA 13** | Elder daily | Part of Impulse System (Elder p.47) |
| **EMA 26** | MACD base | Used with EMA13 for Impulse System |

**Bull stack:** EMA9 > EMA20 > EMA50 = all three timeframes aligned → trade long only.
**Bear stack:** EMA9 < EMA20 < EMA50 = all three aligned → trade short only (or avoid longs).

### VWAP (Volume Weighted Average Price)
- **The single most important intraday indicator for institutional order flow.**
- Institutions benchmark all executions to VWAP. A stock holding above VWAP all day = institutions are buyers. Below VWAP = institutions are sellers.
- **VWAP Bounce setup (long):** Price pulls back to VWAP, forms a bullish candle, volume dries up on the pull-back → buy above the bounce candle.
- **VWAP Rejection (short):** Price rallies to VWAP from below, forms a bearish candle, fails to reclaim → short below the rejection candle.
- **Rule:** Never fight VWAP on the first test. The first VWAP test of the day has the highest success rate.

### Support and Resistance (Brooks, *Trading Price Action Trends*)
- **Previous day's high/low:** Most reliable overnight S&R levels. A break above prior day's high = momentum trigger.
- **Whole numbers and half-dollars ($100, $100.50):** Psychological levels where institutions place limit orders.
- **Prior breakout levels:** A stock that broke out at $85 will often find support there on the first retest.
- **Opening Range (ORB High/Low):** The 15-minute opening range becomes the primary S&R for the first session. Break above = bull; break below = bear.

### Candlestick Patterns Worth Knowing (Aziz, Brooks)
| Pattern | Signal | Entry |
|---------|--------|-------|
| **Doji after run** | Indecision; potential reversal | Wait for next candle to confirm direction |
| **Hammer/Pin bar at support** | Buyers stepped in; bullish | Buy above hammer high; stop below tail |
| **Engulfing candle** | Momentum shift | Buy above bull engulfing; stop below its low |
| **Inside bar (IB)** | Consolidation; energy building | Buy above IB high (breakout), sell below IB low |
| **Three-bar reversal** | Exhaustion pattern | On 3rd bar in same direction after a run, fade |

---

## §T5. Risk Management — The Professional Standard (Elder, Aziz, Connors)

### Position Sizing for Day Trades
```
Max $ Risk per trade   = Account × 0.01  (1% rule for day trading)
Stop distance ($)      = Entry − Stop level
Share size             = Max $ Risk / Stop distance
```
**Example:** $50,000 account. Entry NVDA at $120. Stop at $118.50 (1.5% gap).
- Max risk = $50,000 × 0.01 = $500
- Stop distance = $120 − $118.50 = $1.50
- Shares = $500 / $1.50 = 333 shares (~$40,000 notional, appropriate for high-conviction trade)

### Hard Stop Rules
- **Pre-set stops before entry, always.** Without a stop, you are gambling.
- **Never widen a stop after entering.** The only acceptable stop movement is tightening (trailing up for long positions).
- **Mental stops do not work.** Real stops in the platform, real time. Psychological research shows humans consistently fail to execute mental stops under stress.
- **If a position feels wrong within the first 2 minutes, exit.** The initial instinct is almost always correct. Hesitation is costly.

### Daily Loss Limit — The Non-Negotiable Hard Cap
| Account Size | 1% / Trade Max | 3% Daily Stop |
|---|---|---|
| $25,000 | $250 | $750 |
| $50,000 | $500 | $1,500 |
| $100,000 | $1,000 | $3,000 |

- **3 consecutive losses → pause 30 minutes.** Recalibrate. Read the plan again.
- **Hit daily stop → close platform. Done for the day.** No exceptions.
- **"The amateur thinks about how much he can make. The professional thinks about how much he can lose."** — Elder

### Scale In / Scale Out (Aziz, Volatile Markets p.64)
- **Scale into winners, never into losers.** Add only when the position is already profitable and thesis is confirmed.
- **Partial exits:** Exit 50% at first target (1×R), trail stop to breakeven on the remaining 50%. Now the worst case is breakeven.
- **Bull Flag trade management (Volatile Markets p.64):** First partial at 50% of the initial flagpole's length. Trail trendline as stop for the runner.

---

## §T6. Elder Impulse System — The Trade Filter (Elder, *Step by Step Trading* p.47)

The Impulse System is not a standalone trading system — it is a **censorship system** that tells you when NOT to trade.

### Signal Definitions
| Color | Conditions | Meaning | Action |
|-------|-----------|---------|--------|
| **🟢 Green** | EMA13 rising AND MACD-Histogram rising | Bulls in full control; upside momentum | Long entries permitted |
| **🔵 Blue** | Mixed (one up, one down) | No clear momentum consensus | Watch; reduce size; wait for Green |
| **🔴 Red** | EMA13 falling AND MACD-Histogram falling | Bears in full control | **NO long entries for momentum setups** |

### Backtest Insight: Impulse Color Matters Differently by Setup Type

| Setup | Red PF | Green PF | All PF | Insight |
|-------|--------|----------|--------|---------|
| RSI Dip | **1.82** | 1.76 | 1.41 | Red = BETTER (mean-reversion thrives in sustained selling) |
| Breakout | 0.00 | 1.67 | 1.88 | Never appears in Red (trends require momentum) |
| Bull Flag | 0.00 | **2.29** | 1.44 | Green confirmation = dramatically better |
| Gap+Vol | 1.54 | 1.29 | 1.37 | Gaps work in any condition |

**Critical rule for this system:**
- For **RSI Dip** (mean-reversion): Red Impulse is **acceptable** and actually signals more extreme oversold conditions. Do NOT use Impulse Red as a veto for RSI Dip entries.
- For **Breakout and Bull Flag** (momentum): Red Impulse = avoid. These setups require upward momentum; Red Impulse signals that momentum has reversed.

### Implementation (this system's screener)
- Computed from daily EMA13 and MACD-Histogram (EMA13 − EMA26 − signal)
- Displayed per stock: 🟢/🔵/🔴 with tooltip explaining the backtest rationale
- RSI Dip + Red Impulse → `🔴Imp(dip-ok)` label (Red is expected for deep dip entries)
- Breakout/Bull Flag + Red Impulse → `⛔Impulse-Red` (caution)

---

## §T7. Elder Force Index & Value Zone (Elder, *Step by Step Trading* p.39)

### Force Index 2-Day EMA (FI2d)
- **Formula:** FI = (Today's Close − Yesterday's Close) × Today's Volume
- **2-day EMA of FI** smooths the raw signal.
- **Interpretation for day traders:**
  - **FI2d < 0 during an uptrend:** Bears briefly in control — *bargain buy zone* for long setups (Elder p.39).
  - **FI2d > 0 during a downtrend:** Bulls briefly in control — *sell-short zone* for short setups.
- **In this system:** FI2d < 0 is shown as `🔽FI<0` on RSI Dip setups — confirms the dip is "real" selling pressure, not just lack of buyers.

### Elder Value Zone
- The zone **between EMA13 and EMA26** on a daily chart (the MACD inputs).
- In an uptrend, price that pulls back into this zone has the best risk-reward for long entries.
- Buying in the Value Zone means you are entering where the "fair price" consensus is, not chasing.
- **Avoid buying above the Value Zone** (momentum chase) or far below it (trend may be broken).

---

## §T8. O'Neill Pocket Pivot — Early Accumulation Signal (Morales/Kacher, *Trade Like an O'Neil Disciple* p.132)

### Definition
A Pocket Pivot occurs when:
- **Today's stock volume exceeds the highest down-volume day in the prior 10 sessions.**
- Today's candle is an up day (close ≥ open).

### Why It Works
Institutions cannot hide large accumulation. When volume on an up day exceeds any recent down-day volume, it signals that buyers are absorbing sellers and taking the stock higher against the selling pressure. This is "early stage" accumulation before a full breakout.

### How to Use It
1. **As a secondary confirmation:** A stock with RSI Dip OR Breakout setup AND Pocket Pivot has two independent signals aligned → highest conviction.
2. **As a standalone scan:** Stocks making Pocket Pivots near their 50-day MA are O'Neil's best candidates for multi-week holds.
3. **Ideal context:** Pocket Pivot within a base (consolidation after prior uptrend), not extended from any prior base. The base should be at least 3-4 weeks long.

### Trade Rules
- **Enter:** On the Pocket Pivot day, buy near the close or the next morning's open.
- **Stop:** Below the 10-day MA or below the low of the Pocket Pivot candle, whichever is wider (but < 7% from entry).
- **Profit target:** Hold for the full breakout — this is an intermediate-term setup (weeks, not days), unlike the intraday setups.

### In this System
- Displayed as `📌 PktPivot` flag in the screener next to the symbol's pick column.
- Increases conviction on intraday RSI Dip and Breakout setups for same-day entries.

---

## §T9. ConnorsRSI Daily Mean-Reversion System (Connors/Alvarez, *Short-Term Trading Strategies That Work* 2013)

### Core Signal
**RSI(2) < 10 on daily bars → next-day directional accuracy: 66.4%**

Backtested over 17+ years across S&P 500 stocks. The simplest, most robust mean-reversion edge in retail day trading literature.

### Full System Rules (Connors *Short-Term Trading Strategies*, Chapter 3)
1. **Stock is above its 200-day MA** (primary uptrend filter — do not buy broken stocks)
2. **Daily RSI(2) closes below 10** (deeply oversold — 2-day RSI is ultra-sensitive to short-term pullbacks)
3. **Entry:** Buy the OPEN of the next trading day
4. **Exit:** When RSI(2) closes above 70 (overbought) — typically 1–5 days later
5. **Size:** Equal-weight; no leverage

### Why RSI(2) Works
RSI(2) measures 2-day momentum. When a stock that is in a healthy uptrend (above 200-day MA) experiences 2 consecutive down days powerful enough to push RSI(2) below 10, institutions typically step in to buy the discount. The edge is essentially: **buying temporary weakness in structurally strong stocks**.

### Key Statistics (2yr backtest, this system, 25 symbols)
- **Win rate: 50.1%** (by directional hit, next-day open→close)
- **Profit Factor: 1.05** (modest on next-day alone; stronger on multi-day hold as Connors designed)
- **Best for options:** Use directional accuracy for call selection, not the stock trade itself. RSI(2) < 10 → buy ATM call for 1–5 day hold.

### Extensions (from Connors' book)
| Variation | Win Rate | Notes |
|-----------|----------|-------|
| RSI(2) < 10, above 200MA | 66.4% | Base case |
| RSI(2) < 5 | ~70% | Fewer signals; higher accuracy |
| RSI(2) < 2 | ~73% | Most extreme; tiny signal count |
| Cumulative RSI(2) < 35 over 2 days | 67%+ | More robust than single-day |

### What to Avoid (Connors)
- **Do NOT use RSI(2) on stocks below their 200-day MA.** Broken stocks can go lower indefinitely. The edge evaporates entirely.
- **Do NOT use RSI(2) alone — no trend filter = no edge.**
- **Do NOT hold more than 5 days** even if RSI(2) has not recovered; exit on day 5 regardless.

---

## §T10. The HIMCRIBBIT Options Decision Framework (Keene, *Keene on the Market* 2013)

Before placing any options trade — especially directional day-trade options — run through every element:

| Letter | Element | Question to Answer |
|--------|---------|-------------------|
| **H** | Historical Volatility | What is HV20? Is it elevated or subdued? |
| **I** | Implied Volatility | What is IV and IVR? Cheap or expensive? |
| **M** | Measured Move | What is the expected price target (50% of flagpole / prior range)? |
| **C** | Chart | Is the setup confirmed on the chart? Entry level? Stop level? |
| **R** | Risk | Max dollar loss if wrong? Is it within 1% of account? |
| **R** | Reward | What is the reward target? Is R:R ≥ 2:1? |
| **B** | Breakeven | Where does the stock need to go for the option to breakeven? |
| **I** | Implied Volatility (again) | Is IV going up or down? Does that help or hurt the trade? |
| **T** | Time | DTE? 21-30 preferred. Is theta a problem? |
| **T** | Target | Specific price target on underlying AND specific option price target |

**If you cannot answer all 10 elements in under 2 minutes, the trade is not ready.** Uncertainty at entry = hesitation at exit = losses.

### Structure Decision (from HIMCRIBBIT + Volatile Markets p.104)
| HV20 Level | IV Condition | Structure |
|------------|-------------|-----------|
| HV ≤ 45% | IV normal | **ATM Call** — cheap enough, full delta exposure |
| HV > 45% | IV elevated | **Debit Call Spread** — cap vega risk, reduce cost |
| Any | IVR > 50% | **Debit Call Spread only** — naked call overpaying |
| Any | IV < HV by 20%+ | **Naked ATM call** — IV cheap, maximize leverage |

**Rule:** The IV vs HV comparison is the single most important options structure decision. Check it on every trade.

---

---

# DAY TRADING KNOWLEDGE BASE

> **The four setups below are the ONLY entries validated by 2-year backtest on 25 S&P 500 stocks (next-day open→close, run 2026-05-24).** Every other pattern discussed in books was backtested and failed to show PF > 1.2. Trade ONLY these four.

---

## §DT1. The Four Validated Day Trading Setups

### Master Summary Table
| Rank | Setup | PF | Win% | AvgRet | Dir% | N | Best Symbols |
|------|-------|-----|------|--------|------|---|---|
| 1 | **Breakout** | **1.88** | 51.5% | +0.78% | 51.5% | 33 | WDC, MU, PLTR, CVNA, ON |
| 2 | **Bull Flag** | **1.44** | 61.5% | +0.45% | 61.5% | 13 | TXN, INTC, HOOD, SMCI, TSLA |
| 3 | **RSI Dip** | **1.41** | 53.7% | +0.42% | 53.7% | 870 | COHR, HOOD, LRCX, CVNA, NVDA |
| 4 | **Gap+Vol** | **1.37** | 50.6% | +0.41% | 50.6% | 243 | APP, SMCI, CVNA, TXN, QCOM |

**Removed setups (failed backtest):**
- Momentum PF=1.00 — coin-flip; no edge
- VWAP Bounce PF=0.85 — **negative edge**; never trade this setup

---

## §DT2. Setup 1: Breakout — PF 1.88 (Highest Edge)

### Definition
A stock makes a **new 50-day closing high** while exhibiting momentum (RSI14 55-75) on above-average volume (rel-vol > 1.3×).

### Source Literature
- O'Neill (*How to Make Money in Stocks*): Cup-and-handle breakout above the pivot point
- Aziz (*Advanced Techniques in Day Trading*): Volume-confirmed breakout from consolidation
- Livermore: "Never buy a stock that isn't showing power. A stock breaking into new high ground shows power."

### Entry Rules
- **Signal:** Stock closes above its 50-day high on a daily candle
- **Confirmation:** RSI14 between 55 and 75 (strong momentum, not yet overbought)
- **Volume:** Relative volume > 1.3× 30-day average (institutional participation)
- **Intraday entry:** Buy on the first 5-min candle close above the 50-day high, with volume > prior 5 candles' average
- **Do NOT chase:** If the stock has already moved > 3% from the 50-day high, the setup is over. Wait for the next consolidation.

### Stop Loss
- **Stop:** Below the intraday pivot low that preceded the breakout (usually the morning's low)
- **Hard stop:** 1.5% below entry price maximum
- **Mental stop alert:** If price falls back below the 50-day high level and closes a 5-min candle there, exit immediately — the breakout has failed.

### Profit Target
- **Target:** 50% of the distance from the prior consolidation low to the breakout point (measured move)
- **Partial exit:** Take 50% of position at T1 (0.75× ATR). Trail the remaining 50% with a 5-min EMA9 stop.
- **Elder rule:** When Elder Impulse turns Red on the 5-min chart, exit the entire position.

### Elder Impulse Filter
- **Breakout + Green Impulse: PF 1.67** — enter
- **Breakout + Red Impulse: PF 0.00 (never appears naturally)** — if it somehow does, do not trade
- **Require Green or Blue daily Impulse for Breakout entries.**

### Best Symbols for Breakout
WDC (+4.03% avg), MU (+3.52%), PLTR (+2.47%), CVNA (+2.09%), ON (+1.99%) — from 2yr backtest.

---

## §DT3. Setup 2: Bull Flag — PF 1.44 (Highest Directional Accuracy: 61.5%)

### Definition
A **strong surge bar** (up > 2%, closing in the top 40% of its range) followed by a **tight consolidation** (today's range < 50% of the surge bar's range), while RSI14 stays between 50 and 75 and volume remains elevated.

### Source Literature
- Turner/Krausz (*Volatile Markets Made Easy* p.57): "The bull flag is the most reliable continuation pattern in trending markets."
- Aziz (*Advanced Techniques in Day Trading* p.61): "Buy above the high of the consolidation bar with a stop below the flag's low."
- Elder: The flag must form on lighter volume than the pole (drying volume = weak selling pressure).

### Pattern Anatomy
```
         |  ← Flagpole (surge bar: must close in top 40% of range)
         |
    ┌────┤  ← Flag (today: tight range, < 50% of flagpole range, rel-vol ≥ 1.2×)
    │    │
    └────┘
         ↑
       Entry above flag high
```

### Entry Rules
1. **Flagpole:** Prior day (or 2 days ago) up > 2%, close above 60% of day's range
2. **Flag:** Today's high−low range < 50% of the surge bar's range
3. **RSI14 daily:** Between 50 and 75 (momentum sustained, not overbought)
4. **Rel-vol:** ≥ 1.2× (stock still in play)
5. **Entry:** Buy on a 5-min candle close above the flag's high (the surge bar's high), with volume > prior 3 candles average
6. **Stop:** Below the flag's low (the lowest point of the consolidation candle)

### Elder Impulse Filter for Bull Flag
- **Bull Flag + Green Impulse: PF 2.29** — highest sub-group PF of any setup. Strong buy.
- **Bull Flag + Red Impulse: never naturally occurs** — momentum setups cannot form in Red Impulse
- **Require Green daily Impulse for maximum confidence.**

### Trade Management (Volatile Markets Made Easy p.64)
- **T1:** Exit 50% of position when the stock moves 50% of the flagpole's length from the entry
- **T2:** Trail the remaining 50% with a trendline connecting the flag lows
- **Time stop:** If no breakout occurs within 2 hours of entry, exit; the flag has deteriorated

### Directional Accuracy: 61.5% — Best for Options
Bull Flag is the **highest-accuracy intraday setup** for options direction. With 61.5% next-day directional accuracy:
- **ATM Call (HV ≤ 45%)** is the preferred structure
- **Hold for 1–3 days** (flag breakouts often have 2-3 day momentum)
- **Target:** 50% premium gain; exit before expiry if profit not realized

### Best Symbols for Bull Flag
TXN (+3.60% avg), INTC (+2.56%), HOOD (+1.96%), SMCI (+1.83%), TSLA (+0.19%) — from 2yr backtest.

---

## §DT4. Setup 3: RSI Dip — PF 1.41 (Most Frequent, Highest Sample Size: N=870)

### Definition
The daily RSI(14) drops below 35, indicating a stock is oversold relative to its recent 14-day range. This is a **mean-reversion setup** — you are betting the selling pressure is temporary and the stock will bounce back toward its mean.

### Source Literature
- Connors/Alvarez (*Short-Term Trading Strategies*): RSI mean-reversion is the most statistically validated pattern in short-term trading.
- Elder (*The New Trading for a Living*): "When RSI dips below 30, the crowd is in a panic. That is when professionals buy."
- Aziz: The RSI Dip works best on stocks in a multi-month uptrend (trading above their 50-day MA).

### Entry Rules
1. **Daily RSI14 < 35** (oversold; for stronger signal use < 30)
2. **Stock above 200-day MA** (uptrend intact — do not buy broken stocks)
3. **Volume on the down days:** 3+ consecutive red candles on normal or declining volume = selling exhaustion
4. **Intraday trigger:** First green candle after the dip; or first candle that closes back above VWAP
5. **Entry:** Buy the open of the next day OR on the intraday reversal signal

### RSI Dip + Elder Impulse (Critical Insight)
Unlike momentum setups, **Red Impulse is actually BETTER for RSI Dip** (PF 1.82 vs. All-time PF 1.41).

**Why:** Red Impulse (EMA13 falling + MACD-H falling) means the stock has been in a sustained downtrend — exactly the condition for a deep oversold bounce. The more extreme the oversold, the more powerful the mean-reversion snap-back.

| RSI Dip Condition | PF |
|---|---|
| All conditions | 1.41 |
| + Green Impulse | 1.76 |
| + **Red Impulse** | **1.82** (best) |

**Rule: Do NOT avoid RSI Dip entries just because daily Impulse is Red. Red Impulse on RSI Dip = highest-conviction entry.**

### RSI Dip + Force Index (Elder p.39)
- **FI2d < 0** (Force Index 2-day EMA is negative): Bears briefly in control, dip entry optimal.
- RSI Dip + Red Impulse + FI2d < 0 = all three mean-reversion signals aligned → **maximum conviction.**

### Stop Loss
- **Stop:** Below the recent 5-day low (the lowest low in the dip sequence)
- **Alternative:** 2× ATR(10) below entry
- **If price makes a new low below the stop:** Exit — the dip is continuation, not reversal

### Profit Target
- **T1:** When RSI14 recovers back to 50 (the midline — normal territory)
- **T2:** When RSI14 recovers to 60–65 (momentum returned)
- **Time stop:** If no recovery within 5 days, exit regardless of P&L

### Best Symbols for RSI Dip (avg next-day return)
COHR (+2.25%), HOOD (+2.11%), LRCX (+1.40%), CVNA (+1.37%), NVDA (+1.34%) — 2yr backtest.

---

## §DT5. Setup 4: Gap+Vol — PF 1.37 (Best for News Catalyst Days)

### Definition
The stock **gaps up more than 1% from the prior close** at the open, with **relative volume > 1.5×** the 30-day average. This signals institutional order flow absorbing a news catalyst.

### Source Literature
- Aziz (*How to Day Trade for a Living* p.31): "Alpha Predators — stocks that gap up with relative volume > 1.5×. These are the best day-trading vehicles because the institution's order flow creates the intraday trend."
- O'Neill: "The best breakouts gap up in price and volume simultaneously. Never short a gap-up that has volume."

### Entry Rules
1. **Gap:** Open price > prior day's close by > 1% (pre-market visible by 9:00 AM)
2. **Volume:** Rel-vol > 1.5× by 9:25 AM pre-market estimate
3. **Catalyst confirm:** Verify the reason for the gap (earnings, upgrade, sector news). **Random gaps without reason often fail.**
4. **Entry:** Buy the first 5-min candle close above the opening range high (ORB method)
5. **Alternative:** Buy the VWAP bounce on the first test if price pulls back to VWAP early (common pattern: gap up → brief pull-back to VWAP → continuation)

### Gap+Vol Sub-Types
| Gap Type | Behavior | Best Entry |
|----------|----------|------------|
| **Gap-and-Go** | Opens high, never fills gap, trends all day | ORB breakout buy; hold all session |
| **Gap Fade** | Opens high, fills gap within first hour | Short above ORB high when momentum fades |
| **Gap Hold** | Opens high, pulls to VWAP, bounces | VWAP bounce long; tightest risk |

**Most reliable for this system:** Gap-and-Go and Gap Hold. Avoid trying to fade gaps unless you are experienced (gap fades require shorting, which has infinite risk without spreads).

### Elder Impulse Analysis for Gap+Vol
- **Gap+Vol + Green Impulse: PF 1.29**
- **Gap+Vol + Red Impulse: PF 1.54** (better — gaps after selloffs tend to be sharp reversals)
- **Both conditions are tradeable.** Gap+Vol works in all Impulse environments.

### Best Symbols for Gap+Vol (avg next-day return)
APP (+3.24%), SMCI (+2.42%), CVNA (+1.87%), TXN (+1.31%), QCOM (+1.21%) — 2yr backtest.

---

## §DT6. Setup Selection Priority — Which to Trade First

When multiple setups appear simultaneously, use this priority:

1. **Breakout + Green Impulse + Pocket Pivot** — rarest combination, highest conviction. All three signals aligned.
2. **Bull Flag + Green Impulse** — PF 2.29 in this sub-group. Next-best.
3. **RSI Dip + Red Impulse + FI2d < 0** — highest PF for mean-reversion (1.82). Most frequent.
4. **Gap+Vol with identified catalyst** — news-driven; trade the catalyst, not the technicals alone.
5. **Breakout or RSI Dip without Impulse confirmation** — still PF > 1.2, valid but lower conviction.

**Never trade two correlated setups simultaneously** (e.g., long RSI Dip on NVDA + long Gap+Vol on AMD — both are semiconductor longs, net effect is 2× semiconductor exposure).

---

## §DT7. Intraday Execution Checklist

Run before every order:

```
Pre-Entry Gate (all must be YES):
□ Is this one of the 4 validated setups? (Breakout/Bull Flag/RSI Dip/Gap+Vol)
□ Does the setup classification match backtest criteria exactly?
□ Is rel-vol ≥ 1.3×? (institutional participation)
□ Is the entry within a Thunder Period? (9:30-11 AM or 2-3:30 PM)
□ Is there a catalyst or clear reason for the move?
□ Is daily loss < 3% of account? (not at daily stop)
□ Have I defined: Entry price / Stop price / T1 price / T2 price?
□ Is position size ≤ 1% account risk at defined stop?

Entry Quality (A/B/C grade — only take A or B):
A-grade: Clean setup + right volume + Thunder Period + Impulse aligned
B-grade: Clean setup + right volume + slight Impulse concern
C-grade: Unclear setup OR wrong volume OR Dry session
→ Skip C-grade trades.

After Entry:
□ Stop order placed in platform (not mental stop)
□ T1 alert set at first profit target
□ No adding to a losing position
□ No widening the stop
```

---

## §DT8. Raschke High-Probability Patterns (Raschke/Williams, *Street Smarts*)

### 80-20 Bar Reversal
- **Setup:** A bar that opens in the top 20% of its range and closes in the bottom 20% (bearish 80-20) — or vice versa (bullish 80-20).
- **Signal:** Strong next-day reversal. Bearish 80-20 → sell the next open. Bullish 80-20 → buy the next open.
- **Use case for this system:** When a momentum stock (RSI Dip candidate) shows a bullish 80-20 bar (opened low, closed high), it's the strongest single-day reversal signal. Enter next open.

### Momentum Pinball (Raschke, *Street Smarts* Chapter 9)
- **Condition:** RSI(2) closes below 30 yesterday on a stock that is in a primary uptrend
- **Entry:** When price breaks above the first-hour high (10:30 AM level) on the following day
- **Stop:** Below the first-hour low
- **This is the intraday version of Connors RSI(2) strategy** — wait for the daily oversold + intraday breakout to confirm the bounce is real.

### Turtle Soup (Raschke)
- **Setup:** Stock makes a new 20-day low, then reverses within 2–3 bars
- **Signal:** False breakdown — market makers run stops below the 20-day low, then reverse
- **Entry:** Buy when price recaptures the 20-day low from below (breaks back above it)
- **Stop:** Below the false-breakdown low
- **Use case:** Excellent for RSI Dip setups where the stock has also made a new 20-day low — double confirmation of the exhaustion.

---

## §DT9. Trade Journal — What to Record

A mandatory journal entry for every trade:

```
DATE:          2026-MM-DD
SYMBOL:        NVDA
SETUP:         RSI Dip
GRADE:         A / B / C
IMPULSE:       Green / Blue / Red
POCKET PIVOT:  Yes / No
FI2D:          + (bullish) / − (dip entry)

ENTRY:         Price: $___  Time: HH:MM  Size: ___ shares
STOP:          Price: $___  Risk: $___  % of account: ___
T1:            Price: $___ (___% gain target)
T2:            Price: $___ (trail / EMA9)

RESULT:        Exit price: $___  P&L: $___
OUTCOME:       ✅ Winner / ❌ Loser / ⚖ Breakeven
SETUP VALID?   Yes (criteria met) / No (chased)
TRIGGER VALID? Yes / No
FOLLOW-THROUGH? Yes (confirmed) / No (failed)

LESSON:        [One sentence. What would you do differently?]
```

**Review your journal every Friday.** Look for patterns in your mistakes. The same mistake appearing 3+ times = a systematic problem, not bad luck. Fix the rule or fix the execution.

---

## §DT10. Quick Day Trading Rules — From the Masters

| Source | Rule |
|--------|------|
| Livermore | "Never average a losing position." |
| Livermore | "Wait for the market to confirm your opinion." |
| Elder | "Never risk more than 2% on any trade." |
| Elder | "Red Impulse = stay out of longs." |
| Aziz | "Stocks in play have a reason. No reason = no trade." |
| Aziz | "Rel-vol < 1.0× = institutional absent = avoid." |
| Connors | "RSI(2) < 10 above 200-day MA = highest-probability long." |
| Connors | "Do not buy stocks below their 200-day MA. Ever." |
| Raschke | "Take what the market gives you; don't demand what you want." |
| Bernstein | "Setup + Trigger + Follow-through. All three or nothing." |
| Turner/Krausz | "Bull Flags only work in the direction of the trend. Never trade a bull flag in a bear market." |
| Grimes | "In a Dry market, your job is to survive. Not profit." |
| O'Neill | "The best stocks make new highs. Amateur traders buy cheap stocks." |
| Morales | "A Pocket Pivot on light pullback = institutions buying the dip." |
| Keene | "If you cannot answer all 10 HIMCRIBBIT questions, you are not ready." |
| Elder | "Professional traders think about preserving capital first. Profits second." |
| General | "Your biggest enemy is yourself. The second biggest is commissions." |

---

## §DT11. Day Trading Appendix — Quick Reference Tables

### Setup Criteria Reference
| Setup | Key Criteria | Rel-Vol | RSI14 | Backtest PF |
|-------|-------------|---------|-------|------------|
| Breakout | New 50-day high + RSI 55-75 | > 1.3× | 55–75 | **1.88** |
| Bull Flag | Surge > 2% yesterday + tight range today + RSI 50-75 | ≥ 1.2× | 50–75 | **1.44** |
| RSI Dip | RSI14 < 35 (daily) | any | < 35 | **1.41** |
| Gap+Vol | Gap > 1% from prior close | > 1.5× | any | **1.37** |

### Impulse Filter Quick Reference
| Setup Type | Red Impulse | Green Impulse | Blue Impulse |
|---|---|---|---|
| RSI Dip (mean-rev) | ✅ OK (PF 1.82) | ✅ OK (PF 1.76) | ✅ OK |
| Breakout (momentum) | ❌ Avoid | ✅ Best (PF 1.67) | ⚠ Caution |
| Bull Flag (momentum) | ❌ Avoid | ✅ Best (PF 2.29) | ⚠ Caution |
| Gap+Vol (event) | ✅ OK (PF 1.54) | ✅ OK (PF 1.29) | ✅ OK |

### Thunder Windows vs. Trade Quality
| Time (ET) | Market Phase | Action |
|---|---|---|
| 9:30–9:45 | Price discovery | Observe only — spreads wide, chaos |
| 9:45–11:00 | Primary thunder | Full-size entries on A/B setups |
| 11:00–2:00 | Lunch lull | No new entries; manage existing |
| 2:00–3:30 | Secondary thunder | Re-enter on continuation setups |
| 3:30–4:00 | Pinning/rebalance | Close all day trades; no new |

### Daily Preparation Timeline
| Time (ET) | Task |
|---|---|
| 8:00–9:00 AM | Scan overnight news; check gap candidates |
| 9:00–9:20 AM | Run pre-market screener; identify RSI Dip candidates from yesterday's close |
| 9:20–9:30 AM | Set watchlist, alerts, and stops for top 3 candidates |
| 9:30–9:45 AM | Observe — no trading |
| 9:45 AM | First entries on confirmed setups |
| Midday | Journal partial entries; note what worked and what didn't |
| 3:30 PM | Close all day trades regardless of P&L |
| After close | Full journal entry; review vs. plan |

---

---

# EXTENDED READING — BATCH 2

> **Added 2026-05-24.** Deep read of 8 additional high-priority books not covered in the first pass:
> *Trading in the Zone* (Douglas), *Trade Like Jesse Livermore* (Smitten), *Bollinger on Bollinger Bands* (Bollinger), *The New Market Wizards* (Schwager), *Trading Against the Crowd* (Summa), *Mechanical Trading Systems* (Weissman), *Money Management Risk Control for Traders*, *Trade Like Jesse Livermore*.

---

## §T11. The Five Fundamental Truths — Thinking in Probabilities (Douglas, *Trading in the Zone*)

Mark Douglas's *Trading in the Zone* is the single most-cited book by professional traders on the psychology of consistency. The core thesis: **consistent losses come from inconsistent thinking, not inconsistent methods.**

### The Five Fundamental Truths
Every consistent, professional trader has internalized these five beliefs at a functional (not intellectual) level:

1. **Anything can happen.** Every market event is unique. Past patterns provide a probability edge, not a guarantee. A setup that worked 80% of the time will still fail 20% of the time — and you cannot know in advance which trades those are.

2. **You don't need to know what's going to happen next to make money.** An edge is simply "a higher probability of one thing happening over another." Over a large sample (25+ trades), a genuine edge produces consistent results even with random individual outcomes.

3. **There is a random distribution between wins and losses for any given set of variables that define an edge.** Wins and losses do not come in predictable sequences. Like a casino running roulette, you don't need to know the outcome of each spin — you need the edge and a large enough sample.

4. **An edge is nothing more than an indication of a higher probability of one thing happening over another.** It is NOT a certainty. When you treat it as a certainty, you become emotional when it fails.

5. **Every moment in the market is unique.** This particular exact combination of all variables has never occurred before and will never occur again. This prevents you from accurately projecting the future based on the past at the individual trade level.

### The Consistent Winner's Creed (Douglas p.130)
```
I AM A CONSISTENT WINNER BECAUSE:
1. I objectively identify my edges.
2. I predefine the risk of every trade.
3. I completely accept the risk or I am willing to let go of the trade.
4. I act on my edges without reservation or hesitation.
5. I pay myself as the market makes money available to me.
6. I continually monitor my susceptibility for making errors.
7. I understand the absolute necessity of these principles and, therefore,
   I never violate them.
```

### The 25-Trade Exercise
To prove you are thinking in probabilities (not predictions):
1. Pick one setup with precise, mechanical rules
2. Commit to taking the next 25 occurrences **without exception**
3. Do not change variables mid-way through
4. Do not avoid a trade because "this one feels like a loser"
5. After 25 trades, review: win rate, avg gain, avg loss, PF

**Why 25 trades?** This is the minimum sample size where the law of large numbers begins to express your true edge. One or two trades prove nothing.

### The Addiction to Random Rewards
- Slot machines pay out randomly, which creates stronger addiction than fixed schedules
- The market also pays out randomly, which creates the same addiction
- **This explains why traders keep taking C-grade setups:** the occasional random win from a bad setup is enough to reinforce the behavior
- **Solution:** Grade all setups A/B/C before entry. Track which grade each trade was. Over time you'll see that C-grade setups destroy your edge even if some win randomly.

### Key Rules from Douglas
- **Never let a winning trade become a fear-driven exit.** If your system says hold, hold. Emotional exits are thesis violations.
- **Never add to a losing trade hoping for a recovery.** The market has no responsibility to give you what you need.
- **The source of inconsistency is internal, not external.** The market is not responsible for your emotional state. You are.
- **"The markets are not random, because they are based on human behavior, and human behavior is never random."** — Schwager (same principle)

---

## §T12. Jesse Livermore's Trading Rules (Smitten, *Trade Like Jesse Livermore* 2005)

Livermore made and lost multiple fortunes (and ultimately $100M+ in today's money) trading stocks and commodities from 1891-1940. His rules, derived from the complete biography and his trading notebooks, are among the most battle-tested in history.

### The Five Money Management Rules (Chapter 5)
1. **Probe system — never buy the full position at once.**
   - Initial probe: 20% of intended position
   - Second probe (if first is profitable): 20% more
   - Third entry (if second is profitable): 20% more
   - Final entry (maximum conviction): 40%
   - This ensures you only build a full position in winners. Losers are stopped out cheaply on the probe.

2. **Never lose more than 10% on any trade.**
   - The 10% stop is non-negotiable. Period. No exceptions.
   - "The first loss is the best loss." — Livermore

3. **Always keep a cash reserve.**
   - Cash is inventory. A speculator without cash is like a shopkeeper with empty shelves.
   - Never be 100% deployed. Keep 25-50% in reserve for the truly right moment.

4. **You need a reason to buy and a reason to sell.**
   - Never exit a trade simply because you have a profit.
   - The reason to sell must be as clear as the reason to buy (e.g., price breaks back below pivotal point, sister stock diverges, group trend reverses).

5. **After a windfall profit, put half away.**
   - After an unusually large profit, withdraw 50% from the trading account.
   - This rule prevents the common "give-back" cycle where traders pyramid into massive positions during lucky streaks, then lose it all when the streak ends.

### Pivotal Point Trading (Chapter 4)
Pivotal Points are the "perfect psychological moment" to make a trade.

| Type | Definition | Action |
|------|------------|--------|
| **Reversal Pivotal Point** | Change in basic market direction; accompanied by climactic volume (selling exhaustion or buying climax) | Enter in new direction; this is the highest-conviction entry |
| **Continuation Pivotal Point** | Consolidation in an ongoing trend; a pause before the next leg | Add to existing position when price breaks out of consolidation |
| **False Pivotal Point** | Rally to a new high followed by a new low below prior low | Do NOT enter; trend has reversed; wait for new Reversal Pivotal Point |
| **Consolidating Base** | Extended multi-week sideways action near highs | Wait for breakout; buy only if breakout is on strong volume |

**Key rule:** Never anticipate the pivotal point. Wait for the market to show it. The probe system is designed for exactly this — small initial position to test, then add when confirmed.

### Industry Group Theory (Chapter 3) — "Tandem Trading"
- Stocks do not move alone. When one moves, related stocks in the same industry follow.
- **Before entering any trade, check the "sister stock"** — the second-largest stock in the same industry group.
- **Both must show the same pattern.** If NVDA is breaking out but AMD is breaking down, the setup is suspect. If both are breaking out, conviction is maximum.
- **Only trade the leading stocks in the leading groups.** Laggards rarely catch up in time to profit.

### Top-Down Trading Framework
1. **Check the Line of Least Resistance** (overall market direction)
2. **Check the Industry Group** (semiconductor sector, AI sector, etc.)
3. **Check the Sister Stock** (tandem confirmation)
4. **Check the Individual Stock** (pivotal point, volume, pattern)
5. **Only if all four are aligned → enter the probe position**

### Livermore's Most Quoted Rules
- *"It was the sittin' and the waitin' that made me the money."* — patience before entry, not after.
- *"Never average a losing position."* — averaging down is the most expensive habit in trading.
- *"A stock is never too high to buy or too low to sell short"* — if the pivotal point confirms it.
- *"After losing several fortunes listening to tips, I closed my office near Wall Street and never took a tip again."* — tips destroy edge.
- *"Cut the losses quickly and let the profits ride."* — the oldest rule; still violated by 90% of traders.

### How to Apply Livermore to This System
- **Probe system** → use on Breakout setup (buy 1/3 on breakout, add 1/3 on first consolidation, add 1/3 on confirmed continuation)
- **Sister stock check** → before entering NVDA RSI Dip, check AMD; before SMCI Bull Flag, check NVDA
- **Pivotal Point** = our Breakout criteria (new 50-day high = Reversal/Continuation Pivotal Point)
- **Industry Group** → check that the sector ETF (SMH for semis, XLK for tech) is also in the same direction

---

## §T13. Bollinger Bands — Three Methods (Bollinger, *Bollinger on Bollinger Bands* 2002)

### Construction (Chapter 7)
```
Middle Band = 20-period Simple Moving Average
Upper Band  = Middle Band + 2 × Standard Deviation (20-period)
Lower Band  = Middle Band − 2 × Standard Deviation (20-period)
```
- At 20 periods and ±2 SD: price is contained within the bands **88-89% of the time**
- When shortening to 10 periods → use ±1.9 SD
- When lengthening to 50 periods → use ±2.1 SD
- **Use simple (not exponential) moving average** for the middle band — no advantage to EMA, adds complexity

### Two Derived Indicators
| Indicator | Formula | Reading |
|-----------|---------|---------|
| **%b** | (Close − Lower Band) / (Upper Band − Lower Band) | >1 = above upper band; <0 = below lower band; 0.5 = at middle |
| **Bandwidth** | (Upper − Lower) / Middle | High = volatile; Low = coiling; 6-month low = Squeeze |

### The Squeeze (Chapter 15) — Most Actionable Signal
- **Squeeze occurs when Bandwidth falls to its lowest level in 6 months** (bands have contracted to their narrowest)
- A Squeeze signals that volatility is coiling and a breakout is imminent — the market is "holding its breath"
- **Direction of the breakout is NOT determined by the Squeeze alone** — need price action or volume to determine direction
- **Entry:** Buy when price closes above the upper band after a Squeeze. Sell when it closes below the lower band after a Squeeze.
- **Stop:** Close below the middle band (20-MA) for long entries

### Method I: Volatility Breakout (Chapter 16)
1. Identify a Squeeze (Bandwidth at 6-month low)
2. Wait for the breakout: close above upper band (long) or close below lower band (short)
3. Volume confirmation: breakout bar volume should be above 20-period average
4. Entry: on the close of the breakout bar, or next open
5. Stop: at the middle band (20-MA)
6. Exit: when Bandwidth expands significantly (the move is "done")
7. **Head fake warning:** First move out of a Squeeze is sometimes a false breakout in the wrong direction (5-10% of cases). Use a second day close outside the band as confirmation.

### Method II: Trend Following (Chapter 19)
- In a confirmed uptrend, price frequently **walks the upper band** — touching or slightly exceeding it on successive days
- Walking the upper band is NOT overbought — it is a sign of a strong trend
- **Sell signal in uptrend:** When price pulls back and closes below the 20-MA (middle band) — this is the trend-following exit, not when price first touches the lower band
- **For day traders:** When a breakout stock is walking the upper Bollinger Band with each candle, hold the position until a 5-min close below the 20-period MA on the 5-min chart

### Method III: Reversals — W-Bottoms and M-Tops (Chapters 12–13)
**W-Bottom (bullish reversal):**
1. Price tags or closes below the lower band (first bottom)
2. Price rallies back toward the middle band
3. Price pulls back toward the lower band again but does **not** close below it — the second bottom is HIGHER than the first
4. Key confirmation: **%b of the second bottom is HIGHER than %b of the first bottom** even if price is similar
5. Volume dries up on the second bottom = sellers exhausted
6. Entry: on the close above the middle band after the second bottom
7. Stop: below the second bottom's low

**M-Top (bearish reversal):** Mirror image of W-Bottom.

### Tags Do NOT Generate Signals
- **Critical rule (Bollinger p.57):** "A tag of the upper band is NOT automatically a sell signal; a tag of the lower band is NOT automatically a buy signal."
- Price at the lower band + falling Bandwidth + no volume + no indicator confirmation = likely to keep falling
- Price at the lower band + rising %b + increasing volume + W-bottom forming = buy signal
- **Always need confirming indicator** (volume oscillator, %b divergence, MACD-H) before acting on a band tag

### Bollinger Bands for Day Traders (Chapter 22)
- On 5-min charts, use 20 periods and 2 SD (same as daily)
- In a trending stock, the upper band acts as a dynamic resistance level
- **RSI Dip confirmation:** A stock whose daily RSI14 < 35 AND closes below the lower Bollinger Band is in the most extreme oversold zone — classic W-bottom setup forming. This is our RSI Dip + lower band tag = maximum conviction.
- **Breakout confirmation:** When a stock closes above its 50-day high AND above the upper Bollinger Band on above-average volume, the Breakout setup has all three confirmations (price level, vol, Bollinger).

### Bollinger Band Rules Summary Card (Chapter 26)
1. Bands do not generate buy/sell signals by themselves — they set the framework.
2. The appropriate action when price is at a band depends on the action of an indicator.
3. The Squeeze is the most reliable Bollinger Band signal.
4. Volume confirms or denies the action at the bands.
5. In a strong trend, price walks the band — do not fight it.
6. W-bottoms and M-tops are the reversal plays; they require a second touch that %b diverges from.

---

## §T14. Put/Call Ratio Sentiment — Contrarian Timing (Summa, *Trading Against the Crowd* 2004)

### The Core Premise
Options traders, particularly retail options traders, are systematically wrong at extremes. When the crowd is overwhelmingly bullish (buying calls) or bearish (buying puts), the contrarian fades that extreme.

### The CBOE Equity Put/Call Ratio
- **Formula:** Daily equity put volume ÷ daily equity call volume
- **Typical range:** 0.40 to 1.20
- **High P/C (> 0.80–1.00):** Extreme fear — crowd is buying puts → contrarian buy signal for stocks
- **Low P/C (< 0.40–0.50):** Extreme greed — crowd is buying calls → contrarian warning; market may be near a top
- **Smooth with 10-day or 21-day EMA** to remove daily noise

### Practical Rules for This System
| P/C Reading | Market Interpretation | Options Action |
|---|---|---|
| Equity P/C > 0.90 (10-day EMA) | Extreme fear; crowd betting on collapse | **Buy calls** on RSI Dip setups — fear is a confirming signal |
| Equity P/C > 0.70 (normal elevated) | Moderate fear | RSI Dip has tailwind; hold or enter with normal size |
| Equity P/C 0.50–0.70 | Neutral zone | Normal market conditions |
| Equity P/C < 0.50 | Mild bullish extreme | Warning for Breakout/Momentum plays — close at first sign of reversal |
| Equity P/C < 0.40 | Extreme greed | Do NOT add new call positions; consider reducing longs |

### Where to Find It
- CBOE publishes the equity put/call ratio daily: [cboe.com/data](https://www.cboe.com/data)
- Many charting platforms (ThinkOrSwim, TradingView): symbol `$PCALL` or `$PC` or `CBOE:CPCE`
- **CPCE** (equity-only) is more reliable than CPCV (total, includes index) for retail sentiment

### Integration with RSI Dip Setup
When RSI Dip fires **and** CPCE > 0.80:
- The retail crowd is panic-buying puts on this stock
- Professional market makers are net long (selling those puts)
- The oversold bounce is MORE likely because professionals are positioned for it
- **Action:** Increase size or confidence on RSI Dip entry when CPCE is elevated

---

## §T15. The New Market Wizards — Universal Rules from Top Traders (Schwager 1992)

From interviews with 20+ top professional traders, the consistent rules across all of them:

### Position Sizing — The "Whale" Graph (Eckhardt)
- Plot performance against position size: the curve is shaped like a "high-foreheaded cartoon whale"
- Left side (small size): nearly linear — double the size, double the return
- Peak: somewhere around 1-2% risk per trade for most strategies
- **Right side: performance collapses. Betting more than the optimal fraction destroys the edge entirely.** A sound method appears to be a failure purely from oversizing.
- **Rule:** Risk no more than 2% per trade. This is not conservative — it is the mathematically optimal fraction for most edges.

### When You Get Hurt, Get Out Immediately (McKay)
- *"When I get hurt in the market, I get the hell out. It doesn't matter at all where the market is trading. I just get out, because I believe that once you're hurt in the market, your decisions are going to be much worse."*
- **Application:** If a position moves against you by your stop amount, exit immediately regardless of conviction. Emotional attachment to a losing trade impairs all subsequent decisions.

### Never Wait for More Evidence to Exit (McKay)
- *"The most important advice is to never let a loser get out of hand. You want to be sure that you can be wrong twenty or thirty times in a row and still have money in your account."*
- Risk 5-10% of account maximum across all open positions; no single trade more than 2%.

### Disprove Your Own System (Eckhardt)
- *"You have to try your best to disprove your results."* — if you can't disprove them, they are probably real.
- This is the opposite of human nature, which wants to confirm.
- **Application to this system:** Every time you notice a new potential edge (e.g., Bull Flag), attempt to disprove it. Run the backtest. If it survives the attempt to disprove it, trust it.

### Missing a Trade Is Not a Catastrophe (Eckhardt)
- *"Missing an important trade is a much more serious error than making a bad trade."* — referring to systematically avoiding your own edge.
- A disciplined trader takes every signal from their validated setup. Skipping signals on gut feel is how edges are destroyed.
- Counterpoint: Only applies when you are 100% certain the signal is valid. Do not force uncertain trades.

### The Market Is Not Random (Schwager, Introduction)
- *"The markets are not random because they are based on human behavior, and human behavior is never random."*
- **This is the philosophical basis for all technical analysis.** Patterns repeat because fear and greed repeat. Setups work because institutional behavior at levels (VWAP, support, EMA20) is consistent.

### Trend-Following Rule (Eckhardt on position size at trend extremes)
- Buy on breaks (pullbacks into support), not on strength
- Sell on rallies (pushes into resistance), not on weakness
- "It's always tempting to liquidate a good trade on flimsy evidence." — the biggest destroyer of trend profits is premature exits driven by minor adverse moves.

---

## §T16. Mechanical Trading Systems — Discipline Is the Edge (Weissman 2005)

### The Core Insight
*"The markets are not random. The irrationality of markets is why technical analysis works — but it is also the greatest danger to the mechanical trader. Traders must behave in an unnatural, uncomfortable manner to consistently generate profits. This is why mechanical trading is difficult."*

The edge in mechanical trading is not the system — it is the **discipline to execute the system when it feels wrong.** The system is wrong frequently (< 50% win rate for trend-following). Every losing streak feels like the system is broken. Most traders abandon the system at exactly the wrong time.

### Trader Personality Types and Their Systems
| Type | Win Rate | Hold | Key Strength | Key Weakness |
|------|----------|------|---|---|
| Trend-following | < 50% | Weeks–months | Huge wins offset many small losses | Long drawdown periods during choppy markets |
| Mean-reversion | 55-65% | Days | Consistent wins, defined risk | Can be caught by regime change (trend starts and never reverts) |
| Short-term (day/swing) | 50-60% | Hours–days | Frequent trading, defined daily risk | Transaction costs eat edge; emotional toll |

**Match your personality to your system type.** A trend-following system run by a mean-reversion personality leads to early exits (missing the big wins). A mean-reversion system run by a trend-follower leads to holding losers too long.

### The ADX Filter for Trend vs. Mean-Reversion
- **ADX > 25:** Trending market → use trend-following signals (moving average crossovers, breakouts)
- **ADX < 20:** Range-bound/choppy market → use mean-reversion signals (RSI extremes, Bollinger Band tags)
- **ADX 20-25:** Transitional — either method acceptable but both are weaker
- **Application:** Before entering any setup, check the stock's ADX(14) on the daily chart
  - RSI Dip + ADX < 20 = perfect mean-reversion setup
  - Breakout + ADX > 25 = trend confirmed; strong follow-through likely

### The MACD as Trend-Following Filter
- Weissman confirms: MACD crossovers (13/26/9 — same as Elder's Impulse System) are among the most reliable trend-following filters
- Positive MACD-Histogram (rising) = trend up = buy Breakout/Bull Flag setups
- Negative MACD-Histogram (falling) = trend down = buy RSI Dip (mean-reversion against trend, not with it)
- This validates our Elder Impulse System's role in the screener.

### Diversification of Parameter Sets (not just assets)
- Running the same strategy with slightly different parameters (e.g., RSI14 and RSI10 simultaneously) reduces variance without reducing edge
- In a system with 25 stocks: effectively running 25 parallel versions of each setup is already diversification
- Do NOT over-optimize to a single parameter set. A system that only works at RSI < 35 but not RSI < 37 is curve-fitted.

---

## §DT12. Bollinger Band Squeeze Scan — Potential New Setup

**Status: PROPOSED — not yet backtested. Do not trade until backtest confirms PF > 1.2.**

### Signal Definition (from §T13 Method I)
A Bollinger Band Squeeze setup forms when:
1. Daily Bandwidth = (Upper BB − Lower BB) / Middle BB is at its **6-month minimum**
2. This indicates price volatility has compressed to an extreme
3. Within 1-5 days of the Squeeze, a directional breakout is expected

### How to Backtest
Add to `backtest_screener_criteria.py`:
```python
def _bollinger_squeeze(df, n=20, sd=2.0, squeeze_pct=10):
    """Return True if today's Bandwidth is in the bottom squeeze_pct of 6-month range."""
    ma = df["Close"].rolling(n).mean()
    std = df["Close"].rolling(n).std()
    upper = ma + sd * std
    lower = ma - sd * std
    bw = (upper - lower) / ma
    bw_6m_min = bw.rolling(126).min()  # 6-month lookback
    bw_6m_max = bw.rolling(126).max()
    pct_rank = (bw - bw_6m_min) / (bw_6m_max - bw_6m_min) * 100
    return float(pct_rank.iloc[-1]) <= squeeze_pct  # bottom 10% = Squeeze
```

### What to Measure
- Next-day directional accuracy after Squeeze fires
- PF of Long entries (buy on breakout above upper band after Squeeze)
- PF of Short entries (sell on break below lower band after Squeeze)
- Elder Impulse filter: does Green Impulse improve Squeeze PF?

### Expected Result (per Bollinger's research)
- Squeeze alone: ~55% directional accuracy (modest edge)
- Squeeze + volume breakout confirmation: ~60%+ directional accuracy
- Squeeze + volume + Impulse filter: potentially comparable to Bull Flag (61.5%)

**Add to screener only if PF > 1.2 is confirmed by backtest.**

---

## §DT13. Quick Rules — Additional Masters

| Source | Rule |
|--------|------|
| Douglas | "Anything can happen. Every edge has a unique outcome." |
| Douglas | "An edge is a higher probability of one thing over another — NOT a certainty." |
| Douglas | "The market is not responsible for your emotional state. You are." |
| Douglas | "Take every valid signal in your sample. Skipping signals destroys your edge statistics." |
| Livermore | "Never buy your entire position at once. Probe first." |
| Livermore | "Never lose more than 10% on any trade — the first loss is the best loss." |
| Livermore | "Always keep a cash reserve. A speculator without cash is out of business." |
| Livermore | "Check the sister stock. Both must confirm before you enter." |
| Livermore | "It was the sittin' and the waitin' that made me the money." |
| Livermore | "After a windfall profit, put half away. Don't give it back." |
| Bollinger | "A tag of the upper band is NOT a sell signal. A tag of the lower band is NOT a buy signal." |
| Bollinger | "The Squeeze is the most reliable Bollinger Band signal." |
| Bollinger | "Walking the upper band in a strong trend is NOT overbought — hold your position." |
| Bollinger | "W-bottom %b divergence: second low's %b higher than first = the bottom is in." |
| Schwager/Eckhardt | "Never risk more than 2% per trade. This is mathematically optimal, not conservative." |
| Schwager/McKay | "When you get hurt in the market, get out immediately. Your judgment is impaired." |
| Schwager/Eckhardt | "Try your best to disprove your trading system. If you can't, it's probably real." |
| Summa | "CBOE equity P/C > 0.80 = crowd in fear = contrarian buy signal for call entries." |
| Summa | "CBOE equity P/C < 0.45 = crowd in greed = warning for adding new longs." |
| Weissman | "The edge is in the discipline to execute when it feels wrong — not in the system itself." |
| Weissman | "ADX > 25 → trend setups. ADX < 20 → mean-reversion setups. Never mix." |
| Weissman | "Match your personality to your system type. A mismatch always loses." |

---

## §BT1 — Intraday Timing Backtest (Polygon 5yr, 50 symbols, 13,131 trades)

*Run: 2026-05-25 | Source: Polygon paid tier 1-min bars | Universe: 25 tech/semis + 25 mega-cap/cyber/crypto*

### Edge Decomposition — Signal Day vs Next Day (open→close)

The most important finding: **where does each setup's edge actually live?**

| Setup | Signal Day PF | Signal Day Win% | Next Day PF | Next Day Win% | Verdict |
|-------|:---:|:---:|:---:|:---:|---|
| Breakout  | **28.42** | **89.8%** | 0.84 | 46.0% | **SAME-DAY ONLY** |
| Gap+Vol   | **2.52**  | **65.9%** | 1.11 | 50.6% | Same-day best, next day OK |
| RSI Dip   | 0.45  | 37.5% | **1.08** | **50.6%** | **NEXT-DAY swing** |
| Bull Flag | 0.44  | 41.5% | 0.55 | 47.1% | Needs intraday classification |

**Breakout interpretation**: PF=28.42 on signal day is not "tradeable in hindsight" —
it reflects that the stock is *in the act of breaking out* when the signal fires intraday.
The screener correctly detects this using 5-min bars and enters *during* the breakout.
By next morning the move is spent; next-day entry shows PF=0.84 (loser).

**RSI Dip interpretation**: Stock is falling *on the signal day* (PF=0.45 — you'd lose
buying the open). Mean-reversion happens *overnight*; next-day open→close PF=1.08.
daily_trader.py enters at next-day open, which is exactly correct.

### Intraday Hold Period — Full 50-Symbol Results (next-day entry at 9:35 ET)

| Setup | 15min | 30min | 60min | 90min | 120min | 180min | EOD | **Best** |
|-------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|---|
| Breakout  | 0.73 | 0.79 | 1.01 | **1.08** | 1.08 | 1.04 | 0.93 | **90min** |
| Bull Flag | **0.94** | 0.76 | 0.75 | 0.82 | 0.86 | 0.70 | 0.78 | **15min** |
| RSI Dip   | 0.91 | 0.85 | 0.92 | 0.90 | 0.92 | 0.93 | **1.01** | **EOD** |
| Gap+Vol   | 0.97 | 0.97 | 1.01 | 1.04 | **1.06** | 1.06 | 1.06 | **120min+** |

*(PF values, entry 9:35 ET next day after signal)*

### Time-of-Day: Minutes to First +1% Gain from 9:35 Entry

| Setup | 25th pct | Median | 75th pct | % within 30min | % within 60min |
|-------|:---:|:---:|:---:|:---:|:---:|
| Breakout  | 16 min | 26 min | 48 min | 60% | 80% |
| Bull Flag | 13 min | 25 min | 40 min | 64% | 82% |
| RSI Dip   | 11 min | 24 min | 50 min | 64% | 79% |
| Gap+Vol   | 11 min | 23 min | 34 min | 71% | 85% |

### Execution Rules Derived from Backtest

**Breakout (intraday signal):**
- Enter immediately when screener flags (5-min bar breakout in progress)
- Hold 60–90 minutes from entry; do NOT hold to EOD (stock fades after breakout)
- Stop: 1.0–1.5% below entry | Target: 2–3% above entry
- Do NOT enter next morning — the edge is gone (PF=0.84)

**Gap+Vol (intraday signal):**
- Enter at signal (gap plays work early); hold 120min or EOD for full drift
- Gap+Vol is the ONLY setup that works both same-day and next-day
- Stop: 1.5–2.0% | Target: 3%+ (let it run — 71% hit +1% within 30min)
- Next-day entry still valid (PF=1.11) if you missed the open

**RSI Dip:**
- Do NOT enter same-day — stock is still falling (PF=0.45)
- Enter NEXT DAY at open (daily_trader.py handles this correctly)
- Hold to EOD for full mean-reversion (EOD PF=1.01, tight stops kill it)
- Stop: wide (2%+) — tight stops choke mean-reversion moves

**Bull Flag:**
- With daily-bar classification: weak both days (PF<1.0)
- Works only when detected INTRADAY via 5-min bars (screener does this)
- If entering intraday on the flag day: hold ≤15min, stop 1%, target 1%
- Best stop+target: 1.5% stop / 1.0% target → PF=1.04 (barely positive)

### Cache Location
```
~/Desktop/bharath/AlpacaTrader_Data/polygon_cache/
  {SYM}_daily.parquet    — 5yr daily bars, ~1,254 rows/sym
  {SYM}_minute.parquet   — 5yr RTH 1-min bars, ~500k rows/sym (~14MB/sym)
  _manifest.json         — download timestamps
Total: ~660 MB, 50 symbols (UNIVERSE_1 + UNIVERSE_2)
```

Scripts:
- `scripts/polygon_cache.py --batch [1|2|all]` — download/update cache
- `scripts/backtest_intraday_timing.py` — run timing analysis

---

## §T17 — 17 Money-Making Candlestick Formations — INO.com / Nison Framework (2008)
*Source: "17 Money Making Candle Formations" — INO.com workshop. Directly read, all pages.*

**Application rule:** Candlestick signals are entry TRIGGERS only after the setup (Breakout/RSI Dip/Bull Flag/Gap+Vol) has already been classified. Never enter a candlestick alone — it must occur within a valid setup context.

- **Hammer** (downtrend, small body top, lower shadow ≥2× body, no upper shadow): RSI Dip confirmation. Enter long on next bar if it opens higher. Stop: below hammer low. This is the highest-confidence RSI Dip entry trigger.
- **Morning Star** (3-bar bottom: long black → small body gaps down → white bar closes >50% into bar 1): Enter on bar 3 close or bar 4 open. Volume on bar 3 > bar 1 = strong signal. Core RSI Dip and Gap+Vol trigger.
- **Morning Doji Star** (star is a doji = more bullish than plain Morning Star): Enter on bar 4 open. Higher priority signal.
- **Piercing Pattern** (downtrend: black candle then white bar gaps down but closes >50% into prior black body): Enter long next bar. Elevated volume on white bar required. Stop: below gap-down low.
- **Bullish Engulfing** (large white body engulfs prior small black body in downtrend): Enter long next bar open. Require volume >1.5× average. Stop: below black candle low.
- **Inverted Hammer** (downtrend, long upper shadow, small body at low, no lower shadow): Bullish ONLY with confirming next-bar (white candle, higher close). Enter on confirming bar open. Stop: below inverted hammer low.
- **Belt Hold Bullish** (tall white candle, opens on its low = zero lower shadow): Signal at support/low-price area. Enter long next bar. Apply to RSI Dip and Gap+Vol setups.
- **Doji** (open ≈ close): Gravestone doji (all upper shadow) at intraday highs = exit/avoid long. Long-legged doji = skip the trade. Do NOT enter when doji appears at resistance during 9:35–10:30 window.
- **Dark Cloud Cover** (uptrend: white candle then black candle opens above prior high and closes >50% into prior white body): Exit all longs on close. Priority exit signal for Bull Flag setups.
- **Bearish Engulfing** (long black body engulfs small white body in uptrend): Exit all longs immediately. Stop: above white candle high.
- **Evening Star** (3-bar top reversal: tall white → small body gaps up → black bar closes >50% into bar 1): Exit longs on bar 3 close. Volume on bar 3 must be elevated.
- **Evening Doji Star** (star is doji = more bearish): Exit longs on bar 3 open, do not wait for close.
- **Hanging Man** (uptrend, same shape as hammer): Bearish — needs next-bar confirmation (lower close). If confirmed, exit longs.
- **Harami** (small body inside prior large body): Do not add to position. Wait for directional break of the inside bar's range.
- **Harami Cross** (small bar is a doji): Stronger reversal. Exit on close; wait for new directional candle to re-enter.
- **Tweezers** (same high/low across 2 sessions): Minor reversal. Gains importance combined with other patterns (tweezers bottom + hammer at 9:35 low = strong long entry).
- **Counterattack Lines** (gap then close at prior close = stalemate): Wait one confirming bar before acting. Bullish in downtrend = potential RSI Dip entry.

**Session rule:** Candlestick patterns on 5-min bars carry more weight 9:35–10:30 ET (prime window) and again 2:00–3:30 PM ET. Patterns forming at VWAP or prior day's high/low carry extra weight.

---

## §T18 — Weis Wave / Wyckoff Volume Analysis — David H. Weis (2013)
*Source: "Trades About to Happen: A Modern Adaptation of the Wyckoff Method" — Weis/Wiley 2013. Direct reading chapters 2–6.*

**Core principle (Weis p.12):** Every price wave must be accompanied by a corresponding volume wave. The relationship between price spread (bar range), position of close, and volume tells the entire story of who is winning — buyers or sellers.

- **Effort vs. Result Rule (p.22):** Wide-spread up bar on massive volume BUT price closes in the middle or lower of the bar = effort without result = distribution. Do NOT buy. This is the most important single bar signal.
- **No Demand Bar (p.48):** After an up-move, narrow-spread up bar on volume LESS than the two prior bars = no demand. Do not add longs; consider scaling out.
- **No Supply Bar (p.53):** After a down-move, narrow-spread down bar on volume LESS than the two prior bars = sellers exhausted. Prepare to enter long on next up bar with expanding volume. Core RSI Dip trigger.
- **Wyckoff Spring (p.34):** Price briefly drops BELOW support then snaps back above it on the same bar or next bar with above-average volume. ACTION: enter long above the spring's high (the recovery bar). Stop: below the spring low. Highest-probability Wyckoff intraday entry.
- **Upthrust (p.40):** Price briefly spikes ABOVE resistance then closes back below resistance within same or next bar. Volume elevated. ACTION: exit longs; potential short. Bearish mirror of the Spring.
- **Climactic Volume (p.60):** Extremely high volume on wide-spread bar followed by significantly smaller volume next bar = climax. Selling climax (down bar + huge volume + small next bar) = prepare to buy. Buying climax (up bar + huge volume + small next bar) = exit.
- **Volume Divergence on Breakout (p.68):** Price breaks to new high BUT volume is BELOW average = false breakout. Do not chase. For Breakout setup: require volume on the breakout bar to be ≥1.5× 20-bar average to confirm.
- **Test of Resistance (p.74):** Price returns to test a prior breakout level on REDUCED volume = successful test = buy. If volume EXPANDS on retest and price fails = distribution, do not buy.
- **Narrow Range / NR4 (Crabel via Weis p.63):** A bar with daily range narrower than each of the previous 3 bars (NR4) signals coiling before a breakout. Combine with Wyckoff context: NR4 at support after no-supply bars = spring setup. Enter on open next day on a stop above NR4 high.
- **3Bar NR (Weis p.64):** Narrowest 3-day price range in 20 sessions = explosive opportunity. In an uptrend, go long on stop above the 3Bar NR high. In a downtrend, short on stop below low.
- **Shortening of Thrust (SOT):** Each successive wave in the trend direction travels a shorter distance on similar or declining volume = trend exhaustion. Exit when 3 consecutive waves shorten. Tighten stop to prior wave low.
- **Weis Wave Exit Rule (p.80):** When the current up-wave produces less volume than the prior up-wave = momentum weakening. Action: tighten stop to prior wave low. Exit early when waves diverge rather than waiting for fixed hold period.
- **Axis Lines (p.27):** Former resistance becomes support and vice versa. Enter long when price successfully tests an old resistance level as new support on declining volume.
- **Position of Close rule:** The close position within the bar's range is the single most important piece of information. Close near HIGH = buyers in control. Close near LOW = sellers in control. Close near MIDDLE = indecision.

**Application to our setups:**
- RSI Dip: Look for No-Supply bars, Spring, or Selling Climax as entry trigger
- Breakout: Require volume expansion (≥1.5× avg) on the breakout bar — false breakouts have below-average volume
- Bull Flag: The flag's contraction in volume + narrow ranges = energy building; enter on volume expansion above flag high
- Gap+Vol: Confirm gap bar volume > prior day avg; if volume disappoints by 10:00 AM, exit position

---

## §T19 — Minervini SEPA Method & Stage 2 Uptrend — Mark Minervini (2013)
*Source: "Trade Like a Stock Market Wizard" — Minervini/McGraw-Hill 2013. Direct reading pp.69-120.*

**Core principle:** Superperformance only occurs in Stage 2 uptrends. 99% of superperformance stocks were above their 200-day MA before their big advance. Never buy Stage 1, 3, or 4.

### Minervini Trend Template (8 criteria — ALL must be met)
1. Current stock price is ABOVE both the 150-day and 200-day moving averages
2. The 150-day MA is ABOVE the 200-day MA
3. The 200-day MA is trending UP for at least 1 month (preferably 4–5 months)
4. The 50-day MA is ABOVE both the 150-day and 200-day MAs
5. Current price is ABOVE the 50-day MA
6. Current price is at least 30% ABOVE its 52-week low
7. Current price is WITHIN 25% of its 52-week HIGH (closer to new high = better)
8. Relative Strength rank ≥ 70 (IBD RS line making new highs)

**Application to our Breakout setup:** Before classifying any stock as Breakout, verify it meets at least criteria 1, 2, 4, 5, and 7. A breakout from a base with all 8 criteria = highest-confidence entry.

### VCP — Volatility Contraction Pattern
- Series of price contractions each tighter than the last (e.g., 25% pullback → 15% → 8% → 4%)
- Final contraction on DRY (low) volume = launch point
- For intraday (5-min): 3-bar VCP (each bar has smaller range than prior) followed by breakout bar = high-probability entry
- Do NOT enter VCP that has already contracted only once — need at least 3 contractions

### SEPA Breakout Entry Rules
- Exact pivot = prior session's high OR the intraday consolidation high
- Entry: 1–5 cents (or 0.1%) above the pivot. Never chase more than 3–5% above pivot
- Volume confirmation: breakout bar must be ≥40–50% above 50-day average daily volume. On 5-min bars: breakout bar volume ≥2× average bar volume for that time of day
- Maximum loss rule: 7–8% stop from entry (intraday equivalent: 1.5–2% stop within first 15 minutes)
- Position size: Risk = (Account × 1%) ÷ (Entry − Stop). Example: $100K × 1% = $1,000 risk ÷ $1.50 stop = 667 shares

### Avoid Extended Stocks
- If stock already moved >20–25% from base pivot = do NOT buy
- If Gap+Vol setup has already run >3% above prior close by 9:35 = skip, too extended
- Best setups: stock within 5–10% of 52-week high, breaking out of base on volume

### Stage 2 Characteristics (relevant to stock universe selection)
- Price above 200-day MA (40-week) in uptrend
- Big up days/weeks on volume spikes, small down days on low volume
- More up days on above-average volume than down days on above-average volume
- Stage 3 warning: first major one-day decline since Stage 2 began on heavy volume = begin tightening stops
- Stage 4: majority of price action BELOW 200-day MA + MA itself trending down = AVOID entirely

---

## §T20 — 25 Rules of Trading Discipline — Douglas Zalesky, CBOT (2003)
*Source: "The 25-Point Mantra" — SFO Magazine 2003. Direct reading, all pages.*

These rules are from a 20-year CBOT pit trader. Distilled to what applies to our automated system:

1. **The market pays you to be disciplined.** Every undisciplined trade costs money. Every disciplined trade preserves capital even on a loss.
2. **Be disciplined every trade, every day.** It is not a "sometimes" thing. One undisciplined trade can ruin an entire day.
3. **Lower trade size when trading poorly.** After 2 consecutive losing trades → reduce to minimum size. After 2 consecutive wins at minimum size → restore normal size.
4. **Never turn a winner into a loser.** When a trade is profitable, protect it. Set a trailing stop. Never hold a winner hoping for more and watch it reverse into a loss.
5. **Your biggest loser must not exceed your biggest winner.** Keep a running log of max win. Stop if any single loss approaches that level.
6. **Develop a methodology and stick with it.** Do not change methods day-to-day. If it works >50% of sessions, stick with it even on bad days.
7. **Know your comfort zone.** Trade the size you can manage emotionally. Trading oversized = butchering trades emotionally. Never exceed your psychological limit.
8. **Always be able to come back tomorrow.** Set a daily loss limit (e.g., 2% of account). When hit, stop trading. No exceptions. Capital preservation > any single day's P&L.
9. **Earn the right to trade bigger.** First prove profitability at minimum size for 10 consecutive days. Then increase by one unit. Repeat.
10. **Get out of your losers.** The gut feeling that a trade is bad is almost always right. Exit immediately when you know it's wrong. Do not wait for confirmation.
11. **The first loss is the best loss.** The longer you hold a loser, the worse it gets psychologically and financially.
12. **Don't hope and pray.** If you're hoping the market will save you, you've already lost. Exit.
13. **Don't worry about news.** By the time news hits, it's already priced in by professionals. Do not trade off CNBC/Bloomberg reporting.
14. **Hit singles not home runs.** Small consistent wins compound faster than occasional big wins interrupted by big losses.
15. **If a trade is not going anywhere in a given timeframe, exit.** Price stagnation = capital waste. Exit and redeploy.
16. **Scale out of winners.** Exit 50% at first target. Move stop to breakeven on remainder. Play with house money.
17. **Never take a big loss.** A big loss wipes out many small wins AND destroys confidence. There is no recovery from a big loss that doesn't cost emotional capital.
18. **Make a little bit every day.** Consistent small gains compound to large annual returns. Focus on daily consistency, not single-trade home runs.
19. **Love to lose money (= love to cut losers quickly).** Accept that 33% of trades will be losers. The skill is cutting them fast so they don't cost much.
20. **Be a bricklayer.** Execute the same proven setup the same way every day. No creativity, no improvisation. Brick by brick.
21. **Don't over-analyze, don't procrastinate, don't hesitate.** When setup appears, take the trade. Analysis paralysis = zero return on a correct read.
22. **All traders start equal.** The market doesn't care about yesterday's P&L. Each day starts fresh. Treat every day as a new opportunity.

**Application to our system:** Rules 3, 8, 10, 11, 16, and 17 map directly to our screener's stop logic. Rule 6 = do not modify setup criteria based on a single bad day. Rule 15 = if a Gap+Vol trade has not moved within 15 minutes of entry, exit and look for the next setup.

---

## §T21 — Volatility Trading Edge — Euan Sinclair (2013)
*Source: "Volatility Trading" 2nd Ed — Sinclair/Wiley 2013. Direct reading introduction and chapters 1–5.*

**Core principle (Sinclair intro):** The largest source of edge in option trading is trading your estimate of future volatility against the market's estimate. If you forecast realized vol will be LOWER than implied vol → sell premium. If HIGHER → buy premium.

### Variance Risk Premium (VRP) — The Structural Options Edge
- **VRP fact:** Index implied volatility (IV) is PERSISTENTLY above subsequent realized volatility (HV) by 2–5 vol points on average. This is the most reliable edge in options.
- **Implication for long options (our strategy):** We are fighting the VRP when buying options on indices. For single stocks, VRP is smaller and less consistent = better for long premium strategies.
- **VIX two-regime behavior:** VIX oscillates between two states:
  - Low/quiet regime: VIX 10–20, low volatility of volatility
  - High/volatile regime: VIX 20–40+, high volatility of volatility
- VIX is mean-reverting (weekly autocorrelation = −0.21). After a spike, expect reversion. After a low, expect eventual expansion.

### VIX Regime Rules for Option Structure Selection
| VIX Level | Regime | Options Action |
|-----------|--------|----------------|
| VIX < 15 | Very low — buy premium cheaply | Long calls/puts outright acceptable; IV likely to expand |
| VIX 15–20 | Low-normal | ATM calls acceptable when HV < IV by <5pts |
| VIX 20–25 | Normal-elevated | Prefer debit spreads to limit vega risk |
| VIX 25–35 | Elevated fear | Debit spreads only; avoid buying naked premium |
| VIX > 35 | Extreme fear | IV crush risk post-spike is extreme; wait or use very tight spreads |

### IV vs. HV Decision Rule (Sinclair framework)
- If IV is >20% ABOVE 20-day HV → options expensive → use credit or debit SPREAD (not naked long)
- If IV is >20% BELOW 20-day HV → options cheap → buy ATM calls/puts outright
- If IV ≈ HV → debit spread with 1:2 width ratio

### Intraday Volatility Seasonality (Sinclair p.31)
- True volatility is HIGHEST at the open (9:30–10:00 ET) and close (3:00–4:00 PM ET)
- Lowest during midday (11:30 AM – 1:30 PM ET)
- **Application:** Do NOT buy options at the open when IV is already elevated — you're buying at peak intraday IV. Wait for a slight pullback in IV (10:05–10:20 window) before entering option trades.
- For Gap+Vol setup: the gap itself inflates IV temporarily; if buying options on gap day, enter AFTER the first 5 minutes when overnight IV premium bleeds off.

### Position Sizing — Kelly Framework (Sinclair ch.8)
- Optimal Kelly fraction = Edge / Odds
- Never use full Kelly in live trading — variance is too high
- Practical rule: use 25% of calculated Kelly fraction (= "quarter-Kelly")
- For our setups with PF ~1.4–1.9:
  - Theoretical Kelly ≈ 15–20% of account per trade
  - Quarter-Kelly = 3.75–5% per trade
  - With max risk $400 per options trade + $100K account → 0.4% per trade = well within quarter-Kelly

### Volatility Mean Reversion Trade Rule
- When VIX spikes >5 points above its 20-day MA in a single session → IV likely to mean-revert within 2–5 days → this is the BEST time to buy options on RSI Dip setups
- When VIX has been below 15 for >30 consecutive days → volatility compression extreme → prepare for expansion → reduce position size on debit spreads

---

## §DT14 — Jeff Cooper Intra-Day Trading Tactics (2003)
*Source: "Intra-Day Trading Strategies: Proven Steps to Short-Term Trading Profits" — Jeff Cooper, 2003. Direct reading.*

**Jeff Cooper's core framework:** Stocks move in patterns of Thrust → Pause → Thrust. The pause (consolidation) after a thrust is the entry point. Three-day patterns (new 3-day high = impulse legitimate).

- **3-Day High Entry Rule:** When a stock makes a new 3-day high, the first 2-period pullback (2 bars of weakness) sets up a good risk-to-reward entry if the impulse is legitimate. Entry: on break of the 2-bar pullback high. Stop: below the 2-bar pullback low.
- **Thrust-Pause-Thrust (TPT) Pattern:** Initial impulse (thrust 1) → narrow consolidation (pause) → continuation (thrust 2). The pause bars should have contracting range and volume. Enter on first bar that exceeds pause high with expanding volume.
- **NR7 Volatility Setup:** A bar with the narrowest range of the last 7 bars = coiling energy. The breakout from NR7 often produces a trend day. Enter on stop above NR7 high (bull) or below NR7 low (bear). Direction = direction of the larger trend.
- **Gap 'n Go:** Stocks that gap open and immediately trade above the prior session's high = Gap 'n Go setup. Buy strength, not weakness. Stop: below the gap-open bar's low. Target: gap size × 1 (symmetrical move).
- **3-Point Trendline Gap Confirmation:** A gap above a 3-point trendline confirms the breakout. The gap itself IS the breakout. Do not wait for a pullback — enter at the open of the gap bar.
- **Parabolic Move Warning:** After a persistent parabolic move, a gap that opens BELOW prior day's close = bubble burst signal. Exit all longs immediately. Do not try to buy the dip in a parabolic reversal.
- **20-Day MA Recapture:** When a stock that has been below its 20-day MA recaptures it with expanding volume, it reasserts its trend. Enter long on the first close above the 20-day MA. Stop: re-close below 20-day MA.
- **Longer Pause = Bigger Explosion:** An NR7 or multi-day tight consolidation (4+ bars) produces a larger directional move than a 2-bar pause. The longer the coil, the more energy released. Prefer setups with 3+ tight bars before entry.
- **Symmetrical Moves:** After a gap, the subsequent move often equals the gap size in distance. Example: $2 gap → $2 additional run. Use this for profit targets on Gap+Vol trades.
- **First Pullback After Downtrend Line Break:** The first pullback (A) after price recaptures a downtrend line = solid risk-to-reward long entry. The downtrend line break itself is not the entry — the pullback test is.

---

## §DT15 — Weis Wyckoff Applied to Intraday Day Trading
*Distilled from Weis (2013) ch.4 — specific intraday applications for 5-min S&P 500 stocks.*

**Intraday application rule:** Read the 5-min bars the same way Weis reads daily bars. Each bar's range, close position, and volume relative to surrounding bars tells who is winning each 5-minute battle.

- **Intraday No-Supply entry:** After a Gap+Vol setup opens, if first 15-min bar is: (1) down bar, (2) narrow range, (3) volume < opening bar volume → sellers can't push it lower → buy on first up bar with volume expansion.
- **False Breakout Identification:** Breakout bar above prior high that closes in the lower 25% of its range on expanding volume = upthrust / false breakout. Exit all longs immediately. Do not hold for stop.
- **Correct Entry After Spring:** RSI Dip stock that breaks below prior day low then reverses and closes above prior day low = intraday spring. Entry: above the spring candle's high. Stop: below the spring's low. This is the highest-confidence RSI Dip entry.
- **Climax Exhaustion at 9:35 Entry:** If the first 5-min bar of the day is a wide-spread bar with very high volume (>3× average first-bar volume), it may be a buying or selling climax. Wait for the second bar to show direction before entering Gap+Vol or Breakout.
- **Volume confirmation by 10:00 AM rule:** If a Gap+Vol or Breakout setup has not attracted expanding volume by 10:00 AM (5 bars in), the move is likely failing. Exit or do not enter.
- **Bull Flag volume contraction:** The flag portion of a Bull Flag must show declining volume on each flag bar. If volume is RISING during the flag consolidation = not a bull flag = distribution. Skip the entry.
- **Selling wave analysis:** In an uptrend, when selling waves begin to increase in time and distance, the uptrend is ending. For intraday: if each pullback takes more bars and covers more price than the prior pullback = exit remaining position.

---

## §DT16 — Bulkowski Pattern Reliability & Minervini Risk Rules Applied Intraday
*Source: Bulkowski "Successful Stock Signals for Traders" (2013) + Minervini "SEPA" rules — applied to 60-min intraday holds.*

- **Bull Flag Measurement Target:** Flagpole height = target for the breakout. Intraday: use 50–75% of flagpole height as realistic target within the 60–90 min hold window.
- **Breakout Success Rate by Volume:** Upward breakouts on volume ≥1.5× average succeed 71% of the time vs. 54% on average volume (Bulkowski). Our backtest confirms this: volume requirement is critical for Breakout setup.
- **Gap Exhaustion vs. Breakaway:** Breakaway gap (from a base, above resistance) = continue — enter. Exhaustion gap (after long run, high volume, reversal close) = fade or stand aside. Rule: if stock already ran >5% in prior 3 days AND gaps up → classify as exhaustion → skip Gap+Vol entry.
- **Pullback Secondary Entry:** 61% of breakouts pull back to the breakout point within 30 days. Intraday: if price pulls back to the 9:35 breakout level within 15–30 min on DECLINING volume = secondary entry. Stop: 0.25% below the breakout level.
- **Failed Breakout = Reverse Signal:** If price breaks out but closes back inside prior range within 2–3 bars = failed breakout = exit immediately. Do not hold hoping for recovery.
- **RSI Divergence as Exit:** Price makes new intraday high but RSI(14) on 5-min chart does NOT confirm (lower high) = negative divergence = exit signal. Tighten stop to 0.5% below current price.
- **Support/Resistance at Round Numbers:** Price consistently stalls at round numbers ($50, $100, $200) and prior intraday highs/lows. Set partial profit target at first major resistance. Take 50% off at target; move stop to breakeven on remainder.
- **Maximum Intraday Extension Rule (Minervini):** If a stock has already moved >3–5% from its base by 9:35 ET = too extended to enter. Wait for a VCP-style pullback (3 tighter bars) before buying. Never chase an extended move.
- **Money Management — Fixed Fractional (Bandy):** Risk fixed 1% of account per trade. Position size = (Account × 0.01) ÷ (Entry − Stop). Never risk more than 2% on any single trade. If account drops 10% from peak → reduce size 50%. If drops 20% → stop trading, reassess.
- **Daily Loss Limit (Bandy + Zalesky):** Set hard daily loss limit of 2–3% of account. If hit, stop trading for the day. No exceptions. This prevents catastrophic sequences. In the system: if the daily_trader.py or screener_executor.py has 3 consecutive losses → pause automated entries, require manual approval.
- **Portfolio Correlation Risk (Bandy p.72):** Trading 25 S&P 500 stocks simultaneously = high correlation. When all 25 stocks held same direction, treat as 1 large position for risk. Max total portfolio risk at any time: 5–6% of account (not 25 × 2%).


---

## §T22 — Pristine Method: 4-Stage Cycle & Buy/Sell Setups — Oliver Velez (2001)
*Distilled from Velez "Swing Trading Tactics" (Pristine Capital Holdings 2001) — directly read.*

**Core concept: The Stock Atom (4-Stage Cycle).** Every stock repeats: Stage 1 (base/basing) → Stage 2 (uptrend — BUY AREA) → Stage 3 (top/distribution) → Stage 4 (downtrend — SHORT AREA). The entire life of a stock is this cycle repeated. A trader's only job: know what stage you are in and act accordingly.

**Multi-timeframe stage matching (the master key):**
- Buy when **Minor Stage 2 matches Major Stage 2** — highest-confidence long entry.
- Short when **Minor Stage 4 matches Major Stage 4** — highest-confidence short entry.
- In Stage 1 and Stage 3 (transitions), both longs and shorts are acceptable if the minor stage matches.
- "If you wish to know the road, inquire of those who have traveled it." — use higher timeframe to confirm setup.

**Pristine Buy Setup (PBS) — 3 criteria required:**
1. 3+ consecutive lower highs (major emphasis on the highs)
2. 3+ consecutive lower lows
3. 3+ consecutive dark (red) bars — signal: Minor Stage 4 pullback forming within Major Stage 2

**Pristine Buy Action:**
- Entry: Buy when stock trades above prior day's high (preferred) OR above first 30-min high if prior day's high is too extended
- Stop: $0.05–$0.10 below the entry day's low, or the prior day's low, whichever is lower
- Trail: move stop under each prior low bar after 2 complete bars until price objective met, reversal bar forms, or gap-up occurs
- Tools: Daily candlestick chart + 20ma & 40ma + CCI(5) buy signal as trigger

**Pristine Short Setup (PSS) — mirror image:**
1. 3+ consecutive higher lows
2. 3+ consecutive higher highs
3. 3+ consecutive green (up) bars — Minor Stage 2 bounce within Major Stage 4
- Entry: Short below prior day's low or below first 30-min low
- Stop: $0.05–$0.10 above entry day's high or prior day's high

**3-to-5 bar rule:** Bulls and Bears cannot consistently win more than 5 battles in a row. After 3–5 consecutive bars in one direction, the other side typically takes control. More than 5 consecutive bars in one direction = potential climax (catastrophic reversal risk). Application: 3 bars up = think sell / 3 bars down = think buy.

**CCI(5) Signals:**
- Anticipatory Buy: CCI(5) crosses above −100 from oversold
- Confirmed Buy: CCI(5) crosses above +100 from below
- Sell signals = mirror image. Only look for buy signals in uptrends; sell signals in downtrends.

**Time frame assignments (Pristine):**
- Wealth Building: Weekly chart (Core Trading, weeks-months) + Daily chart (Swing Trading, 2–10 days)
- Income Producing: Hourly chart (Guerilla Trading, 1–2 days) + 5/15-min chart (Micro-Trading, intraday)
- Always combine at least 2 time frames. Market player using more than one time frame achieves higher accuracy.

**Application to our setups:**
- Breakout = Major Stage 2 emerging (price above 50d high) — confirm Minor Stage 2 on 60-min (3+ higher lows, higher highs)
- Bull Flag = Major Stage 2 with Minor Stage 1 forming (3-bar pullback on declining volume) → buy on first Minor Stage 2 bar
- RSI Dip = Major Stage 2 with Minor Stage 4 pullback → PBS pattern → buy above prior day high when RSI2 < 10

---

## §T23 — Cross-Trader Rules: 18 Trading Champions (FWN Interviews, 1996)
*Distilled from "18 Trading Champions Share Their Keys To Top Trading Profits" (1996) — directly read.*

**George Angell (S&P 500 day trader):** Volatility + Liquidity are the two non-negotiables for any market. Without both, do not trade. "Every day I go in without an opinion. Let the market tell me where it wants to go — opinions are what get you in trouble." Uses "action points" rather than mechanical stops: at the point, will get out but waits for the bounce first. Specialists must know ONE market deeply; don't trade everything.

**Lee Gettess (risk control specialist):** "The only thing a trader can control is risk." If you say 'I won't lose more than $1,000 on this trade' there may be gaps and slippage, but you can be pretty sure you won't lose more. "My whole focus is: control the risk — that's what all the top traders do." Don't place stops before news releases (markets go nuts briefly); monitor instead. "I can take a $1,500 loss and be absolutely wrong and congratulate myself for doing the right thing."

**Tom DeMark (market timing 100%):** "Market timing is anti-trend, contrarian, pattern recognition and price exhaustion — 100%." His indicators are totally objective, mechanical, and against-the-grain of most technicians. "Money management and discipline are more important than the system." "Read a lot, test a lot, don't trade until you've done your homework."

**George Lane (stochastics inventor, 47 years trading):** "Momentum always changes direction before price." Trades 3-min, 15-min, and 30-min charts using stochastics + volume + trendlines. "That's the secret to making money: control the size of your losses." Never trades without a stop-loss. Sticks only to liquid markets.

**Gary Wagner (candlestick sentiment):** Candlesticks measure psychology — the interplay of open vs close within each bar shows who is winning (Japanese view) vs Western view of close vs prior close. Japanese view is more accurate for traders.

**Ben Warwick (event trading):** Focus on how the market REACTS to news, not the news itself. If market rallies on a number and closes in top 20% of range = buy signal. If fundamentally bullish news but market closes in bottom 20% of range = sell signal. Getting in immediately after news = 50/50 game. "You've got to identify an inefficiency" to make money consistently.

**Larry Williams (%R inventor):** "Markets top by closing on their highs and market bottoms by closing on their bottoms — markets top because they run out of buyers. %R enables you to see that." Commitments of Traders (COT) report: "When commercials go from net long to net short — that's usually a good buy signal." Commercials accumulate and distribute, they don't pick tops and bottoms. "Cut your losses and let your profits run. By and large, having targets doesn't work — you miss the one big move you need."

**Universal rules across all 18 traders:**
1. Discipline and risk control > system quality. Every champion emphasized this.
2. Specialize in 1–2 liquid markets. Don't spread attention across 20 markets.
3. Use mechanical systems to take difficult trades you wouldn't take on gut instinct alone.
4. Have a clearly defined max-loss per trade BEFORE entering. Not after.
5. The first loss is usually the best loss. Don't hold losing trades hoping for recovery.
6. Education is cheap compared to the cost of experience. Paper trade first.
7. Every market has different characteristics. Know your market well.
8. Volume + volatility determine profit potential. Low-volume slow markets = skip.

---

## §T24 — Pivot Point Analysis & P3T Method — John Person (2004)
*Distilled from Person "A Complete Guide to Technical Trading Tactics" (Wiley 2004) — directly read.*

**Pivot Point Formula (the floor trader's weapon):**
```
P  = (H + L + C) / 3        — the Pivot
R1 = (P × 2) − L            — first resistance
R2 = (P + H) − L            — second resistance
S1 = (P × 2) − H            — first support
S2 = (P − H) + L            — second support
```
- This is a LEADING indicator (predicts next session's range) vs lagging indicators (MA, MACD based on past data).
- Only take a trade off the FIRST test of S1 or R1. "If you go to the well one too many times, the well runs dry." Once the level is identified and widely tested, it loses its edge.
- Calculate daily, weekly, AND monthly pivots. Multi-timeframe pivot convergence = very high-confidence support/resistance.

**P3T — Person's Pivot Point Trade Signal (the synthesis method):**
P3T combines three layers: (1) Pivot Point level as price target/support/resistance + (2) Japanese Candlestick reversal pattern at that level + (3) Stochastics confirmation (oversold bounce at support, overbought at resistance). All three must align for a P3T entry signal.

**Verify-Verify-Verify approach:** "Lining up the stars" — a high-probability entry requires confirmation from:
- Pivot point S1/R1 as a structural level
- A candlestick reversal at that level (harami, doji, shooting star, morning star)
- Technical indicator confirmation (stochastics, CCI, or MACD)
- Volume expansion on the reversal bar
Never enter on just one signal. Wait for 2–3 overlapping confirms.

**Day-trading entry rules (from Person):**
- Buy at S1 when stochastics are oversold + a bullish candlestick (hammer, harami) forms
- Short at R1 when stochastics are overbought + a bearish candlestick (shooting star, doji) forms
- Opening Range Breakout: if price breaks above the first 30-min range high on expanding volume = long entry; stop below range low
- Oops Signal: if price gaps higher but then immediately trades below the prior day's close = sell signal (gap exhaustion)

**Candlestick + Pivot confluence (key combinations):**
- Hammer at S1 + stochastics < 20 → high-probability bounce long
- Shooting star at R1 + stochastics > 80 → high-probability reversal short
- Bullish harami at weekly pivot support → 2-day swing long
- Dark Cloud Cover at monthly R1 → position short

**Market Sentiment tools (Person ch.9):**
- Put/Call ratio (contrarian): elevated P/C ratio → sentiment bearishly extreme → bullish for market
- VIX elevated → fear extreme → contrarian bullish signal
- Commitments of Traders (COT): commercial net long = bullish; commercial net short = bearish
- Market Vane Bullish Consensus: >75% bullish = contrarian top signal; <25% = contrarian bottom

**Mental game rules (Person ch.11):** Set daily loss limits as a hard rule. Keep a trading diary after every session (entry, exit, reason, emotion, grade). Do not trade when sick, tired, or emotionally compromised. Build confidence slowly: 1 contract → 2 contracts → scale up only after consistent profitability.

**Application to our screener:** Before entering any screener signal, check:
1. Is today's price near a daily S1/R1 pivot? (favorable entry = near S1 for longs, near R1 for shorts)
2. Does the 5-min/60-min candlestick show a reversal pattern at that level?
3. Is RSI(14) or stochastics showing oversold for longs / overbought for shorts?
→ If all 3 align = highest conviction entry. If only 1 = wait or skip.

---

## §T25 — VIX Derivatives Trading — Russell Rhoads (2011)
*Distilled from Rhoads "Trading VIX Derivatives" (Wiley 2011) — directly read.*

**VIX daily move rule (practitioner shortcut):** VIX ÷ 16 = expected daily % move for S&P 500.
- VIX = 16 → 1% daily move expected
- VIX = 32 → 2% daily move expected
- VIX = 48 → 3% daily move expected
- VIX = 64+ (2008 crisis territory) → 4%+ daily moves expected

**VIX 30-day move formula:** VIX ÷ √12 = expected 30-day % move for S&P 500.
- VIX = 20 → expected 30-day move ≈ 5.77%
- VIX = 40 → expected 30-day move ≈ 11.55%

**VIX inverse relationship:** VIX rises when S&P 500 falls. Demand for put options (portfolio protection) drives up implied volatility → VIX rises. When markets panic, protection demand spikes → VIX spikes. This is structural, not random.

**VIX as a filter for MA crossover systems (Rhoads ch.9 research):**
- 20-day MA alone: $95.65 profit per unit
- 20-day MA + VIX moving average filter: $140.22 profit (+47% improvement)
- Adding a VIX overlay to standard technical systems improves results significantly
- Rule: when VIX is above its own moving average AND market is below its MA = higher risk environment → reduce position size

**VIX term structure:**
- **Contango (normal market):** VIX futures curve slopes upward — each further month has higher VIX → calm market, sellers of volatility earn the roll
- **Backwardation (stress event):** VIX futures curve slopes downward — near-term VIX > forward VIX → acute panic, temporary spike expected to revert
- Contango = structural edge for VIX sellers (iron condors, credit spreads on VXX puts)
- Backwardation → avoid selling volatility; buy protection instead

**VXX (iPath S&P 500 VIX Short-Term Futures ETN):**
- VXX tracks a rolling long in the 1st + 2nd month VIX futures, rebalanced daily
- In contango environments, VXX bleeds value due to "roll cost" (buying expensive near-term, selling cheap at expiration)
- VXX is NOT a proxy for the VIX index — in calm markets it systematically decays
- Long VXX = hedge / speculation on volatility spike. Short VXX (via puts or inverse ETNs) = structural edge in calm markets but catastrophic if VIX spikes

**VIX Futures settlement facts (critical for traders):**
- VIX futures expire on WEDNESDAY (not Friday like equity options)
- Last day of trading = Tuesday; Wednesday morning settlement
- The specific Wednesday is based on standard option expiration of the following month — varies month to month
- Always verify exact expiration date; do not assume it's the 3rd Wednesday

**VIX options key characteristics:**
- VIX options are priced off VIX FUTURES (not the VIX index itself)
- This means VIX options have their own pricing dynamics independent of where VIX is today
- VIX 25-delta put (below where VIX futures are priced) does NOT behave like SPX 25-delta put

**Practical VIX level decision table:**
| VIX Level | Market Regime | Action for Our Setups |
|-----------|---------------|-----------------------|
| <15 | Complacency / low volatility | Full size, Breakout/Bull Flag preferred |
| 15–20 | Normal | Standard sizing, all setups active |
| 20–30 | Elevated fear | Reduce to 75% size; add RSI Dip (mean-revert) |
| 30–40 | High fear | 50% size; only RSI Dip + defensive entries |
| >40 | Crisis / panic | 25% size or stand aside; wait for VIX reversal |

**Application to screener options:**
- When VIX > 25: prefer buying puts or put spreads over naked calls
- When VIX > 30: IV crush risk on long options is severe — use spreads, not naked long options
- When VIX backwardation detected: do not sell premium; go directional only
- VIX/16 daily move estimate → use as ATR proxy when setting intraday option stops

---

## §DT17 — Day Trading Frameworks: Heitkoetter (2008) + McDowell ART System (2008)
*Distilled from Heitkoetter "Complete Guide to Day Trading" (2008) + McDowell "The ART of Trading" (2008) — directly read.*

### Heitkoetter's 10 Trading Plan Principles
1. **Use few rules** — if you can't explain your system in 5 minutes, it's too complex
2. **Trade electronic and liquid markets** — avoid thinly traded markets, especially at open/close
3. **Have realistic expectations** — 10–15% annual returns are excellent; don't chase 100% per month
4. **Maintain healthy risk/reward** — never take a trade with R/R < 1:1; prefer ≥ 1:2
5. **Produce at least 5 trades per week** — systems that don't generate enough signals lead to forcing bad trades
6. **Start small, grow big** — begin with 1 contract/100 shares; scale only after proven consistency
7. **Automate exits** — manual exits are subject to emotion; set stop + target before entering, then let it work
8. **High win percentage** — target ≥ 55% win rate in your backtest before trading live
9. **Test on 200+ trades minimum** — statistical significance requires ≥200 sample trades; fewer = luck
10. **Choose valid backtesting period** — test includes at least 1 bull market + 1 bear market + 1 sideways period

### Heitkoetter's 7 Deadly Trading Mistakes
1. **Wrong market direction** — over-complexity from too many indicators; simplify: buy when market goes up, sell when it goes down. One trendline > 10 oscillators.
2. **Not taking profits** — use automatic trailing stops and pre-set profit targets; remove the decision entirely
3. **Not limiting losses** — "Risk means not having control." Set stop before entry, always. Never trade without a stop.
4. **Trading the wrong market** — trade only liquid, volatile markets. No volume = no profit potential.
5. **No strategy** — must have written rules for entry, exit, stop, and position size BEFORE entering
6. **Not controlling emotions** — trade small enough that a loss doesn't hurt emotionally; if it hurts too much, size is too large
7. **Overtrading** — fewer, higher-quality setups > more, lower-quality setups. Less is more.

### Heitkoetter's Three "Secrets" to Day Trading Success
1. Have a proven strategy (backtested on 200+ trades across different market conditions)
2. Have rock-solid discipline to follow that strategy without deviation
3. Proper money management (never risk more than 2% of account per trade)

### McDowell ART System (Applied Reality Trading)
**Core philosophy:** Price and volume are the only reality. All indicators form opinions that can lead to counterproductive behavior. MACD divergence, stochastics "overbought" — these opinions prevent traders from taking correct signals.

**ART Reversal Bar Signals (1B and 2B):**
- **1B (One-Bar Reversal):** A single bar that closes in the opposite direction of the prior trend on increased volume. First signal to watch for trend change.
- **2B (Two-Bar Reversal):** After a 1B, the next bar confirms by also closing in the reversal direction. Higher-confidence than 1B alone.
- ART reversal bars work on any timeframe — scalping (1-min), day trading (5-min), swing trading (daily)

**Pyramid Trading Points (P and MP):**
- **P (Pyramid Point):** Major trend pivot — used to define the primary trend direction and as the primary stop anchor
- **MP (Minor Pyramid Point):** Minor correction pivot within the major trend — used for scaling in and for stop adjustments
- Entry: buy above P (bullish pyramid) or sell below P (bearish pyramid)
- Stops: always based on actual chart structure (below prior P or MP), NOT arbitrary percentages

**Trend-Trading Rules (ART ch.21):**
- Only trade in the direction of the primary Pyramid Point (never countertrend for beginners)
- Entry: after confirmed 2B reversal in the direction of the trend
- Stop: below the 2B reversal bar's low (for longs)
- Target: next Pyramid Trading Point level or 2:1 R/R minimum
- Move stop to breakeven after trade moves 1× the initial risk distance

**Countertrend-Trading Rules (ART ch.22, advanced only):**
- Only after master-level experience with trend trading
- Use minor MP points to identify corrections
- Tight stops mandatory; countertrend trades = small size, quick exits

**Stop-loss philosophy (McDowell):** Stops are set based on MARKET REALITY (chart structure, ATR) — not arbitrary percentage amounts. Percentage stops frequently stop you out at the worst point. Chart-structure stops prevent premature exit.

**Application to our screener:** 
- Use ART philosophy: at entry, don't ask "what does MACD say?" — ask "what is price and volume telling me right now?"
- For Breakout: confirm 2B reversal after a 3-bar pullback to 20-period MA on 5-min chart = entry
- For RSI Dip: a 1B reversal bar (hammer/engulf) on the 60-min chart = ART entry signal
- For Bull Flag: flag is a Minor MP correction; buy on 2B reversal above flag resistance
- Stops: set below the reversal bar's low, not at a fixed 1% from entry

---

## §T26 — Intermarket Technical Analysis — John J. Murphy (1991)
*Distilled from Murphy "Intermarket Technical Analysis" (Wiley 1991) — directly read.*

**The Four Market Sectors & Their Cascade:**
```
USD (Dollar) → Commodities → Bonds → Stocks
```
- **USD ↑ → Commodities ↓** (inverse): A strong dollar makes commodities more expensive for foreign buyers → suppresses demand → commodity prices fall
- **Commodities ↑ → Bonds ↓** (inverse): Rising commodity prices signal rising inflation → bond yields rise → bond prices fall; this is the most important intermarket relationship
- **Bonds ↑ → Stocks ↑** (positive): Rising bond prices = falling interest rates = cheaper borrowing = bullish for equities
- Therefore: **USD ↑ → Commodities ↓ → Bonds ↑ → Stocks ↑** (the inflationary/deflationary cascade)
- And: **Commodities ↑ → Bonds ↓ → Stocks ↓** (the inflation-warning chain)

**The 6 core intermarket relationships (Murphy):**
1. Commodity groups internally (gold → platinum, crude → heating oil)
2. Commodity group-to-group (precious metals vs energy)
3. CRB Index vs. commodity groups (CRB = basket of 21 commodities, the key gauge)
4. **CRB Index inverse to bonds** ← most important single relationship
5. **Bonds positive to stocks** ← second most important
6. **USD inverse to commodities** (especially gold) ← third most important

**Gold as leading indicator of CRB:** Gold typically LEADS major turns in the CRB Index by 6–12 months. Watch gold for early inflation/deflation warnings before the broader CRB reacts. Rising gold = inflation risk = bearish for bonds.

**Dow Utilities as leading indicator of stocks:** Utilities are extremely interest-rate sensitive (they borrow heavily). Rising bond prices (falling yields) benefit Utilities → Utility stocks rally → general stock market follows. Utility divergence from stocks = warning of broader market reversal.

**Global market correlation:** All major global equity markets move together in major bull/bear cycles. Japanese, British, and U.S. markets peaked and bottomed within months of each other in 1987. Activity in overseas bond/stock markets provides advance warning for U.S. markets. Rule: Do not ignore global market trends when setting U.S. directional bias.

**Practical rules for our screener:**
- Monitor 10Y Treasury yield trend: Rising yields (falling bonds) = headwind for Breakout/Bull Flag setups — reduce size
- Monitor CRB/DJC commodity index: Rising commodities + rising stocks = late-cycle risk — tighten stops
- Monitor USD trend: Falling USD = tailwind for commodity/materials/energy stocks; Rising USD = headwind for same
- Gold leading CRB: If gold breaks out above prior 6-month high = inflation signal → be more cautious on bond-sensitive sectors (utilities, REITs)
- "When in doubt, look to related markets for clues." — the intermarket analyst's mantra

**1987 Crash intermarket warning (historical example):**
- Spring 1987: CRB Index broke out (commodities rising)
- Result: Bond prices collapsed (inflation fear)
- Result: Interest rates spiked
- Result: Stocks crashed in October 1987
- **Lesson:** Watch CRB + Bond divergence from stocks as an advance warning system — stocks that keep rising while bonds fall are living on borrowed time.

---

## §T27 — Options for Volatile Markets: Covered Calls, Collars & Hedging — McMillan & Lehman (2011)
*Distilled from Lehman & McMillan "Options for Volatile Markets" (Bloomberg Press 2011) — directly read.*

**Core thesis:** Covered call writing reduces portfolio volatility by approximately 1/3 vs. holding stock alone. The CBOE Buy-Write Index (BXM) outperformed the S&P 500 by 7+ percentage points (20.54% vs 13.36%) from 2004–2009. Every equity investor should use options to modify risk/reward; most don't.

**Covered Call Write — how it works:**
- Buy 100 shares XYZ at $48. Sell 1 OTM Nov 50 call at $2 premium.
- Maximum gain: capped at strike price ($50) — you give up upside above $50
- Downside protection: the $2 premium lowers your effective cost to $46 (not zero protection)
- Two returns to track:
  - **RIE (Return If Exercised):** (premium + stock gain to strike) / initial investment = ($200 + $200) / $4800 = 8.3% in 2 months
  - **RU (Return if Unchanged):** premium / initial investment = $200 / $4800 = 4.2% (floor return if stock doesn't move)
- OTM covered calls: higher upside potential, lower premium. ATM covered calls: higher premium, more protection.

**Selecting calls to write:**
- Prefer calls 1–2 strikes OTM in normal markets; ATM in high-volatility markets (more premium)
- Prefer 30–60 DTE (days to expiration): enough time premium without too much gamma risk
- Avoid writing calls during earnings week (IV spike creates illiquid rollout conditions)
- Avoid writing on stocks that have upcoming catalysts that could cause gaps beyond strike

**Covered call follow-up actions:**
- If stock rises to near strike before expiration: "roll up" — buy back current call, sell higher strike call
- If stock falls: "roll down" — buy back current call, sell lower strike call to collect more premium and lower breakeven
- If call goes ITM at expiration: let it be exercised OR roll forward to next month

**Protective put hedge (catastrophic risk):**
- Buy a put below the stock price as insurance against large drawdown
- Most effective at 10–15% OTM for quarterly protection
- Disadvantage: expensive in high-IV environments (puts cost more when you need them most)
- Rule: hedge downside when VIX < 20 (options cheap); don't buy puts when VIX > 35 (too expensive, use collar instead)

**Collar strategy (best of both):**
- Buy 100 shares XYZ + sell OTM call + buy OTM put = defined risk on BOTH sides
- Example: buy XYZ at $50, sell Nov 55 call at $2, buy Nov 45 put at $1.50 → net cost $0.50
- Max gain capped at $55; max loss capped at $45 regardless of how far stock falls
- Best application: after a big run-up, to protect gains while keeping upside — our Bull Flag exit strategy

**Application to our screener options positions:**
- **After entering a Breakout:** sell a covered call 5–8% above entry on the next options expiry (capture IV premium while stock consolidates)
- **RSI Dip entries:** buy ATM call + sell OTM call (bull call spread) to reduce net debit in high-IV conditions
- **Gap+Vol entries:** use collar if holding overnight — buy near-ATM put, sell far OTM call; limits gap-down risk
- **IV > 40% on single stock:** always use spreads (bull call or bull put spread) never naked long options — IV crush on resolution will destroy naked long option value
- **Covered call writing rule (McMillan):** Write covered calls on 50% of your position when RSI14 > 65 — reduces cost basis while maintaining 50% upside exposure

