#!/usr/bin/env python3.11
"""
Backtest harness — SPY Auto Trader
====================================
Standalone replay of the signal logic against historical 5-min bars.
No webapp changes required. Uses yfinance for free OHLCV data.

Usage:
    venv/bin/python3.11 backtest.py                   # SPY, last 90 days
    venv/bin/python3.11 backtest.py --symbol NVDA     # single symbol
    venv/bin/python3.11 backtest.py --days 180        # longer window
    venv/bin/python3.11 backtest.py --symbols SPY NVDA AMZN

Output:
    backtest_results/YYYY-MM-DD_<symbol>.md   — per-symbol report
    backtest_results/summary.md               — aggregate across symbols

NOTE: This is a *signal replay* backtest, not an options backtest.
Option pricing on historical chains requires Polygon/ThetaData subscriptions.
We approximate option P&L using a simplified delta model (see _option_pnl).
Treat results as directional signal quality, not actual dollar returns.
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from datetime import datetime, date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import numpy as np

ET = ZoneInfo("America/New_York")
RESULTS_DIR = Path(__file__).parent / "backtest_results"
RESULTS_DIR.mkdir(exist_ok=True)

# ── Load .env ─────────────────────────────────────────────────────────────────
_ENV = Path(__file__).parent / ".env"
def _load_env():
    if not _ENV.exists():
        return
    for line in _ENV.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip("'\""))
_load_env()

# ── Signal parameters (mirror spy_auto_trader.py defaults) ────────────────────
STOP_LOSS_PCT      = 0.30   # 30% premium drop → stop
PARTIAL_PCT        = 0.30   # +30% → close 50%
PROFIT_TARGET_PCT  = 1.00   # +100% → close rest
HARD_CLOSE_HOUR    = 15     # 3 PM ET time stop
HARD_CLOSE_MIN     = 45
SESSION_START      = (9, 30)
SESSION_END        = (15, 45)

# ── Indicator computation (mirrors _add_indicators) ──────────────────────────
def _add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add VWAP, EMA9/21, RSI(14), volume ratio, ORB to bar dataframe."""
    df = df.copy()
    # VWAP — cumulative (reset each day)
    df["vwap"] = (df["Close"] * df["Volume"]).cumsum() / df["Volume"].cumsum()
    df["ema9"]  = df["Close"].ewm(span=9,  adjust=False).mean()
    df["ema21"] = df["Close"].ewm(span=21, adjust=False).mean()

    # RSI(14)
    delta = df["Close"].diff()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)
    avg_g = gain.ewm(span=14, adjust=False).mean()
    avg_l = loss.ewm(span=14, adjust=False).mean()
    rs    = avg_g / avg_l.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))

    # Volume ratio vs 20-bar rolling avg
    df["vol_avg"]   = df["Volume"].rolling(20).mean()
    df["vol_ratio"] = df["Volume"] / df["vol_avg"].replace(0, np.nan)

    # ATR(14)
    hl  = df["High"] - df["Low"]
    hc  = (df["High"] - df["Close"].shift()).abs()
    lc  = (df["Low"]  - df["Close"].shift()).abs()
    df["atr"] = pd.concat([hl, hc, lc], axis=1).max(axis=1).ewm(span=14, adjust=False).mean()

    return df


def _orb(day_bars: pd.DataFrame, orb_minutes: int = 30) -> tuple[float, float]:
    """Return (orb_high, orb_low) for the first `orb_minutes` of the day."""
    cutoff = day_bars.index[0] + pd.Timedelta(minutes=orb_minutes)
    orb    = day_bars[day_bars.index <= cutoff]
    if orb.empty:
        return float("nan"), float("nan")
    return float(orb["High"].max()), float(orb["Low"].min())


# ── Signal logic (simplified mirror of all_day_session checks) ────────────────
def _generate_signals(day_bars: pd.DataFrame) -> list[dict]:
    """
    Replay indicator logic on intraday bars and return a list of signal dicts.
    Each dict: {time, direction, reason, price, bar_idx}
    """
    signals = []
    if len(day_bars) < 25:
        return signals

    df = _add_indicators(day_bars)
    orb_h, orb_l = _orb(day_bars)
    orb_formed = not (math.isnan(orb_h) or math.isnan(orb_l))

    in_position = None  # track so we don't double-enter

    for i in range(25, len(df)):
        bar  = df.iloc[i]
        prev = df.iloc[i - 1]
        ts   = df.index[i]

        # Only trade in session hours
        if ts.hour < SESSION_START[0] or (ts.hour == SESSION_START[0] and ts.minute < SESSION_START[1]):
            continue
        if ts.hour > HARD_CLOSE_HOUR or (ts.hour == HARD_CLOSE_HOUR and ts.minute >= HARD_CLOSE_MIN):
            break
        # Avoid first 5 bars after ORB formation (~30 min window)
        if i < 35:
            continue

        close = float(bar["Close"])
        vwap  = float(bar["vwap"])  if not math.isnan(bar["vwap"])  else close
        ema9  = float(bar["ema9"])  if not math.isnan(bar["ema9"])  else close
        ema21 = float(bar["ema21"]) if not math.isnan(bar["ema21"]) else close
        rsi   = float(bar["rsi"])   if not math.isnan(bar["rsi"])   else 50.0
        vol_r = float(bar["vol_ratio"]) if not math.isnan(bar.get("vol_ratio", float("nan"))) else 1.0

        bull_score = 0
        bear_score = 0

        # ORB breakout
        if orb_formed and close > orb_h * 1.001 and prev["Close"] <= orb_h:
            bull_score += 2
        if orb_formed and close < orb_l * 0.999 and prev["Close"] >= orb_l:
            bear_score += 2

        # VWAP cross
        if close > vwap and prev["Close"] <= prev["vwap"]:
            bull_score += 1
        if close < vwap and prev["Close"] >= prev["vwap"]:
            bear_score += 1

        # EMA alignment
        if ema9 > ema21 and close > ema9:
            bull_score += 1
        if ema9 < ema21 and close < ema9:
            bear_score += 1

        # RSI gates (avoid overbought/oversold entries against direction)
        if rsi > 70:
            bear_score += 1
            bull_score = max(0, bull_score - 1)
        if rsi < 30:
            bull_score += 1
            bear_score = max(0, bear_score - 1)

        # Volume confirmation
        if vol_r < 1.2:
            bull_score = max(0, bull_score - 1)
            bear_score = max(0, bear_score - 1)

        direction = None
        reason    = ""
        # ORB breakout alone = strong signal (score 2); otherwise need 2+ confluence
        if bull_score >= 2 and bull_score > bear_score and in_position != "bull":
            direction = "bull"
            reason    = "ORB+VWAP+EMA bull" if bull_score >= 3 else "VWAP+EMA bull"
        elif bear_score >= 2 and bear_score > bull_score and in_position != "bear":
            direction = "bear"
            reason    = "ORB+VWAP+EMA bear" if bear_score >= 3 else "VWAP+EMA bear"

        if direction:
            signals.append({
                "time":      ts,
                "direction": direction,
                "reason":    reason,
                "price":     close,
                "bar_idx":   i,
                "rsi":       rsi,
                "vol_ratio": vol_r,
            })
            in_position = direction

    return signals


# ── Simplified option P&L approximation ───────────────────────────────────────
def _option_pnl(entry_px: float, signals: list[dict],
                df: pd.DataFrame) -> list[dict]:
    """
    Simulate P&L for each signal using underlying price movement as a proxy.

    This is NOT actual option pricing. We use a simplified model:
      - ATM option premium ≈ 0.5% of underlying × days_to_expiry^0.5 (rough)
      - Delta ≈ 0.5 for ATM, decays as underlying moves away
      - We track the underlying move and apply a 2× leverage factor
        (typical ATM option exposure for 7-14 DTE)

    For real dollar accuracy you need historical option chains (Polygon/ThetaData).
    This gives a valid signal quality signal: is the direction right?
    """
    trades = []
    for sig in signals:
        i     = sig["bar_idx"]
        entry = sig["price"]
        dir_  = sig["direction"]
        rows  = df.iloc[i:]

        # Approximate initial option premium (0.5% of underlying for 7-14 DTE ATM)
        opt_entry = entry * 0.005 * 3.0  # ~1.5% of underlying = rough ATM premium

        stop_px  = opt_entry * (1 - STOP_LOSS_PCT)
        part_px  = opt_entry * (1 + PARTIAL_PCT)
        tgt_px   = opt_entry * (1 + PROFIT_TARGET_PCT)

        pnl_pct  = None
        exit_reason = "time_stop"
        exit_time   = None

        remaining = 1.0  # fraction of position

        for j in range(1, len(rows)):
            bar      = rows.iloc[j]
            bar_time = rows.index[j]
            und_px   = float(bar["Close"])

            # Underlying move → option proxy (delta ≈ 0.5, leverage ≈ 2×)
            und_move = (und_px - entry) / entry
            if dir_ == "bear":
                und_move = -und_move
            opt_current = opt_entry * (1 + und_move * 2.0)
            opt_current = max(opt_current, 0.01)

            opt_pct = (opt_current - opt_entry) / opt_entry

            # Time stop
            if (bar_time.hour > HARD_CLOSE_HOUR or
                    (bar_time.hour == HARD_CLOSE_HOUR and bar_time.minute >= HARD_CLOSE_MIN)):
                pnl_pct = opt_pct * remaining
                exit_reason = "time_stop"
                exit_time = bar_time
                break

            # Stop
            if opt_current <= stop_px:
                pnl_pct = -STOP_LOSS_PCT * remaining
                exit_reason = "stop"
                exit_time = bar_time
                break

            # T1 partial
            if opt_current >= part_px and remaining == 1.0:
                remaining = 0.5
                # lock half at +30%
                pnl_pct_partial = PARTIAL_PCT * 0.5
                opt_entry = opt_current  # reset basis for trailing half
                continue

            # T2 full close
            if opt_current >= tgt_px:
                pnl_pct = PROFIT_TARGET_PCT * remaining + (PARTIAL_PCT * 0.5 if remaining < 1 else 0)
                exit_reason = "target"
                exit_time = bar_time
                break
        else:
            # End of day
            pnl_pct = opt_pct if pnl_pct is None else pnl_pct

        if pnl_pct is None:
            pnl_pct = 0.0

        trades.append({
            "entry_time":  sig["time"],
            "exit_time":   exit_time or rows.index[-1],
            "direction":   dir_,
            "reason":      sig["reason"],
            "entry_price": entry,
            "pnl_pct":     round(pnl_pct * 100, 2),
            "exit_reason": exit_reason,
            "rsi":         sig["rsi"],
            "vol_ratio":   sig["vol_ratio"],
        })

    return trades


# ── Metrics ───────────────────────────────────────────────────────────────────
def _metrics(trades: list[dict]) -> dict:
    if not trades:
        return {"n": 0}
    wins   = [t for t in trades if t["pnl_pct"] > 0]
    losses = [t for t in trades if t["pnl_pct"] < 0]
    n      = len(trades)
    wr     = len(wins) / n * 100
    avg_w  = sum(t["pnl_pct"] for t in wins)  / len(wins)  if wins  else 0
    avg_l  = sum(t["pnl_pct"] for t in losses) / len(losses) if losses else 0
    gw     = sum(t["pnl_pct"] for t in wins)
    gl     = abs(sum(t["pnl_pct"] for t in losses))
    pf     = gw / gl if gl else float("inf")
    exp    = (wr / 100) * avg_w + (1 - wr / 100) * avg_l
    r_unit = STOP_LOSS_PCT * 100
    avg_r  = (sum(t["pnl_pct"] for t in trades) / n / r_unit) if r_unit else 0

    # Sharpe approximation (daily P&L, annualised)
    daily = pd.Series([t["pnl_pct"] for t in trades])
    sharpe = (daily.mean() / daily.std() * math.sqrt(252)) if daily.std() > 0 else 0

    # Max drawdown on cumulative P&L
    cumul = daily.cumsum()
    peak  = cumul.cummax()
    dd    = (cumul - peak).min()

    # Baseline: buy-and-hold underlying (rough comparison)
    return {
        "n": n, "wins": len(wins), "losses": len(losses),
        "win_rate": round(wr, 1),
        "avg_win": round(avg_w, 2), "avg_loss": round(avg_l, 2),
        "gross_wins": round(gw, 2), "gross_losses": round(gl, 2),
        "profit_factor": round(pf, 2) if pf != float("inf") else "∞",
        "expectancy": round(exp, 2),
        "avg_r": round(avg_r, 2),
        "sharpe": round(sharpe, 2),
        "max_dd": round(float(dd), 2),
        "total_pnl": round(sum(t["pnl_pct"] for t in trades), 2),
    }


# ── Report builder ────────────────────────────────────────────────────────────
def _report(symbol: str, period_days: int, trades: list[dict], m: dict,
            baseline_pct: float) -> str:
    today = date.today().isoformat()
    pf    = m.get("profit_factor", "n/a")
    lines = [
        f"# Backtest Report — {symbol}",
        f"_Period: last {period_days} calendar days | Generated: {today}_",
        f"_Underlying data: yfinance 5-min bars | Option P&L: delta-proxy model_",
        "",
        "---",
        "",
        "## Summary",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Trades | {m.get('n', 0)} |",
        f"| Win Rate | {m.get('win_rate', 0):.1f}% |",
        f"| Avg Win | {m.get('avg_win', 0):+.2f}% |",
        f"| Avg Loss | {m.get('avg_loss', 0):+.2f}% |",
        f"| Profit Factor | {pf} |",
        f"| Expectancy | {m.get('expectancy', 0):+.2f}% / trade |",
        f"| Avg R-Multiple | {m.get('avg_r', 0):+.2f}R |",
        f"| Sharpe (annualised) | {m.get('sharpe', 0):.2f} |",
        f"| Max Drawdown | {m.get('max_dd', 0):.2f}% |",
        f"| Total Signal P&L | {m.get('total_pnl', 0):+.2f}% |",
        f"| Buy-and-Hold underlying | {baseline_pct:+.2f}% |",
        "",
        "---",
        "",
        "## Trade Log",
        "",
        "| Date | Dir | Reason | Entry $ | P&L % | Exit |",
        "|------|-----|--------|---------|-------|------|",
    ]
    for t in trades:
        dt  = t["entry_time"].strftime("%m-%d %H:%M")
        dir_= "CALL" if t["direction"] == "bull" else "PUT"
        lines.append(
            f"| {dt} | {dir_} | {t['reason']} "
            f"| ${t['entry_price']:.2f} | {t['pnl_pct']:+.2f}% | {t['exit_reason']} |"
        )

    lines += [
        "",
        "---",
        "",
        "## Interpretation",
        "",
        "> **Important:** P&L figures use a simplified delta-proxy model, not real option",
        "> chain data. They indicate *signal direction quality*, not exact dollar returns.",
        "> For real option P&L, integrate Polygon Historical Options or ThetaData.",
        "",
        "### What to look for",
        "- **Profit factor > 1.5** → signal has edge worth pursuing",
        "- **Win rate > 50% + avg win > avg loss** → directional edge confirmed",
        "- **Sharpe > 0.5** → risk-adjusted returns acceptable",
        "- **Beat buy-and-hold** → the system adds value vs passive exposure",
        "",
        "### Next steps if edge looks weak",
        "1. Raise `bull_score` / `bear_score` threshold from 3 → 4",
        "2. Require `vol_ratio > 1.5` (only trade on volume spikes)",
        "3. Add regime filter (skip choppy days: SPY range < 0.5%)",
        "4. Test 0-DTE vs 7-DTE on the same signals",
        "",
        f"_SPY Auto Trader Backtest — {today}_",
    ]
    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────
def run_backtest(symbol: str, days: int) -> dict:
    try:
        import yfinance as yf
    except ImportError:
        print("yfinance not installed. Run: venv/bin/pip install yfinance")
        sys.exit(1)

    print(f"\n{'─'*50}")
    print(f"  {symbol} — {days} day backtest")
    print(f"{'─'*50}")

    end   = datetime.now(ET)
    start = end - timedelta(days=days)

    print(f"→ Downloading 5-min bars ({start.date()} → {end.date()})…")
    ticker = yf.Ticker(symbol)
    # yfinance max for 5-min is 60 days; for longer periods use 1-day bars
    if days <= 59:
        df = ticker.history(start=start, end=end, interval="5m", auto_adjust=True)
    else:
        # Use 1-day bars for signal replay on longer periods
        df = ticker.history(start=start, end=end, interval="1d", auto_adjust=True)
        print("  [info] Using 1-day bars (5-min only available for 60 days via yfinance)")

    if df.empty:
        print(f"  [warn] No data for {symbol}")
        return {}

    df.index = pd.DatetimeIndex(df.index).tz_convert(ET)
    df = df.dropna(subset=["Close", "Volume"])
    print(f"  {len(df)} bars loaded")

    # Baseline: underlying buy-and-hold
    baseline_pct = (df["Close"].iloc[-1] / df["Close"].iloc[0] - 1) * 100 if len(df) > 1 else 0.0

    # Group by day and replay signals
    all_trades: list[dict] = []
    trading_days = df.groupby(df.index.date)
    for day, day_df in trading_days:
        if len(day_df) < 10:
            continue
        sigs   = _generate_signals(day_df)
        trades = _option_pnl(float(day_df["Close"].iloc[0]), sigs, day_df)
        all_trades.extend(trades)

    print(f"  Signals fired: {len(all_trades)}")

    m = _metrics(all_trades)
    report = _report(symbol, days, all_trades, m, baseline_pct)

    out_path = RESULTS_DIR / f"{date.today().isoformat()}_{symbol}.md"
    out_path.write_text(report)
    print(f"  Report → {out_path}")

    # Print quick summary
    print(f"  Win rate: {m.get('win_rate', 0):.1f}%  "
          f"PF: {m.get('profit_factor', 'n/a')}  "
          f"Expectancy: {m.get('expectancy', 0):+.2f}%  "
          f"Sharpe: {m.get('sharpe', 0):.2f}")
    print(f"  Signal P&L: {m.get('total_pnl', 0):+.2f}%  vs  "
          f"Buy-and-hold: {baseline_pct:+.2f}%")

    return {"symbol": symbol, "metrics": m, "trades": len(all_trades),
            "baseline": baseline_pct}


def _summary_report(results: list[dict]) -> str:
    today = date.today().isoformat()
    lines = [
        f"# Backtest Summary — {today}",
        "",
        "| Symbol | Trades | Win% | PF | Expectancy | Sharpe | MaxDD | Signal P&L | vs Buy&Hold |",
        "|--------|--------|------|----|-----------|--------|-------|-----------|------------|",
    ]
    for r in results:
        m = r.get("metrics", {})
        lines.append(
            f"| {r['symbol']} | {r['trades']} | {m.get('win_rate',0):.1f}% "
            f"| {m.get('profit_factor','n/a')} | {m.get('expectancy',0):+.2f}% "
            f"| {m.get('sharpe',0):.2f} | {m.get('max_dd',0):.2f}% "
            f"| {m.get('total_pnl',0):+.2f}% | {r.get('baseline',0):+.2f}% |"
        )
    lines += [
        "",
        "---",
        "",
        "## Key thresholds",
        "- **PF > 1.5** = has edge | **PF 1.0–1.5** = marginal | **PF < 1.0** = losing",
        "- **Sharpe > 0.5** = acceptable risk-adjusted returns",
        "- **Signal P&L > Buy&Hold** = strategy adds value over passive",
        "",
        "_Option P&L uses delta-proxy approximation. Treat as signal quality indicator._",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SPY Auto Trader backtest harness")
    parser.add_argument("--symbol",  default="SPY",
                        help="Single symbol (default: SPY)")
    parser.add_argument("--symbols", nargs="+",
                        help="Multiple symbols (overrides --symbol)")
    parser.add_argument("--days",    type=int, default=90,
                        help="Lookback in calendar days (default: 90, max 5min: 59)")
    args = parser.parse_args()

    symbols = args.symbols or [args.symbol]
    print(f"\n{'='*50}")
    print(f"  SPY Auto Trader — Backtest Harness")
    print(f"  Symbols: {', '.join(symbols)} | Days: {args.days}")
    print(f"{'='*50}")

    results = []
    for sym in symbols:
        r = run_backtest(sym, args.days)
        if r:
            results.append(r)

    if len(results) > 1:
        summary = _summary_report(results)
        summary_path = RESULTS_DIR / "summary.md"
        summary_path.write_text(summary)
        print(f"\nSummary → {summary_path}")
        print(summary)
    elif results:
        m = results[0]["metrics"]
        print(f"\n✅ Done. Profit factor: {m.get('profit_factor','n/a')} | "
              f"Win rate: {m.get('win_rate',0):.1f}% | "
              f"Sharpe: {m.get('sharpe',0):.2f}")
