#!/usr/bin/env python3.11
"""
screener_engine.py — Live intraday screener for the Screener tab.

════════════════════════════════════════════════════════════
DEEP BOOK READING — key citations incorporated (2026-05-24)
════════════════════════════════════════════════════════════
Day-Trading Criteria:
  Aziz (HTDT p.31):        Gap+Vol — gap ≥$1 pre-mkt, rel-vol > 1.5× → Alpha Predator
  Connors/Alvarez (2013):  RSI(2) < 10 → 66.4% bull directional accuracy (multi-day)
  Elder (Step-by-Step p.47): Impulse System — EMA13+MACD-H direction filter:
                               Green = both rising  → buy permitted
                               Red   = both falling → NO LONGS (censorship system)
  Elder (New TfaL p.112):  Force Index 2-day EMA < 0 during uptrend = bargain entry
  O'Neill/Morales (p.128): Pocket Pivot = vol > any down-day in prior 10 sessions
  Bernstein (30 Days p.18): Setup→Trigger→Follow-through required for every trade
  Raschke/Williams (HP p.38): 80-20 bar → next-day reversal; first-hour range breakout
  Ways of Trade (p.44):    Wet climate = heavy volume, 9:30-11 AM thunder window
  Volatile Markets (p.57): Bull Flag — entry above flag high on rising volume; stop below flag

Options Criteria:
  Volatile Markets (p.104): IV > HV → options expensive → use credit/debit SPREAD
                             IV < HV → options cheap    → ATM call/put acceptable
  Keene on Market (2013):  HIMCRIBBIT — Historical/Implied/Measured move + Chart +
                             Risk/Reward/Breakeven/Time/Target before every trade
  Option Spread (p.30):    Vertical spreads = limited-risk directional when IV is elevated
  Think Like Option (p.47): IV = "price of uncertainty"; 1-SD daily move = IV/16
  Put Option Strategies:   Bear put spread for directional downside; insurance put for hedge

BACKTESTED setup criteria (2yr, 25 symbols, next-day open→close):
  ✅ Breakout   PF 1.88  Win 51.5%  AvgRet +0.78%  Dir 51.5%  (new 50d high + RSI55-70 + rel-vol>1.3)
  ✅ RSI Dip    PF 1.41  Win 53.7%  AvgRet +0.42%  Dir 53.7%  (RSI14 < 35, oversold mean-revert)
  ✅ Gap+Vol    PF 1.37  Win 50.6%  AvgRet +0.41%  Dir 50.6%  (gap>1% + rel-vol>1.5×)
  ✅ Bull Flag  PF 1.44  Win 61.5%  AvgRet +0.45%  Dir 61.5%  (Volatile Markets p.57 + Aziz p.61)
  ❌ Momentum   PF 1.00  Win 50.1%  AvgRet +0.00%  REMOVED — no edge
  ❌ VWAP Bounce PF 0.85 Win 48.9%  AvgRet -0.15%  REMOVED — negative edge

ELDER IMPULSE FILTER (2yr backtest, same universe):
  RSI Dip  + Impulse-Red   PF 1.82 (beats All=1.41!) — mean-reversion IMPROVES in Red
  RSI Dip  + Impulse-Green PF 1.76 — also excellent
  Gap+Vol  + Impulse-Green PF 1.29 | Red PF 1.54
  Breakout + Impulse-Green PF 1.67 (never appears in Red — trend requires Green/Blue)
  Bull Flag+ Impulse-Green PF 2.29 (never appears in Red — momentum requires Green/Blue)
  KEY: Impulse-Red is NOT a veto for MEAN-REVERSION (RSI Dip). It IS a veto for MOMENTUM setups.

OPTIONS direction accuracy (same backtest):
  ✅ Connors RSI(2) < 10  66.4% directional (multi-day, PF 1.32)
  ✅ Bull Flag            61.5% directional (next-day) — highest of all intraday setups
  ✅ RSI Dip              53.7% directional (next-day)
  ✅ Breakout             51.5% directional (next-day)
  ✅ Gap+Vol              50.6% directional (next-day)

Top performers per validated setup (avg next-day return):
  RSI Dip  : COHR+2.25% HOOD+2.11% LRCX+1.40% CVNA+1.37% NVDA+1.34%
  Gap+Vol  : APP+3.24%  SMCI+2.42% CVNA+1.87% TXN+1.31%  QCOM+1.21%
  Breakout : WDC+4.03%  MU+3.52%   PLTR+2.47% CVNA+2.09% ON+1.99%
  Bull Flag: TXN+3.60%  INTC+2.56% HOOD+1.96% SMCI+1.83% TSLA+0.19%

Auto-refreshes every 90 s during market hours via SocketIO.
"""
from __future__ import annotations
import json
import math
import threading
import time
from datetime import datetime, date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import numpy as np

ET = ZoneInfo("America/New_York")

# ── Universe (15-symbol selection, expanded 2026-05-31 per operator request) ──
# Was trimmed 25 → 5 (2026-05-30) for hub responsiveness; operator wants the
# tables fuller (up to 15 rows each), so we run 15 liquid names. Tradeoff: each
# refresh now does ~6-9s of pandas/yfinance work (vs 2-3s at 5 names). The
# refresh runs in a background greenlet on a 120s cache TTL, so the occasional
# hub lag during a refresh is acceptable for a single-user paper dashboard.
# To go back to the fast 5-symbol cycle, restore the prior list.
#
# All 15 carry _SECTOR + TOP_PERFORMERS metadata so labelling/badges stay correct.
DAY_TRADING_UNIVERSE = [
    "INTC", "AMD", "NVDA", "PLTR", "HOOD",          # original fast-5
    "TSLA", "AVGO", "MU", "QCOM", "ORCL",           # +liquidity / semis / tech
    "CRM", "SMCI", "ANET", "APP", "CVNA",           # +SaaS / servers / net / momentum
    "NOW", "LRCX", "AMAT", "TXN", "COHR",           # +SaaS / semi-equip / photonics
    # ── ETFs (operator request 2026-05-31): broad index + key sectors + commod/bond
    "SPY", "QQQ", "IWM", "DIA",                     # broad index
    "XLF", "XLE", "XLK", "XLV", "SMH",              # key sectors / semis
    "GLD", "TLT",                                   # commodity / bond diversifiers
]   # stocks + ETFs; table fills toward the 15-row cap (not every symbol
    # produces a setup row on a given day)

_SECTOR = {
    "NVDA":"Semis","INTC":"Semis","AMD":"Semis","MU":"Semis",
    "QCOM":"Semis","ON":"Semis","AVGO":"Semis","LRCX":"Semi Equip",
    "AMAT":"Semi Equip","MCHP":"Semis","GLW":"Tech",
    "TSLA":"EV/Tech","PLTR":"AI","ORCL":"Tech","NOW":"Tech",
    "ANET":"Net","COHR":"Photonics","SMCI":"Servers","WDC":"Storage",
    "CRM":"SaaS","TXN":"Semis","APP":"AdTech","VRT":"Industrials",
    "HOOD":"Fintech","CVNA":"Retail",
    # ETFs
    "SPY":"ETF-Index","QQQ":"ETF-Index","IWM":"ETF-Index","DIA":"ETF-Index",
    "XLF":"ETF-Fin","XLE":"ETF-Energy","XLK":"ETF-Tech","XLV":"ETF-Health",
    "SMH":"ETF-Semis","GLD":"ETF-Gold","TLT":"ETF-Bonds",
}

# Backtested metrics per setup (from backtest_screener_criteria.py, 2026-05-24)
BT_METRICS = {
    # ── Validated setups (PF > 1.2, 2yr backtest 25 symbols, run 2026-05-24) ──
    "Breakout":    {"pf": 1.88, "win_pct": 51.5, "avg_ret": 0.781, "dir_pct": 51.5, "n": 33},
    "Bull Flag":   {"pf": 1.44, "win_pct": 61.5, "avg_ret": 0.445, "dir_pct": 61.5, "n": 13},
    "RSI Dip":     {"pf": 1.41, "win_pct": 53.7, "avg_ret": 0.421, "dir_pct": 53.7, "n": 870},
    "Gap+Vol":     {"pf": 1.37, "win_pct": 50.6, "avg_ret": 0.408, "dir_pct": 50.6, "n": 243},
    # ── No-edge setups (kept for label display only — not in VALID_SETUPS) ───
    "Momentum":    {"pf": 1.00, "win_pct": 50.1, "avg_ret": 0.002, "dir_pct": 50.1, "n": 1566},
    "VWAP Bounce": {"pf": 0.85, "win_pct": 48.9, "avg_ret":-0.148, "dir_pct": 48.9, "n": 380},
    "Neutral":     {"pf": 0.00, "win_pct": 0,    "avg_ret": 0,     "dir_pct": 50.0, "n": 0},
}

# Top performers per setup (from backtest — highlight these in the UI)
TOP_PERFORMERS = {
    "RSI Dip":   ["COHR", "HOOD", "LRCX", "CVNA", "NVDA"],
    "Gap+Vol":   ["APP",  "SMCI", "CVNA", "TXN",  "QCOM"],
    "Breakout":  ["WDC",  "MU",   "PLTR", "CVNA", "ON"],
    "Bull Flag": ["TXN",  "INTC", "HOOD", "SMCI", "TSLA"],
}

# Validated = backtested PF > 1.2  (Bull Flag PF=1.44 confirmed 2026-05-24)
VALID_SETUPS = {"Breakout", "RSI Dip", "Gap+Vol", "Bull Flag"}

# ── Intraday strategy per setup (from Polygon 5yr backtest §BT1) ──────────────
SETUP_STRATEGY = {
    "Breakout": (
        "SAME-DAY edge (signal-day PF=28.42, next-day PF=0.84 — edge gone by tomorrow). "
        "Enter intraday NOW while breakout is in progress. "
        "Hold 60–90 min from entry. "
        "Stop 1–1.5% below entry. Target 2–3%. "
        "60% hit +1% within 30min, 80% within 60min."
    ),
    "Bull Flag": (
        "Intraday 5-min setup — buy the tight consolidation after a surge day. "
        "Enter on flag break (today's range < 50% of surge bar). "
        "Short hold: 15 min max. "
        "Stop 1.5% below flag low. Target 1% above flag high. "
        "Best stop+target: 1.5% stop / 1% target → PF=1.04."
    ),
    "RSI Dip": (
        "Mean-reversion — stock still falling on signal day (same-day PF=0.45). "
        "Do NOT enter today. Best entry: next-day open (PF=1.08). "
        "Hold to EOD for full mean-reversion (EOD PF=1.01). "
        "Wide stop 2%+ — tight stops choke mean-reversion. "
        "daily_trader.py handles overnight entry automatically."
    ),
    "Gap+Vol": (
        "Gap continuation — edge persists both days (signal-day PF=2.52, next-day PF=1.11). "
        "Enter at 9:35 open. Hold 120 min or EOD for full drift. "
        "Stop 1.5–2% below open. Target 3%+. "
        "71% hit +1% within 30min, 85% within 60min."
    ),
    "Momentum": "No backtested directional edge — watch only, do not trade.",
    "VWAP Bounce": "No backtested directional edge — watch only, do not trade.",
}

CACHE_TTL_MARKET = 120   # seconds during market hours. With the trimmed
                         # 5-symbol universe each refresh is ~2-3s so 2-min
                         # cadence stays responsive (vs 300s/5-min before
                         # which was a workaround for the 25-symbol stalls).
CACHE_TTL_CLOSED = 600   # seconds after hours

_cache: dict = {"dt": [], "options": [], "ts": 0.0, "market_open": False}
_cache_lock   = threading.Lock()
_refresh_lock = threading.Lock()


# ── Market hours ──────────────────────────────────────────────────────────────
def _is_market_open() -> bool:
    now = datetime.now(ET)
    if now.weekday() > 4:
        return False
    h, m = now.hour, now.minute
    return (9, 30) <= (h, m) < (16, 0)


# ── Indicators ────────────────────────────────────────────────────────────────
def _rsi(s: pd.Series, n: int) -> float:
    d = s.diff()
    g = d.clip(lower=0).rolling(n).mean()
    l = (-d).clip(lower=0).rolling(n).mean()
    rs = g / l.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    v = rsi.dropna()
    return round(float(v.iloc[-1]), 1) if not v.empty else 50.0


def _rsi2(s: pd.Series) -> float:
    return _rsi(s, 2)


def _ema(s: pd.Series, n: int) -> float:
    v = s.ewm(span=n, adjust=False).mean()
    return float(v.iloc[-1]) if not v.empty else float(s.iloc[-1])


def _hv_annual(closes: pd.Series, n: int = 20) -> float:
    rets = np.log(closes / closes.shift(1)).dropna()
    if len(rets) < n:
        return 0.0
    return round(float(rets.tail(n).std() * math.sqrt(252) * 100), 1)


def _vwap(df: pd.DataFrame) -> float:
    tp = (df["High"] + df["Low"] + df["Close"]) / 3
    cv = df["Volume"].cumsum()
    return float((tp * df["Volume"]).cumsum().iloc[-1] / cv.iloc[-1]) if cv.iloc[-1] else float(df["Close"].iloc[-1])


def _impulse(daily: pd.DataFrame) -> str:
    """Elder Impulse System — Green/Blue/Red.

    Source: 'Step by Step Trading' (Elder 2015) p.47:
      Green:  EMA13 rising AND MACD-Histogram rising → buy permitted
      Red:    EMA13 falling AND MACD-Histogram falling → NO LONGS (censorship)
      Blue:   mixed signals → neutral, watch

    'The Impulse System isn't a trading system—it's a censorship system.
    It doesn't tell you what to do—it shows you when NOT to trade.' — Elder
    """
    if len(daily) < 30:
        return "Blue"
    ema13  = daily["Close"].ewm(span=13, adjust=False).mean()
    ema26  = daily["Close"].ewm(span=26, adjust=False).mean()
    macd_l = ema13 - ema26
    signal = macd_l.ewm(span=9, adjust=False).mean()
    macd_h = macd_l - signal

    ema13_up  = float(ema13.iloc[-1])  > float(ema13.iloc[-2])
    macdh_up  = float(macd_h.iloc[-1]) > float(macd_h.iloc[-2])

    if ema13_up and macdh_up:
        return "Green"
    if (not ema13_up) and (not macdh_up):
        return "Red"
    return "Blue"


def _force_index_2d(daily: pd.DataFrame) -> float:
    """Elder Force Index 2-day EMA (FI2).

    Source: 'Step by Step Trading' (Elder 2015) p.39-41:
      FI = (Close_today − Close_yesterday) × Volume_today
      'Once you've made a decision to buy during an uptrend, a decline
      of the 2-day EMA of Force Index below zero identifies a bargain area.'
    Positive FI2 = bulls in control; Negative = bears, potential dip-buy entry.
    """
    if len(daily) < 5:
        return 0.0
    fi    = daily["Close"].diff() * daily["Volume"]
    fi2   = fi.ewm(span=2, adjust=False).mean()
    return round(float(fi2.iloc[-1]), 0)


def _pocket_pivot(daily: pd.DataFrame) -> bool:
    """O'Neill/Morales Pocket Pivot — early base buy signal.

    Source: 'Trade Like an O'Neil Disciple' (Morales/Kacher 2010) p.132:
      'Today's volume must exceed the highest down-volume day in the
      prior 10 trading sessions.'
    Used as an early accumulation signal before a full breakout.
    """
    if len(daily) < 12:
        return False
    last10 = daily.tail(11).iloc[:-1]   # 10 sessions before today
    down_days = last10[last10["Close"] < last10["Open"]]
    if down_days.empty:
        return True   # no down days → any volume is a pocket pivot
    max_down_vol = float(down_days["Volume"].max())
    today_vol    = float(daily["Volume"].iloc[-1])
    today_up     = float(daily["Close"].iloc[-1]) >= float(daily["Open"].iloc[-1])
    return today_up and today_vol > max_down_vol


def _nearest_expiry(dte_min: int = 21) -> tuple[str, int]:
    """Return (expiry_str, dte) for nearest weekly Friday >= dte_min DTE."""
    today = date.today()
    for off in range(dte_min, dte_min + 14):
        d = today + timedelta(days=off)
        if d.weekday() == 4:
            return d.strftime("%Y-%m-%d"), off
    d = today + timedelta(days=dte_min)
    return d.strftime("%Y-%m-%d"), dte_min


# ── Setup classification (backtested rules only) ──────────────────────────────
def _classify_setup(daily: pd.DataFrame, price: float, rel_vol: float,
                    gap_pct: float, rsi14: float) -> str:
    """
    Apply the FOUR backtested-valid setup criteria (all PF > 1.2).
    Momentum (PF=1.00) and VWAP Bounce (PF=0.85) deliberately excluded.

    Priority order matches backtest classification order:
      1. Breakout  PF 1.88 — highest PF, trend-continuation
      2. Gap+Vol   PF 1.37 — pre-market gap with volume confirm
      3. RSI Dip   PF 1.41 — mean-reversion from oversold
      4. Bull Flag PF 1.44 — consolidation after surge (lowest priority in backtest)
    """
    ema20  = _ema(daily["Close"], 20)
    high50 = float(daily["Close"].tail(51).iloc[:-1].max()) if len(daily) >= 51 else price

    # 1. Breakout: PF 1.88 — new 50-day high + RSI55-70 + rel-vol > 1.3
    if price > high50 and 55 <= rsi14 <= 75 and rel_vol > 1.3:
        return "Breakout"

    # 2. Gap+Vol: PF 1.37 — gap > 1% AND rel-vol > 1.5× (Aziz p.31)
    if gap_pct > 1.0 and rel_vol > 1.5:
        return "Gap+Vol"

    # 3. RSI Dip: PF 1.41 — RSI14 < 35, oversold mean-reversion
    if rsi14 < 35:
        return "RSI Dip"

    # 4. Bull Flag: PF 1.44, Dir 61.5% — surge + tight consolidation
    #    (Volatile Markets Made Easy p.57, Aziz p.61)
    #    Surge bar: prev day OR 2 days ago up > 2% and closed in top 40% of range
    #    Consolidation: today's range < 50% of surge bar's range
    #    Filter: daily RSI14 50-75 (momentum not overbought) + rel_vol ≥ 1.2
    if len(daily) >= 3 and rel_vol >= 1.2:
        prev_o  = float(daily["Open"].iloc[-2])
        prev_c  = float(daily["Close"].iloc[-2])
        prev_h  = float(daily["High"].iloc[-2])
        prev_l  = float(daily["Low"].iloc[-2])
        prev2_o = float(daily["Open"].iloc[-3])
        prev2_c = float(daily["Close"].iloc[-3])
        today_h = float(daily["High"].iloc[-1])
        today_l = float(daily["Low"].iloc[-1])

        prev_chg  = (prev_c - prev_o) / prev_o * 100 if prev_o > 0 else 0
        prev2_chg = (prev2_c - prev2_o) / prev2_o * 100 if prev2_o > 0 else 0
        surge_any = (prev_chg > 2.0) or (prev2_chg > 2.0)

        prev_range  = max(prev_h - prev_l, 0.001)
        today_range = today_h - today_l
        tight_flag  = today_range < 0.5 * prev_range

        # Flagpole quality: surge bar must close in top 40% of its range
        flagpole  = (prev_c - prev_l) / prev_range
        strong_up = flagpole > 0.6

        rsi14_d = _rsi(daily["Close"], 14)  # daily RSI14 for Bull Flag check
        if surge_any and tight_flag and strong_up and 50 <= rsi14_d <= 75:
            return "Bull Flag"

    return "Neutral"


# ── Per-symbol fetch ──────────────────────────────────────────────────────────
def _fetch_symbol(sym: str) -> dict | None:
    try:
        import yfinance as yf
        t = yf.Ticker(sym)

        # 60-day daily for indicators + HV
        daily = t.history(period="60d", interval="1d", auto_adjust=True, actions=False)
        if daily is None or len(daily) < 20:
            return None

        adv30      = float(daily["Volume"].tail(30).mean())
        hv20       = _hv_annual(daily["Close"], 20)
        rsi14_d    = _rsi(daily["Close"], 14)   # daily RSI14
        rsi2_d     = _rsi2(daily["Close"])       # daily RSI2 (Connors signal)
        ema20_d    = _ema(daily["Close"], 20)
        ema13_d    = _ema(daily["Close"], 13)   # Elder value-zone EMA
        impulse    = _impulse(daily)             # Elder Impulse System (Green/Blue/Red)
        fi2d       = _force_index_2d(daily)      # Elder Force Index 2-day EMA
        pkt_pivot  = _pocket_pivot(daily)        # O'Neill Pocket Pivot flag
        prev_close = float(daily["Close"].iloc[-2]) if len(daily) >= 2 else None

        # Intraday 5-min bars for VWAP + live price
        intra = t.history(period="1d", interval="5m", auto_adjust=True, actions=False)
        if intra is None or intra.empty:
            # Fall back to latest daily bar
            price     = float(daily["Close"].iloc[-1])
            day_vol   = int(daily["Volume"].iloc[-1])
            vwap      = price
            rsi14_i   = rsi14_d
        else:
            price   = float(intra["Close"].iloc[-1])
            day_vol = int(intra["Volume"].sum())
            vwap    = _vwap(intra)
            rsi14_i = _rsi(intra["Close"], 14)  # intraday RSI14 (5m bars)

        chg_pct  = round((price - prev_close) / prev_close * 100, 2) if prev_close and prev_close > 0 else 0.0
        open_day = float(intra["Open"].iloc[0]) if (intra is not None and not intra.empty) else price
        gap_pct  = round((open_day - prev_close) / prev_close * 100, 2) if prev_close else 0.0
        vwap_diff = round((price - vwap) / vwap * 100, 2) if vwap > 0 else 0.0
        high_d   = float(daily["High"].tail(1).iloc[-1])
        low_d    = float(daily["Low"].tail(1).iloc[-1])
        day_range = round((high_d - low_d) / price * 100, 1) if price > 0 else 0.0

        # Relative volume
        now   = datetime.now(ET)
        mkt_s = now.replace(hour=9, minute=30, second=0, microsecond=0)
        mkt_e = now.replace(hour=16, minute=0, second=0, microsecond=0)
        elapsed = max(0.05, min(1.0, (now.timestamp() - mkt_s.timestamp()) /
                                     (mkt_e.timestamp() - mkt_s.timestamp())))
        rel_vol = round(day_vol / (adv30 * elapsed), 2) if adv30 > 0 else 1.0

        setup = _classify_setup(daily, price, rel_vol, gap_pct, rsi14_i)

        # Is this symbol a top performer for this setup? (backtest-sourced)
        is_top = sym in TOP_PERFORMERS.get(setup, [])
        bt     = BT_METRICS.get(setup, BT_METRICS["Neutral"])

        # ── Reason why this setup was triggered (live indicator values) ──────
        high50_r = float(daily["Close"].tail(51).iloc[:-1].max()) if len(daily) >= 51 else price
        if setup == "Breakout":
            imp_note = {"Green": "🟢 Impulse Green (buy zone)", "Red": "🔴 Impulse Red (caution)", "Blue": "🔵 Impulse Blue (neutral)"}.get(impulse, impulse)
            reason = (f"Price ${price:.2f} > 50d High ${high50_r:.2f} · "
                      f"RSI14={rsi14_i:.0f} (zone 55–75) · "
                      f"RelVol={rel_vol:.1f}× (thresh >1.3×) · {imp_note}")
        elif setup == "Gap+Vol":
            imp_note = {"Green": "🟢 Impulse Green", "Red": "🔴 Impulse Red", "Blue": "🔵 Impulse Blue"}.get(impulse, impulse)
            reason = (f"Gap={gap_pct:+.1f}% at open (thresh >1%) · "
                      f"RelVol={rel_vol:.1f}× (thresh >1.5×) · "
                      f"RSI14={rsi14_i:.0f} · ADV30={adv30/1e6:.1f}M · {imp_note}")
        elif setup == "RSI Dip":
            fi_note = "FI2d<0 (bargain entry — Elder p.39)" if fi2d < 0 else f"FI2d={fi2d:+.0f}"
            pp_note = " · 📌 Pocket Pivot" if pkt_pivot else ""
            imp_note = "🔴 Impulse Red (sustained sell = BETTER dip entry, PF=1.82)" if impulse == "Red" else ("🟢 Impulse Green (also good, PF=1.76)" if impulse == "Green" else "🔵 Impulse Blue")
            reason = (f"RSI14={rsi14_i:.0f} < 35 (oversold mean-revert) · "
                      f"RSI2(daily)={rsi2_d:.1f} · {fi_note}{pp_note} · {imp_note}")
        elif setup == "Bull Flag":
            if len(daily) >= 3:
                prev_o2 = float(daily["Open"].iloc[-2]); prev_c2 = float(daily["Close"].iloc[-2])
                surge2  = (prev_c2 - prev_o2) / prev_o2 * 100 if prev_o2 > 0 else 0.0
                reason  = (f"Surge prev day {surge2:+.1f}% · "
                           f"Today range tight · "
                           f"RSI14={rsi14_i:.0f} (zone 50–75) · RelVol={rel_vol:.1f}×")
            else:
                reason = f"Bull Flag — RSI14={rsi14_i:.0f} · RelVol={rel_vol:.1f}×"
        else:
            reason = (f"No backtested edge today · "
                      f"RSI14={rsi14_i:.0f} · RelVol={rel_vol:.1f}× · Gap={gap_pct:+.1f}%")

        strategy = SETUP_STRATEGY.get(setup, "No strategy — watch only.")

        return {
            "sym":       sym,
            "sector":    _SECTOR.get(sym, "Tech"),
            "price":     round(float(price), 2),
            "chg_pct":   float(chg_pct),
            "gap_pct":   float(gap_pct),
            "rel_vol":   float(rel_vol),
            "rsi14":     float(rsi14_i),
            "rsi14_d":   float(rsi14_d),     # daily RSI14
            "rsi2_d":    float(rsi2_d),      # daily RSI2 (Connors 66.4%)
            "vwap":      round(float(vwap), 2),
            "vwap_diff": float(vwap_diff),
            "day_range": float(day_range),
            "hv20":      float(hv20),
            "ema20_d":   round(float(ema20_d), 2),
            "ema13_d":   round(float(ema13_d), 2),  # Elder value-zone EMA
            "adv30m":    round(float(adv30) / 1e6, 1),
            "setup":     setup,
            "valid":     setup in VALID_SETUPS,
            "is_top":    bool(is_top),
            "bt_pf":     float(bt["pf"]),
            "bt_win":    float(bt["win_pct"]),
            "bt_ret":    float(bt["avg_ret"]),
            "bt_dir":    float(bt["dir_pct"]),
            "bt_n":      int(bt["n"]),
            # ── Elder book-sourced indicators (2026-05-24 deep read) ──────────
            "impulse":   impulse,            # Green/Blue/Red (Elder Step-by-Step p.47)
            "fi2d":      float(fi2d),        # Force Index 2d EMA (Elder p.39)
            "pkt_pivot": bool(pkt_pivot),    # O'Neill Pocket Pivot (Morales p.132)
            # ── Human-readable detail for UI expandable rows ──────────────────
            "reason":    reason,             # Why this setup was triggered (live values)
            "strategy":  strategy,           # How to trade it (from Polygon 5yr backtest §BT1)
        }
    except Exception:
        return None


# ── Options opportunities ─────────────────────────────────────────────────────
def _build_options(dt_rows: list[dict], daily_positions: list[dict]) -> list[dict]:
    """
    Options opportunities ranked by validated directional accuracy.

    Book-sourced selection framework (Keene 2013 HIMCRIBBIT + Volatile Markets p.104):
      H  = Historical volatility (HV20)
      I  = Implied volatility   (proxy: IVR from daily strategy or HV estimate)
      M  = Measured move target (50% of prior impulse — Volatile Markets p.64)
      C  = Chart (setup classification + Impulse System filter)
      R  = Risk per trade (max $400 — Elder 2% rule)
      R  = Reward:Risk ≥ 2:1 (Aziz rule p.22)
      B  = Breakeven (debit ≤ move expected)
      T  = Time (21-30 DTE — avoid last-month rapid theta decay)
      T  = Target (50% of flagpole move or prior day's range)

    Structure rule (Volatile Markets Made Easy p.104):
      HV ≤ 45% → ATM Call cheap enough → buy outright
      HV > 45% → debit call spread limits theta risk

    Elder Impulse filter (Step-by-Step p.47):
      Impulse = Red → append ⛔ warning; still show but flag as elevated risk

    Ranked by directional accuracy:
      1. Connors RSI(2) < 10  → 66.4% directional (PF 1.32, proven)
      2. Bull Flag            → 61.5% directional (PF 1.44, backtested — best intraday)
      3. RSI Dip intraday     → 53.7% directional (PF 1.41, backtested)
      4. Breakout             → 51.5% directional (PF 1.88, backtested)
      5. Gap+Vol              → 50.6% directional (PF 1.37, backtested)
    Momentum and VWAP Bounce excluded — no directional edge.

    RSI Dip Impulse note (backtest insight):
      Impulse Red PF=1.82 > Green PF=1.76 > All PF=1.41 for RSI Dip.
      Red Impulse = sustained selling = better mean-reversion opportunity.
      Do NOT apply Red-veto to RSI Dip. Apply it only to momentum setups.
    """
    rows: list[dict] = []
    seen: set[str] = set()
    expiry, dte = _nearest_expiry(21)

    # ── Source A: Connors RSI(2) daily strategy signals ───────────────────────
    for pos in (daily_positions or []):
        if pos.get("status") not in ("signal", "pending"):
            continue
        sym = pos.get("sym", "").upper()
        if sym in seen:
            continue
        seen.add(sym)
        direction = pos.get("direction", "bull")
        opt_type  = "Call" if direction == "bull" else "Put"
        ivr_val   = pos.get("ivr") or "?"
        structure = pos.get("structure") or ("ATM Call" if str(ivr_val) == "?" or
                    (isinstance(ivr_val, (int, float)) and ivr_val < 30) else "Debit Spread")
        rsi2_val = pos.get("rsi2")
        rsi2_str = f"{rsi2_val:.1f}" if isinstance(rsi2_val, float) else "<10"
        opt_reason = (
            f"Connors RSI(2)={rsi2_str} < 10 → 66.4% directional accuracy (PF=1.32, 2yr backtest) · "
            f"{opt_type} for {'bullish' if direction=='bull' else 'bearish'} mean-reversion · "
            f"IVR {ivr_val} → {structure}"
        )
        opt_strategy = (
            f"BTO 1 ATM {opt_type}, exp {expiry} ({dte}d). "
            f"Stop: exit if option loses 50% of premium. "
            f"Target: 100% gain or hold to day 3–5 for mean-reversion. "
            f"Max risk: ${int(pos.get('risk_budget', 400))}. "
            f"Connors rule: RSI(2) < 10 signals sharp multi-day reversal (Connors/Alvarez 2013 p.44)."
        )
        rows.append({
            "rank":      1,
            "source":    "Connors RSI(2) Daily",
            "sym":       sym,
            "direction": "▲ Bull" if direction == "bull" else "▼ Bear",
            "signal":    f"RSI2={rsi2_str}" if isinstance(rsi2_val, float) else "RSI2 < 10",
            "opt_type":  opt_type,
            "structure": structure,
            "expiry":    expiry,
            "dte":       dte,
            "ivr":       str(ivr_val),
            "max_risk":  int(pos.get("risk_budget", 400)),
            "dir_pct":   66.4,
            "pf":        1.32,
            "badge":     "⭐ Proven",
            "confidence":"66.4% hit · PF 1.32 · 2yr backtest",
            "action":    "✅ BUY",
            "reason":    opt_reason,
            "strategy":  opt_strategy,
        })

    # ── Source B: Intraday validated setups → directional options ────────────
    # Rank by directional accuracy:
    #   Bull Flag 61.5% > RSI Dip 53.7% > Breakout 51.5% > Gap+Vol 50.6%
    setup_rank = {"Bull Flag": 2, "RSI Dip": 3, "Breakout": 4, "Gap+Vol": 5}
    for row in sorted(dt_rows, key=lambda r: setup_rank.get(r["setup"], 9)):
        sym   = row["sym"]
        setup = row["setup"]
        if setup not in VALID_SETUPS or sym in seen:
            continue
        seen.add(sym)
        bt       = BT_METRICS[setup]
        hv       = row.get("hv20", 30)
        impulse  = row.get("impulse", "Blue")
        pkt_piv  = row.get("pkt_pivot", False)
        fi2d     = row.get("fi2d", 0)
        is_top   = row.get("is_top", False)

        # Structure (Volatile Markets Made Easy p.104):
        # HV ≤ 45% → options cheap → ATM call acceptable
        # HV > 45% → spread to limit theta risk
        structure   = "Debit Call Spread" if hv > 45 else "ATM Call"
        struct_note = (f"HV={hv:.0f}%>45%→spread" if hv > 45
                       else f"HV={hv:.0f}%≤45%→ATM")

        # Elder Impulse filter — differentiated by setup TYPE (2yr backtest insight):
        #   RSI Dip (mean-reversion): Red PF=1.82 > Green PF=1.76 > All PF=1.41
        #     → Red Impulse is NORMAL for dip-buy setups (selling pressure = dip entry)
        #   Breakout / Bull Flag / Gap+Vol (momentum): Never appear in Red Impulse naturally
        #     → If somehow Red, it's a warning
        impulse_flag = ""
        if setup == "RSI Dip":
            # For mean-reversion: Red = oversold territory = BETTER entry (not a veto)
            if impulse == "Red":
                impulse_flag = " 🔴Imp(dip-ok)"  # Red normal for mean-revert, PF=1.82
            elif impulse == "Green":
                impulse_flag = " 🟢Impulse"       # Green also excellent, PF=1.76
            # action: top performers get BUY regardless of impulse color
            action = "✅ BUY" if is_top else "⚠ WATCH"
        else:
            # Momentum setups (Breakout, Bull Flag, Gap+Vol): Red = avoid
            if impulse == "Red":
                impulse_flag = " ⛔Impulse-Red"
            elif impulse == "Green":
                impulse_flag = " 🟢Impulse"
            action = "✅ BUY" if (is_top and impulse != "Red") else ("⚠ WATCH" if impulse != "Red" else "🔴 WAIT")

        # Pocket Pivot bonus (O'Neill p.132)
        pp_flag = " 📌PktPivot" if pkt_piv else ""
        # Force Index bonus (Elder p.39): FI2d < 0 = bargain entry (for RSI Dip)
        fi_flag = " 🔽FI<0" if (fi2d < 0 and setup == "RSI Dip") else ""

        # Build detailed reason from live indicator values
        intra_reason = (
            f"{setup} setup · {bt['dir_pct']:.1f}% directional · PF {bt['pf']:.2f} (2yr backtest) · "
            f"{struct_note} · "
            f"RSI14={row['rsi14']:.0f} · RelVol={row['rel_vol']:.1f}× · "
            f"Gap={row.get('gap_pct', 0):+.1f}% · HV20={hv:.0f}%"
            + (f" · 📌 Pocket Pivot" if pkt_piv else "")
            + (f" · 🔽 FI2d<0 (bargain)" if fi2d < 0 and setup == "RSI Dip" else "")
            + (f" · ⭐ Top-5 backtest performer" if is_top else "")
        )
        exec_instr = (
            f"BTO 1 ATM Call, exp {expiry} ({dte}d). "
            if structure == "ATM Call" else
            f"BTO ATM Call + STO OTM Call (debit spread), exp {expiry} ({dte}d). "
        )
        intra_strategy = exec_instr + SETUP_STRATEGY.get(setup, "See setup rules.")

        rows.append({
            "rank":      setup_rank.get(setup, 9),
            "source":    f"Intraday {setup}",
            "sym":       sym,
            "direction": "▲ Bull",
            "signal":    f"RSI14={row['rsi14']:.0f} RelVol={row['rel_vol']:.1f}×{impulse_flag}{pp_flag}{fi_flag}",
            "opt_type":  "Call",
            "structure": structure,
            "expiry":    expiry,
            "dte":       dte,
            "ivr":       "—",
            "max_risk":  400,
            "dir_pct":   bt["dir_pct"],
            "pf":        bt["pf"],
            "badge":     "⭐ Top Pick" if is_top else "📈 Valid",
            "confidence":f"{bt['dir_pct']:.1f}% dir · PF {bt['pf']:.2f} · {struct_note}",
            "action":    action,
            "impulse":   impulse,
            "reason":    intra_reason,
            "strategy":  intra_strategy,
        })
    # ── Affordability pre-filter (KB §4 max risk $400) ──────────────────────
    # The executor rejects orders whose net debit exceeds max_risk. That
    # rejection currently burns a daily auto-exec slot for no benefit (see
    # _auto_exec_options dedup-on-reject in app.py). Pre-filter here so a
    # row that *won't* fit the budget is tagged WATCH instead of BUY and
    # auto-exec skips it cleanly.
    #
    # Estimated ATM premium per contract uses the Brenner-Subrahmanyam
    # approximation: P ≈ 0.4 × S × σ × √(T/365)  (Brenner & Subrahmanyam 1988)
    # then ×100 for the per-contract $ cost.
    #   • ATM Call:           downgrade if naked premium > max_risk × 1.05
    #   • Debit Call Spread:  downgrade if naked premium > max_risk × 2.10
    #     (spread debit typically 40-50% of naked; 2.10x leaves headroom)
    #
    # Symbols without HV data (e.g. Connors-source rows) keep their action
    # — the executor still gatekeeps and the dedup-on-reject release lets
    # us retry tomorrow.
    import math as _math
    price_by_sym = {r["sym"]: (r.get("price", 0), r.get("hv20", 0)) for r in dt_rows}
    for r in rows:
        if r.get("action") != "✅ BUY":
            continue
        sym = r["sym"]
        price, hv = price_by_sym.get(sym, (0, 0))
        if not price or not hv:
            continue   # no data — let the executor filter
        sigma   = hv / 100.0
        t_years = max(r.get("dte", 21), 1) / 365.0
        est_premium_per_contract = 0.4 * price * sigma * _math.sqrt(t_years) * 100
        max_risk = r.get("max_risk", 400)
        struct   = r.get("structure", "")
        cap = max_risk * 1.05 if struct == "ATM Call" else max_risk * 2.10
        if est_premium_per_contract > cap:
            r["action"] = "⚠ WATCH"
            note = (f" [pre-filter: est ATM ${est_premium_per_contract:.0f} "
                    f"> {struct} cap ${cap:.0f}]")
            r["reason"] = (r.get("reason", "") + note)[:1200]
            r["confidence"] = (r.get("confidence", "") + " · affordability=fail")[:200]

    rows.sort(key=lambda r: r["rank"])
    return rows


# ── Refresh ───────────────────────────────────────────────────────────────────
def refresh_screener(daily_positions: list[dict] | None = None) -> dict:
    if not _refresh_lock.acquire(blocking=False):
        return get_cached()
    try:
        dt_rows: list[dict] = []
        for sym in DAY_TRADING_UNIVERSE:
            row = _fetch_symbol(sym)
            if row:
                dt_rows.append(row)

        # Sort: validated setups first (by PF desc), then neutral
        # Breakout PF=1.88 > Bull Flag PF=1.44 > RSI Dip PF=1.41 > Gap+Vol PF=1.37
        dt_rows.sort(key=lambda r: (
            0 if r["setup"] == "Breakout"  else
            1 if r["setup"] == "Bull Flag" else
            2 if r["setup"] == "RSI Dip"   else
            3 if r["setup"] == "Gap+Vol"   else
            9,
            -r.get("bt_pf", 0),
            -r.get("rel_vol", 0),
        ))

        opts = _build_options(dt_rows, daily_positions or [])

        # Load backtest summary for the UI
        bt_path = (Path.home() / "Desktop" / "bharath" / "AlpacaTrader_Data"
                   / "screener_backtest_results.json")
        bt_summary: dict = {}
        if bt_path.exists():
            try:
                bt_summary = json.loads(bt_path.read_text()).get("results", {})
            except Exception:
                pass

        result = {
            "dt":          dt_rows[:15],   # cap matches the UI table (max 15 rows)
            "options":     opts[:15],
            "ts":          time.time(),
            "updated_at":  datetime.now(ET).strftime("%H:%M:%S ET"),
            "market_open": _is_market_open(),
            "bt_summary":  bt_summary,
        }
        with _cache_lock:
            _cache.update(result)
        return result
    finally:
        _refresh_lock.release()


def get_cached() -> dict:
    with _cache_lock:
        return dict(_cache)


def get_or_refresh(daily_positions: list[dict] | None = None, force: bool = False) -> dict:
    with _cache_lock:
        age = time.time() - _cache.get("ts", 0)
    ttl = CACHE_TTL_MARKET if _is_market_open() else CACHE_TTL_CLOSED
    if force or age > ttl or not _cache.get("dt"):
        return refresh_screener(daily_positions)
    return get_cached()


# ── Standalone ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Screener (backtested + book-sourced indicators)…")
    d = refresh_screener()
    print(f"Updated: {d['updated_at']}  Market: {'OPEN' if d['market_open'] else 'CLOSED'}")
    valid   = [r for r in d["dt"] if r["setup"] in VALID_SETUPS]
    neutral = [r for r in d["dt"] if r["setup"] not in VALID_SETUPS]
    print(f"\n{'Sym':<6} {'Price':>7} {'Chg%':>6} {'RelVol':>7} {'RSI14':>6} {'Setup':<11} {'PF':>5} {'Impulse':>8} {'PP':>2} {'FI2d':>8} {'Top?':>4}")
    print("-" * 92)
    for r in (valid + neutral[:5])[:20]:
        top  = "⭐" if r["is_top"] else ""
        imp  = {"Green":"🟢","Blue":"🔵","Red":"🔴"}.get(r.get("impulse","Blue"),"🔵")
        pp   = "✓" if r.get("pkt_pivot") else ""
        fi2d = r.get("fi2d", 0)
        print(f"{r['sym']:<6} ${r['price']:>6.2f} {r['chg_pct']:>+5.1f}%  {r['rel_vol']:>5.2f}×  {r['rsi14']:>5.1f}  "
              f"{r['setup']:<11} {r['bt_pf']:>4.2f}  {imp} {r.get('impulse','?'):5}  {pp:>2}  {fi2d:>+9.0f}  {top}")
    print(f"\nOptions opportunities: {len(d['options'])}")
    for o in d["options"][:8]:
        print(f"  {o['badge']:14} {o['sym']:<6} {o['direction']} {o['signal'][:35]:35} {o['structure']:22} {o['confidence'][:50]}")
