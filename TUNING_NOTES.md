# SPY Auto Trader — Tuning Notes

## 🐛 Known issue: Account / Buying Power / Max Risk don't refresh after trades  *(staged for 2026-05-09 batch)*

**Symptom:** Header stats stuck at startup values after a trade fires:
```
Account       $100,000.00
Buying Power  $200,000.00
Max Risk      $—
```
They only update on login, session start, session end, or specific toggle events — NOT on each trade fill.

**Two contributing causes:**

1. **In DRY_RUN mode (current default):** trades are simulated locally — `register_trade()` adds a position to the in-process list but no `submit_order()` call goes to Alpaca. The Alpaca account equity genuinely doesn't change, so the next `refresh_account()` (when it eventually runs) returns the same numbers. Expected behaviour for paper-paper-simulation, but confusing.

2. **Even with DRY_RUN off and real Alpaca paper orders flowing:** [scripts/app.py:358](scripts/app.py:358) `refresh_account()` is only called from:
   - `login_alpaca` (line 602)
   - The session thread's `finally` block (line 774) — fires once per session lifetime, not per trade
   - A few toggle handlers (lines 489, 920, 1013) — only when user clicks toggles
   
   There's no call after `place_trade()` returns successfully or after `wait_for_fill()` confirms a fill. So even when real fills happen, the UI shows stale account values until the next refresh trigger fires (often only at session end).

**Fix locations (when we get to it):**
- Add `refresh_account()` + `emit_state()` after the successful `wait_for_fill()` branch in `all_day_session` (around [scripts/spy_auto_trader.py:2700](scripts/spy_auto_trader.py:2700))
- Add the same call inside `check_positions()` whenever a position is closed (stop hit / target hit / time stop / hard close)
- Optionally: a 30s background ticker that refreshes account state during active sessions, so the UI never shows >30s-stale equity

**Workaround until fix:** start/stop a session toggle to force a refresh — that fires the `finally` block and updates the header.

**Priority:** medium. Cosmetic in DRY_RUN, but real users running live-paper will want to see equity tick down after a trade opens and back up after target hits.

---

## 🔧 Operating mode reference

### Auto-Trade ON → no approval popup

When the **Auto-Trade** toggle is ON in the dashboard, the user popup ("Allow trade?") is **not required**. The bot auto-approves every signal and submits the order immediately.

- Implementation: [scripts/app.py:122-155](scripts/app.py:122) — `TradeApproval.request()` returns `True` immediately when `self.auto_trade` is set.
- Signal still gets emitted to the UI (visible chart marker + trade log entry) for observability — there's just no modal blocking.
- Log line written for every auto-approval: `Auto-trade: signal AUTO-APPROVED — placing order without user prompt.`
- Toggle wiring: [scripts/app.py:904-910](scripts/app.py:904) — `toggle_auto_trade` socket event.

**To use it:** flip the Auto-Trade switch in the config card of the dashboard. Mode pill stays showing PAPER / LIVE depending on `dry_run`; auto-trade is independent of dry-run.

**Combinations:**
| Dry-Run | Auto-Trade | Behaviour |
|---|---|---|
| ON  | OFF | Modal pops, approval simulated only (registers fake position locally, no Alpaca order) |
| ON  | ON  | No modal, approval simulated only (no Alpaca order) |
| OFF | OFF | Modal pops, real order submitted to Alpaca paper account on approval |
| OFF | ON  | **No modal, real order submitted to Alpaca paper automatically** ← fully autonomous |

---

## 📌 Pending: Switch to swing-style stop/target after today's baseline (planned 2026-05-09)

**Decision (2026-05-08):** Run today with current settings to establish a baseline win-rate / fill-quality benchmark. Switch tomorrow before market open.

### Why this is queued

Current settings imply **R:R = 1.25 : 1** which requires a **44.4% win rate** to be profitable. For a 5-min-bar momentum/trend strategy on liquid weekly options, expected win rate is 30–40%. The math is upside-down.

The single worst setting is **closing 50% of the position at +50%** — the strategy makes its money on outsized winners (clean trend days produce +150% to +300% options runs), and halving size at +50% amputates the right tail.

### Today's baseline (do NOT change before EOD 2026-05-08)

[scripts/spy_auto_trader.py:74-80](scripts/spy_auto_trader.py:74) and related:

```python
STOP_LOSS_PCT  = 0.50          # exit at -50% premium
PROFIT_TARGET  = 0.75          # final target +75%
# In place_trade / register_trade:
target_50 = entry * 1.50       # +50% triggers Target 1
target_75 = entry * 1.75       # +75% triggers Target 2 (PROFIT_TARGET)
# Target 1 closes 50% of position (max(1, remaining // 2))
# Time-stop: TIME_STOP_MINS=60, range [-15%, +25%]
```

R:R math:
- Average winner = 0.5 × 0.50 + 0.5 × 0.75 = **+0.625 × premium**
- Average loser  = **-0.50 × premium**
- Effective R:R = **1.25 : 1**, break-even win rate **44.4%**

### Tomorrow's target settings

```python
STOP_LOSS_PCT          = 0.40    # tighter — losers pay less
PROFIT_TARGET          = 1.00    # +100% final target (let runners run)
PARTIAL_QTY_FRAC       = 0.25    # NEW — close 25% (not 50%) at partial
PARTIAL_TRIGGER_PCT    = 0.50    # take a sliver off the table
BREAKEVEN_TRIGGER_PCT  = 0.30    # NEW — move stop to BE once up +30%
TIME_STOP_MINS         = 60      # unchanged
TIME_STOP_RANGE_LO     = -0.15   # unchanged
TIME_STOP_RANGE_HI     = 0.10    # was +0.25 — tighten upside (don't kill runners early)
```

R:R math:
- Average winner = 0.25 × 0.50 + 0.75 × 1.00 = **+0.875 × premium**
- Average loser  = **-0.40 × premium**
- Effective R:R = **2.2 : 1**, break-even win rate **31%**

Plus the breakeven stop after +30% means: if a winner reverses, worst case is roughly flat instead of a -50% loser. Most "winners that reversed" become scratches instead of full stops — meaningfully changes realised win-rate math.

### Code changes needed tomorrow

**Stop/target tuning (`spy_auto_trader.py` only, ~30 lines):**

1. **Constants** at top of `spy_auto_trader.py` — flip the four values above and add the two new ones (`PARTIAL_QTY_FRAC`, `PARTIAL_TRIGGER_PCT`, `BREAKEVEN_TRIGGER_PCT`)
2. **`register_trade`** — `target_50` becomes `entry × (1 + PARTIAL_TRIGGER_PCT)`; add `breakeven_armed: False` flag
3. **`check_positions`** — partial close uses `max(1, int(remaining * PARTIAL_QTY_FRAC))` instead of `remaining // 2`
4. **`check_positions`** — new branch: when `pnl_frac >= BREAKEVEN_TRIGGER_PCT` AND `not pos["breakeven_armed"]` → set `pos["stop_price"] = pos["entry_price"]` and `pos["breakeven_armed"] = True`. Log it.
5. **`check_positions`** — time-stop range upper bound becomes `+0.10` (was `+0.25`)

**Account-refresh fix (cross-file, ~4–6 lines) — see Known Issue section above:**

6. **`all_day_session` post-fill refresh** — after `wait_for_fill()` returns >0 in [scripts/spy_auto_trader.py:2700](scripts/spy_auto_trader.py:2700) area, call back into `app.refresh_account()` + `emit_state()`. Cleanest: add an optional `on_fill_callback` parameter to `all_day_session` (defaulted in `app.py:_launch_session.run()` to `lambda: (refresh_account(), emit_state())`).
7. **`check_positions` post-close refresh** — same callback pattern, fired whenever a stop/target/time/hard-close branch successfully closes a position.

Total estimated diff: **~35–40 lines across `spy_auto_trader.py` (and 3-line wiring in `app.py`).** No UI/template changes required.

### Tomorrow's batch checklist (single restart)

- [ ] Flip stop/target constants (#1)
- [ ] Update `register_trade` for new targets + breakeven flag (#2)
- [ ] Update partial-close math + breakeven-stop branch + tightened time-stop range (#3-5)
- [ ] Wire `on_fill_callback` for post-fill / post-close account refresh (#6-7)
- [ ] Smoke test: replay synthetic trade events through `_sanitize_indicators` + `register_trade` + `check_positions`
- [ ] Restart bot once. Verify first SIGNAL → modal/auto-approve → fill → header values tick.

### Baseline metrics to capture EOD today

Before switching, snapshot today's results from `scripts/analyze_session.py` and Alpaca paper account:
- Signals fired (count by symbol)
- Fills (count by symbol, direction)
- Win/loss breakdown (count, average %)
- Avg time-in-trade
- Hit rate by exit type (Target 1, Target 2, Stop, Time stop, Hard close)

That's the apples-to-apples comparison after running the new settings for a week.

### A/B comparison plan

After switching, run new settings for **5 trading days** (~25–50 fills) before forming an opinion. Single-day P&L isn't statistically meaningful for a strategy that fires <10 trades/day.

### Caveat

These projected R:R numbers are theory based on the partial-close mechanics. **Real validation comes from realised fills, not back-of-envelope math.** Use `analyze_session.py` + Alpaca paper account fills to verify the regime change.
