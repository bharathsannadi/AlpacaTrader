#!/usr/bin/env python3.11
"""
backtest_connors_daily.py — Path A, Phase 1: Connors RSI(2) on DAILY bars.

Identical discipline as prior Tier-1/Tier-2 tests:
  • PRE-SPECIFIED rules — no parameter sweeping (Davey §12)
  • Walk-forward 50/50 (train 2021-mid, test mid→2026)
  • Cost gate: Test PF ≥ 1.10 at BOTH 3 bp AND 5 bp OOS — pass both or fail
  • $0 cost — yfinance daily cache; Polygon not required

WHY THIS IS THE FRAME-SHIFT TEST
  The intraday Connors (backtest_connors.py) returned ZERO trades because
  EMA200 never forms on ~78 5-min bars per session. Daily bars give 200+
  bars of trend-filter warmup — the signal can actually fire here.
  Daily bars also change the cost structure: slippage is per-trade not
  per-ATR-notional, so thin edges that die on 5-min may survive at daily.

PRE-SPECIFIED RULES (Connors & Raschke Street Smarts p.51 + KB §8):
  Long-term filter : close  > 200-day SMA  (bull trend)
                     close  < 200-day SMA  (bear trend)
  Entry trigger    : RSI(2) < 10  (bull — deeply oversold in uptrend)
                     RSI(2) > 90  (bear — deeply overbought in downtrend)
  Execution        : enter at NEXT trading day's open (no look-ahead)
  Exit priority    :
    1. RSI(2) > 70 (bull) / < 30 (bear) at prior day's close → open next day
    2. Adverse 2×ATR(14) stop → exit at that day's open (approximation)
    3. 10-trading-day time cap → exit at open
    4. End of data → exit at last close
  Sizing           : shares = $200 risk / (2 × ATR14)  [same $200 budget as Tier-1]
  Directionality   : LONG only (bear side optional — flagged in output)
  Costs            : round-trip slippage on notional at entry+exit open prices

Data: ~/Desktop/AlpacaTrader_Data/daily_cache/{SYM}.csv (yfinance, cached)
Pass bar: Test PF ≥ 1.10 at BOTH 3 and 5 bp OOS.
"""
from __future__ import annotations
import sys, warnings
from pathlib import Path
from datetime import datetime

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent))
import logging
logging.disable(logging.CRITICAL)

import numpy as np
import pandas as pd
from daily_data import fetch_daily
from universe import ALL

# ── constants (PRE-SPECIFIED, no sweep) ──────────────────────────────────────
SMA_WIN        = 200     # trend filter window (days)
RSI_N          = 2       # Connors short RSI
RSI_LO         = 10.0   # bull entry: RSI(2) < this
RSI_HI         = 90.0   # bear entry: RSI(2) > this
RSI_EXIT_BULL  = 70.0   # bull exit trigger
RSI_EXIT_BEAR  = 30.0   # bear exit trigger
ATR_WIN        = 14      # ATR smoothing window
ATR_STOP_M     = 2.0    # stop distance = 2×ATR14
TIME_CAP_DAYS  = 10     # max hold in trading days
RISK_BUDGET    = 200.0  # $ risk per trade (consistent with all prior tests)
LONG_ONLY      = True   # if False, also trade bear side
ACCOUNT_SIZE   = 5000.0 # for Sharpe / drawdown as % of account (user's $5K profile)
# Portfolio-level cap (not signal tuning — matches live bot's risk brain):
# MAX_PORTFOLIO_RISK 20% / MAX_RISK_PCT 4% = 5 concurrent positions max.
# Without this, 24+ correlated mean-reversion entries firing on a market
# crash day create unrealistic concentrated risk ($200×24 = $4.8K = 96% of account).
MAX_CONCURRENT = 5      # max simultaneous open positions (pre-specified, not swept)

ET_ZONE        = "America/New_York"

OUT_DIR = Path(__file__).parent.parent / "backtest_results"


# ── indicator helpers ─────────────────────────────────────────────────────────
def _rsi(close: pd.Series, n: int) -> pd.Series:
    """Wilder EMA RSI. Pre-specified n; no tuning."""
    d = close.diff()
    up = d.where(d > 0, 0.0)
    dn = (-d).where(d < 0, 0.0)
    ag = up.ewm(alpha=1.0 / n, adjust=False).mean()
    al = dn.ewm(alpha=1.0 / n, adjust=False).mean()
    rs = ag / al.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50.0)


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, n: int) -> pd.Series:
    """Wilder ATR (true range EMA)."""
    prev = close.shift(1)
    tr = pd.concat([high - low,
                    (high - prev).abs(),
                    (low  - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / n, adjust=False).mean()


# ── per-symbol backtest ───────────────────────────────────────────────────────
def gen(symbol: str) -> list[dict]:
    """Return list of trade records for *symbol*."""
    df = fetch_daily(symbol)
    if df is None or df.empty:
        return []

    df = df.sort_values("date").reset_index(drop=True)
    if len(df) < SMA_WIN + 10:
        return []

    df["sma200"] = df["close"].rolling(SMA_WIN).mean()
    df["rsi2"]   = _rsi(df["close"], RSI_N)
    df["atr14"]  = _atr(df["high"], df["low"], df["close"], ATR_WIN)

    trades = []
    n = len(df)

    for i in range(SMA_WIN, n - 2):           # need SMA warmup + 1 future bar
        sma   = df["sma200"].iloc[i]
        rsi   = df["rsi2"].iloc[i]
        atr   = df["atr14"].iloc[i]
        close = df["close"].iloc[i]

        if np.isnan(sma) or np.isnan(atr) or atr <= 0:
            continue

        # --- entry logic ---
        direction = None
        if rsi < RSI_LO and close > sma:
            direction = "bull"
        elif not LONG_ONLY and rsi > RSI_HI and close < sma:
            direction = "bear"
        if direction is None:
            continue

        # Enter at NEXT day's open — no look-ahead
        ei = i + 1
        if ei >= n:
            continue
        entry_open = df["open"].iloc[ei]
        entry_date = df["date"].iloc[ei]
        sgn = 1.0 if direction == "bull" else -1.0
        shares = max(1.0, RISK_BUDGET / (ATR_STOP_M * atr))
        stop_dist = ATR_STOP_M * atr

        # --- exit walk ---
        exit_price = None
        exit_why   = "eod"
        exit_date  = df["date"].iloc[-1]

        for j in range(ei + 1, min(ei + TIME_CAP_DAYS + 1, n)):
            prev_rsi  = df["rsi2"].iloc[j - 1]   # prior-close RSI decides if we exit TODAY's open
            j_open    = df["open"].iloc[j]
            adverse   = (entry_open - j_open) if direction == "bull" else (j_open - entry_open)

            # 1. Mean-reversion exit: prior-close RSI crossed exit threshold
            if direction == "bull" and prev_rsi >= RSI_EXIT_BULL:
                exit_price, exit_why, exit_date = j_open, "mean_revert", df["date"].iloc[j]
                break
            if direction == "bear" and prev_rsi <= RSI_EXIT_BEAR:
                exit_price, exit_why, exit_date = j_open, "mean_revert", df["date"].iloc[j]
                break

            # 2. ATR stop (approximate — check if yesterday's low/high breached)
            if direction == "bull":
                day_low = df["low"].iloc[j]
                if (entry_open - day_low) >= stop_dist:
                    exit_price = entry_open - stop_dist   # approximate fill
                    exit_why, exit_date = "atr_stop", df["date"].iloc[j]
                    break
            else:
                day_high = df["high"].iloc[j]
                if (day_high - entry_open) >= stop_dist:
                    exit_price = entry_open + stop_dist
                    exit_why, exit_date = "atr_stop", df["date"].iloc[j]
                    break

            # 3. Time cap
            if j == min(ei + TIME_CAP_DAYS, n - 1):
                exit_price, exit_why, exit_date = j_open, "time_cap", df["date"].iloc[j]
                break

        if exit_price is None:
            exit_price = float(df["close"].iloc[-1])
            exit_date  = df["date"].iloc[-1]
            exit_why   = "eod"

        trades.append({
            "sym":       symbol,
            "date":      str(entry_date.date()),
            "exit_date": str(exit_date.date()),
            "year":      str(entry_date.year),
            "dir":       direction,
            "entry":     float(entry_open),
            "exit":      float(exit_price),
            "shares":    shares,
            "sgn":       sgn,
            "why":       exit_why,
        })

    return trades


# ── P&L + stats ───────────────────────────────────────────────────────────────
def pnl(t: dict, slip_bp: float) -> float:
    bp = slip_bp / 1e4
    raw = t["sgn"] * (t["exit"] - t["entry"]) * t["shares"]
    cost = (t["entry"] + t["exit"]) * bp * t["shares"]   # RT slippage
    return raw - cost


def stats(trades: list[dict], slip_bp: float) -> dict:
    if not trades:
        return {"n": 0, "win": 0.0, "pf": 0.0, "avg": 0.0, "tot": 0.0}
    ps = [pnl(t, slip_bp) for t in trades]
    gw = sum(x for x in ps if x > 0)
    gl = abs(sum(x for x in ps if x < 0))
    return {
        "n":   len(ps),
        "win": round(sum(1 for x in ps if x > 0) / len(ps) * 100, 1),
        "pf":  round(gw / gl, 2) if gl else (99.9 if gw else 0.0),
        "avg": round(sum(ps) / len(ps), 2),
        "tot": round(sum(ps), 0),
    }


# ── Portfolio-level position cap ─────────────────────────────────────────────
def portfolio_cap(trades: list[dict], max_concurrent: int) -> list[dict]:
    """
    Filter trades respecting a max-concurrent-open-positions limit.
    Trades are processed in (entry_date, symbol) order — deterministic.
    A position is 'open' from entry_date (inclusive) to exit_date (exclusive).
    This models the live bot's MAX_PORTFOLIO_RISK / MAX_RISK_PCT cap.
    """
    ordered = sorted(trades, key=lambda t: (t["date"], t["sym"]))
    taken: list[dict] = []          # accepted trades

    for t in ordered:
        # count currently open positions at this entry date
        open_now = sum(
            1 for o in taken
            if o["date"] <= t["date"] < o["exit_date"]
        )
        if open_now < max_concurrent:
            taken.append(t)

    return taken


# ── GO_LIVE_CHECKLIST metrics ─────────────────────────────────────────────────
def checklist_stats(test_trades: list[dict], slip_bp: float,
                    test_start: str, test_end: str) -> dict:
    """
    Compute the metrics required by GO_LIVE_CHECKLIST §1 from test-half trades.
    Returns a dict; all values are strings for direct report insertion.
    """
    if not test_trades:
        return {}

    ps_sorted = sorted(test_trades, key=lambda t: t["date"])
    pnl_vals  = [pnl(t, slip_bp) for t in ps_sorted]

    # ── daily P&L series (assign each closed trade's P&L to its exit date) ──
    from collections import defaultdict
    daily_pnl: dict[str, float] = defaultdict(float)
    for t, p in zip(ps_sorted, pnl_vals):
        daily_pnl[t["date"]] += p

    bdays = pd.bdate_range(test_start, test_end)
    daily_series = pd.Series(
        [daily_pnl.get(str(d.date()), 0.0) for d in bdays],
        index=bdays
    )

    # ── Sharpe (annualized, account-based) ──────────────────────────────────
    daily_ret = daily_series / ACCOUNT_SIZE
    sharpe = (daily_ret.mean() / daily_ret.std() * np.sqrt(252)
              if daily_ret.std() > 0 else 0.0)

    # ── Max drawdown (% of running peak equity) ──────────────────────────────
    # running_eq = account balance over time (starts at ACCOUNT_SIZE)
    cum_eq     = daily_series.cumsum()
    running_eq = ACCOUNT_SIZE + cum_eq          # account grows with profits
    peak_eq    = running_eq.cummax()            # high-water mark
    drawdown   = (peak_eq - running_eq) / peak_eq * 100   # % of peak
    max_dd     = drawdown.max()

    # ── Annualized return (on account) ───────────────────────────────────────
    years = (pd.Timestamp(test_end) - pd.Timestamp(test_start)).days / 365.25
    ann_ret = (sum(pnl_vals) / ACCOUNT_SIZE / years * 100) if years > 0 else 0.0

    # ── Top-3 trade concentration ─────────────────────────────────────────────
    gross_profit = sum(p for p in pnl_vals if p > 0)
    top3         = sum(sorted(pnl_vals, reverse=True)[:3])
    top3_pct     = (top3 / gross_profit * 100) if gross_profit > 0 else 0.0

    # ── SPY buy-and-hold over same period ─────────────────────────────────────
    spy_df  = fetch_daily("SPY")
    spy_ret = None
    if spy_df is not None:
        spy_df = spy_df[(spy_df["date"] >= test_start) & (spy_df["date"] <= test_end)]
        if len(spy_df) >= 2:
            spy_ret = (spy_df["close"].iloc[-1] / spy_df["close"].iloc[0] - 1) * 100

    # ── 18-month window check (last 18 months of test) ───────────────────────
    cutoff_18m = (pd.Timestamp(test_end) - pd.DateOffset(months=18)).strftime("%Y-%m-%d")
    last18 = [t for t in test_trades if t["date"] >= cutoff_18m]
    s18    = stats(last18, slip_bp)

    return {
        "ann_ret_pct":  round(ann_ret, 1),
        "sharpe":       round(sharpe, 2),
        "max_dd_pct":   round(max_dd, 1),
        "top3_pct":     round(top3_pct, 1),
        "spy_ret_pct":  round(spy_ret, 1) if spy_ret is not None else None,
        "years":        round(years, 2),
        "last18_pf":    s18["pf"],
        "last18_n":     s18["n"],
    }


# ── main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    syms = [s.upper() for s in sys.argv[1:]] or list(ALL)
    long_only_label = "LONG-only" if LONG_ONLY else "LONG+SHORT"
    print(f"backtest_connors_daily — {len(syms)} syms  "
          f"RSI({RSI_N})<{RSI_LO:.0f} above SMA{SMA_WIN}  {long_only_label}  "
          f"exit RSI>{RSI_EXIT_BULL:.0f}|{ATR_STOP_M}×ATR|{TIME_CAP_DAYS}d  "
          f"$0 yfinance cache\n", flush=True)

    all_tr: list[dict] = []
    for s in syms:
        tr = gen(s)
        print(f"  {s:<6} {len(tr):>4} trades", flush=True)
        all_tr += tr

    # ── report ────────────────────────────────────────────────────────────────
    L: list[str] = [
        f"# Path A — Connors RSI({RSI_N}) Daily-Bar Backtest\n",
        f"_Generated {datetime.now():%Y-%m-%d %H:%M}_\n",
        f"**Pre-specified rules (no sweeping):** RSI({RSI_N}) < {RSI_LO:.0f} above "
        f"SMA{SMA_WIN} (bull), enter next-day open, exit when RSI > {RSI_EXIT_BULL:.0f} "
        f"at prior close or {ATR_STOP_M}×ATR14 stop or {TIME_CAP_DAYS}-day cap. "
        f"{long_only_label}. Same \\$200 risk budget. Same 3 & 5 bp cost gate.\n",
    ]

    if not all_tr:
        L.append("**NO trades generated.** Signal too strict or insufficient "
                 "data in cache — check `daily_data.py` cache and symbol list.")
        print(L[-1])
        OUT_DIR.mkdir(exist_ok=True)
        fn = OUT_DIR / f"backtest_connors_daily_{datetime.now():%Y-%m-%d}.md"
        fn.write_text("\n".join(L))
        print(f"\n✓ Report → {fn}")
        return

    # Apply portfolio cap (position limit — not signal tuning)
    capped_tr = portfolio_cap(all_tr, MAX_CONCURRENT)
    print(f"\n  Portfolio cap ({MAX_CONCURRENT} concurrent): "
          f"{len(all_tr)} raw → {len(capped_tr)} accepted trades", flush=True)

    # Use capped trades for all downstream analysis
    all_tr = capped_tr

    # date-sorted for walk-forward split
    dates = sorted({t["date"] for t in all_tr})
    split = dates[len(dates) // 2]

    # full-sample table
    L += [
        "## Full-sample (context; split at training midpoint)\n",
        "| bp | n | Win% | PF | Avg\\$ | Total\\$ |",
        "|---|---|---|---|---|---|",
    ]
    for bp in (1, 3, 5, 10):
        s = stats(all_tr, bp)
        flag = "✅" if s["pf"] >= 1.10 else ("⚠️" if s["pf"] >= 1.0 else "⛔")
        L.append(f"| {bp} | {s['n']} | {s['win']} | {s['pf']} {flag} | "
                 f"{s['avg']:+} | {s['tot']:+} |")

    # walk-forward table
    train = [t for t in all_tr if t["date"] <  split]
    test  = [t for t in all_tr if t["date"] >= split]
    L += [
        "\n## Walk-forward — TEST half (the honest read)\n",
        f"_Split date: {split}  |  train n={len(train)}  test n={len(test)}_\n",
        "| bp | Train PF | **Test PF** | Test Win% | Test \\$ |",
        "|---|---|---|---|---|",
    ]
    te_pf = {}
    for bp in (3, 5):
        trn = stats(train, bp)
        tst = stats(test,  bp)
        te_pf[bp] = tst["pf"]
        flag = "✅" if tst["pf"] >= 1.10 else ("⚠️" if tst["pf"] >= 1.0 else "⛔")
        L.append(f"| **{bp}** | {trn['pf']} | **{tst['pf']}** {flag} | "
                 f"{tst['win']} | {tst['tot']:+} |")

    # per-symbol breadth
    L += [
        "\n## Per-symbol breadth (@ 3 bp, TEST half)\n",
        "| Symbol | n | Win% | PF | Total\\$ |",
        "|---|---|---|---|---|",
    ]
    from collections import defaultdict
    grp: dict[str, list] = defaultdict(list)
    for t in test:
        grp[t["sym"]].append(t)
    pos = tot = 0
    for sym in sorted(grp):
        s = stats(grp[sym], 3)
        tot += 1
        if s["pf"] >= 1.0:
            pos += 1
        flag = "✅" if s["pf"] >= 1.10 else ("⚠️" if s["pf"] >= 1.0 else "⛔")
        L.append(f"| {sym} | {s['n']} | {s['win']} | {s['pf']} {flag} | {s['tot']:+} |")
    L.append(f"\n**{pos}/{tot} symbols PF ≥ 1.0 @3bp in test half.**")

    # exit-type breakdown
    L += ["\n## Exit breakdown (TEST half)\n",
          "| Exit type | n | % |", "|---|---|---|"]
    from collections import Counter
    ec = Counter(t["why"] for t in test)
    for why, cnt in sorted(ec.items(), key=lambda x: -x[1]):
        L.append(f"| {why} | {cnt} | {cnt/len(test)*100:.0f}% |")

    # per-year robustness
    L += ["\n## Per-year PF (@ 3 bp, all years)\n",
          "| Year | n | PF |", "|---|---|---|"]
    from collections import defaultdict as dd2
    by_yr: dict[str, list] = dd2(list)
    for t in all_tr:
        by_yr[t["year"]].append(t)
    for yr in sorted(by_yr):
        s = stats(by_yr[yr], 3)
        flag = "✅" if s["pf"] >= 1.0 else "⛔"
        L.append(f"| {yr} | {s['n']} | {s['pf']} {flag} |")

    # VERDICT
    passed = te_pf.get(3, 0) >= 1.10 and te_pf.get(5, 0) >= 1.10
    L.append("\n## Verdict\n")
    if passed:
        L.append(
            f"**✅ CANDIDATE — Test PF {te_pf[3]}@3bp / {te_pf[5]}@5bp, BOTH ≥ 1.10 OOS.**\n\n"
            f"Clears cost-robust gate. **Not auto-live** — GO_LIVE_CHECKLIST and paper "
            f"incubation still required (see checklist section below)."
        )
    else:
        L.append(
            f"**⛔ FAILS cost-robust gate (Test PF {te_pf.get(3,0)}@3bp / "
            f"{te_pf.get(5,0)}@5bp; need ≥ 1.10 at BOTH).**\n\n"
            f"Daily-bar Connors RSI(2) does NOT survive realistic costs on this universe. "
            f"Frame-shift moved the dial but not enough. Next Tier-A candidates: "
            f"PEAD (post-earnings drift), overnight/intraday return decomposition, "
            f"variance risk premium / systematic short-vol (Sinclair Ch10). "
            f"Stay paper; GO_LIVE_CHECKLIST hard gate stands."
        )

    # GO_LIVE_CHECKLIST metrics
    cl = checklist_stats(test, 3, split, max(t["date"] for t in test))
    if cl:
        def _ck(ok: bool) -> str:
            return "✅" if ok else "⛔"
        spy_line = (f"{cl['spy_ret_pct']:+.1f}%" if cl["spy_ret_pct"] is not None
                    else "N/A")
        beats_spy = (cl["ann_ret_pct"] > 0 and cl["spy_ret_pct"] is not None
                     and cl["ann_ret_pct"] > cl["spy_ret_pct"] / cl["years"])
        L += [
            "\n## GO_LIVE_CHECKLIST — §1 Edge metrics (test half, @3bp)\n",
            f"_Account size assumed: \\${ACCOUNT_SIZE:,.0f} · test window: {split} → "
            f"{max(t['date'] for t in test)} ({cl['years']:.1f} yr)_\n",
            "| Metric | Value | Threshold | Status |",
            "|---|---|---|---|",
            f"| Annualized return (on account) | {cl['ann_ret_pct']:+.1f}%/yr | > 0 | "
            f"{_ck(cl['ann_ret_pct'] > 0)} |",
            f"| Test PF @3bp (OOS) | {te_pf.get(3, 0)} | ≥ 1.10 | "
            f"{_ck(te_pf.get(3, 0) >= 1.10)} |",
            f"| Test PF @5bp (OOS) | {te_pf.get(5, 0)} | ≥ 1.10 | "
            f"{_ck(te_pf.get(5, 0) >= 1.10)} |",
            f"| Test PF last 18 months (n={cl['last18_n']}) | {cl['last18_pf']} | ≥ 1.10 | "
            f"{_ck(cl['last18_pf'] >= 1.10)} |",
            f"| OOS decay (train→test) | {round((te_pf.get(3,1.0)/stats(train,3)['pf']-1)*100,1) if stats(train,3)['pf'] else 'N/A'}% | < −25% = fail | "
            f"{_ck(stats(train,3)['pf'] > 0 and (te_pf.get(3,0)/stats(train,3)['pf']) > 0.75)} |",
            f"| Annualized Sharpe (@3bp) | {cl['sharpe']} | ≥ 0.8 | "
            f"{_ck(cl['sharpe'] >= 0.8)} |",
            f"| Max drawdown (% of account) | {cl['max_dd_pct']:.1f}% | < 12% | "
            f"{_ck(cl['max_dd_pct'] < 12.0)} |",
            f"| Top-3 trades as % of gross profit | {cl['top3_pct']:.1f}% | < 40% | "
            f"{_ck(cl['top3_pct'] < 40.0)} |",
            f"| SPY B&H total return (same window) | {spy_line} | strategy beats SPY ann. | "
            f"{_ck(beats_spy)} |",
            "",
            f"_Note: \\$5K account size means strategy P&L is a large % of account — "
            f"Sharpe and DD figures are sensitive to account-size assumption. "
            f"Short-selling (bear side) may require margin; borrowing costs not modelled._",
        ]

    L.append(
        f"\n_Data: yfinance daily bars (5yr, free). Pre-specified Connors RSI({RSI_N}) rules. "
        f"Same \\$200 risk budget + 3 & 5 bp cost gate as all prior tests._"
    )

    out_text = "\n".join(L)
    OUT_DIR.mkdir(exist_ok=True)
    fn = OUT_DIR / f"backtest_connors_daily_{datetime.now():%Y-%m-%d}.md"
    fn.write_text(out_text)
    print(f"\n✓ Report → {fn}\n")
    # print verdict section to stdout
    print(out_text.split("## Verdict")[-1][:1200])


if __name__ == "__main__":
    main()
