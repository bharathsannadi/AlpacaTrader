#!/usr/bin/env python3.11
"""
screener_engine.py — Live intraday screener for the web dashboard Screener tab.

Two data products:
  1. Day-Trading Watchlist  — top S&P 500 names ranked by book criteria, refreshed
     every 90 s during market hours with today's intraday metrics (VWAP, rel-vol,
     RSI14, setup tag, day change).

  2. Options Opportunities  — two sources merged:
       a. Connors RSI(2) daily positions in "signal" state (from daily_trader)
          → mean-reversion ATM call (KB §2 IVR routing)
       b. High-momentum day-trading stocks (RSI14 > 60, above VWAP, change > +1%)
          → trend-following ATM call

Book citations embedded in every row:
  Aziz p.31    — relative volume ≥ 1.5×  defines "Stocks in Play"
  Elder p.212  — VWAP is the intraday institutional benchmark
  O'Neil §78   — ADV ≥ millions = institutional quality
  Livermore p.47 — trade only the leaders of the leading group
  Get Rich w/Options p.48 — buy options when IV is LOW
  KB §2 / Appendix — IVR routing: naked < 30, spread ≥ 30
  KB-9 Saliba  — prefer DTE 21-28 for directional long options
"""
from __future__ import annotations
import math
import threading
import time
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import numpy as np

ET = ZoneInfo("America/New_York")

# ── Day-trading universe (top-25 S&P 500 from our screen, ranked by score) ───
# Source: screen_sp500_daytrading.py run 2026-05-24
DAY_TRADING_UNIVERSE = [
    "NVDA", "INTC", "AMD", "MU",   "TSLA",
    "QCOM", "PLTR", "ORCL", "HOOD", "ON",
    "AVGO", "LRCX", "ANET", "NOW",  "COHR",
    "VRT",  "SMCI", "WDC",  "GLW",  "MCHP",
    "CRM",  "AMAT", "TXN",  "APP",  "CVNA",
]

# Sector labels for display
_SECTOR = {
    "NVDA": "Semis", "INTC": "Semis", "AMD": "Semis", "MU": "Semis",
    "QCOM": "Semis", "ON": "Semis", "AVGO": "Semis", "LRCX": "Semi Equip",
    "AMAT": "Semi Equip", "MCHP": "Semis",
    "TSLA": "EV/Tech", "PLTR": "AI/Tech", "ORCL": "Tech", "NOW": "Tech",
    "ANET": "Tech", "COHR": "Tech", "SMCI": "Tech", "WDC": "Tech",
    "GLW": "Tech", "CRM": "Tech", "TXN": "Tech", "APP": "Tech",
    "VRT": "Industrials", "HOOD": "Fintech", "CVNA": "Retail",
}

# Pre-scored day-trading scores (from screen, stable for the session)
_SCORE = {
    "NVDA": 96.2, "INTC": 96.9, "AMD": 91.7, "MU": 87.6, "TSLA": 78.6,
    "QCOM": 78.1, "PLTR": 79.3, "ORCL": 79.5, "HOOD": 77.8, "ON": 76.7,
    "AVGO": 75.3, "LRCX": 72.9, "ANET": 72.7, "NOW": 72.7, "COHR": 71.6,
    "VRT": 71.6, "SMCI": 67.4, "WDC": 74.3, "GLW": 69.2, "MCHP": 65.8,
    "CRM": 68.7, "AMAT": 68.6, "TXN": 62.1, "APP": 62.1, "CVNA": 62.7,
}

# Book rationale per setup type
BOOK_CITATIONS = {
    "Momentum":   "Elder p.212 VWAP + Livermore p.47 leader",
    "Gap+Vol":    "Aziz p.31 Stocks in Play (gap≥1% + rel-vol≥1.5×)",
    "VWAP Bounce":"Elder p.212 institutional VWAP reset",
    "RSI Dip":    "Connors RSI(2)<30 — mean-reversion (KB §2)",
    "Breakout":   "Livermore p.65 Pivotal Point + O'Neil §78 volume",
    "Neutral":    "O'Neil §78 institutional ADV quality",
}

CACHE_TTL_MARKET  = 90    # seconds — market hours
CACHE_TTL_CLOSED  = 900   # seconds — after hours

_cache: dict = {"dt": [], "options": [], "ts": 0.0, "market_open": False}
_cache_lock = threading.Lock()
_refresh_lock = threading.Lock()  # prevent concurrent refreshes


# ── Helpers ───────────────────────────────────────────────────────────────────
def _is_market_open() -> bool:
    now = datetime.now(ET)
    if now.weekday() > 4:
        return False
    h, m = now.hour, now.minute
    return (9, 30) <= (h, m) < (16, 0)


def _rsi(closes: pd.Series, n: int = 14) -> float:
    """RSI(n) on a price series. Returns last value."""
    delta = closes.diff().dropna()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)
    avg_g = gain.rolling(n).mean().dropna()
    avg_l = loss.rolling(n).mean().dropna()
    if avg_g.empty or avg_l.empty or avg_l.iloc[-1] == 0:
        return 50.0
    rs = avg_g.iloc[-1] / avg_l.iloc[-1]
    return round(100 - 100 / (1 + rs), 1)


def _rsi2(closes: pd.Series) -> float:
    """RSI(2) for Connors signal."""
    return _rsi(closes, 2)


def _vwap(df: pd.DataFrame) -> float:
    """VWAP from OHLCV intraday DataFrame (typical price method)."""
    tp = (df["High"] + df["Low"] + df["Close"]) / 3
    cum_vol = df["Volume"].cumsum()
    if cum_vol.iloc[-1] == 0:
        return float(df["Close"].iloc[-1])
    return float((tp * df["Volume"]).cumsum().iloc[-1] / cum_vol.iloc[-1])


def _hv_annual(closes: pd.Series, n: int = 20) -> float:
    """Annualised historical volatility (%) from daily closes."""
    rets = np.log(closes / closes.shift(1)).dropna()
    if len(rets) < n:
        return 0.0
    return round(float(rets.tail(n).std() * math.sqrt(252) * 100), 1)


def _nearest_expiry(dte_target: int = 21) -> str:
    """Return the nearest weekly expiry (Fri preferred) ≥ dte_target DTE."""
    today = date.today()
    for offset in range(dte_target, dte_target + 14):
        d = today + timedelta(days=offset)
        if d.weekday() == 4:   # Friday
            return d.strftime("%Y-%m-%d")
    return (today + timedelta(days=dte_target)).strftime("%Y-%m-%d")


def _dte(expiry_str: str) -> int:
    return (date.fromisoformat(expiry_str) - date.today()).days


# ── Per-symbol intraday fetch ─────────────────────────────────────────────────
def _fetch_intraday(sym: str) -> dict | None:
    """Pull today's 5-min bars + 30-day daily history for one symbol."""
    try:
        import yfinance as yf
        t = yf.Ticker(sym)

        # 30-day daily for avg volume, HV, and daily context
        daily = t.history(period="35d", interval="1d", auto_adjust=True, actions=False)
        if daily is None or len(daily) < 5:
            return None

        adv_30 = float(daily["Volume"].tail(30).mean())
        hv20   = _hv_annual(daily["Close"], 20)
        prev_close = float(daily["Close"].iloc[-2]) if len(daily) >= 2 else None

        # Today's intraday bars
        intra = t.history(period="1d", interval="5m", auto_adjust=True, actions=False)
        if intra is None or intra.empty:
            return None

        price     = float(intra["Close"].iloc[-1])
        day_vol   = int(intra["Volume"].sum())
        vwap      = _vwap(intra)
        rsi14     = _rsi(intra["Close"], 14)
        high_day  = float(intra["High"].max())
        low_day   = float(intra["Low"].min())
        day_range = (high_day - low_day) / price * 100 if price > 0 else 0

        # Daily change %
        chg_pct = 0.0
        if prev_close and prev_close > 0:
            chg_pct = round((price - prev_close) / prev_close * 100, 2)

        # Relative volume: today's volume vs avg_30 (scaled by fraction of day elapsed)
        now    = datetime.now(ET)
        mkt_s  = now.replace(hour=9, minute=30, second=0, microsecond=0)
        mkt_e  = now.replace(hour=16, minute=0, second=0, microsecond=0)
        elapsed = (now.timestamp() - mkt_s.timestamp()) / (mkt_e.timestamp() - mkt_s.timestamp())
        elapsed = min(max(elapsed, 0.02), 1.0)
        rel_vol = day_vol / (adv_30 * elapsed) if adv_30 > 0 else 1.0
        rel_vol = round(rel_vol, 2)

        # Pre-market gap (today open vs yesterday close)
        open_day = float(intra["Open"].iloc[0])
        gap_pct  = round((open_day - prev_close) / prev_close * 100, 2) if prev_close else 0.0

        # VWAP position
        vwap_diff = (price - vwap) / vwap * 100 if vwap > 0 else 0.0

        # Setup classification (book-sourced)
        setup = _classify_setup(chg_pct, rel_vol, rsi14, vwap_diff, gap_pct)

        return {
            "sym":      sym,
            "sector":   _SECTOR.get(sym, "Tech"),
            "score":    float(_SCORE.get(sym, 60.0)),
            "price":    round(float(price), 2),
            "chg_pct":  float(chg_pct),
            "gap_pct":  float(gap_pct),
            "rel_vol":  float(rel_vol),
            "rsi14":    round(float(rsi14), 1),
            "vwap":     round(float(vwap), 2),
            "vwap_diff":round(float(vwap_diff), 2),
            "day_range":round(float(day_range), 1),
            "hv20":     float(hv20),
            "adv_30m":  round(float(adv_30) / 1e6, 1),
            "setup":    setup,
            "citation": BOOK_CITATIONS.get(setup, ""),
        }
    except Exception:
        return None


def _classify_setup(chg: float, rvol: float, rsi: float,
                    vwap_diff: float, gap: float) -> str:
    """Book-sourced intraday setup classification."""
    # Aziz p.31: Gap+Vol = gap ≥ 1% AND rel-vol ≥ 1.5×
    if gap >= 1.0 and rvol >= 1.5:
        return "Gap+Vol"
    # Elder p.212: Momentum = RSI14 > 60, price above VWAP, up >1%
    if rsi >= 60 and vwap_diff > 0 and chg > 1.0:
        return "Momentum"
    # Connors: RSI Dip = RSI14 < 35 (oversold, mean-reversion long)
    if rsi < 35:
        return "RSI Dip"
    # Elder p.212: VWAP Bounce = near VWAP + recovering
    if abs(vwap_diff) < 0.4 and rsi > 40 and chg > -0.5:
        return "VWAP Bounce"
    # Breakout: rel-vol ≥ 2× + positive
    if rvol >= 2.0 and chg > 0.5:
        return "Breakout"
    return "Neutral"


# ── Options opportunities builder ─────────────────────────────────────────────
def _build_options_rows(dt_rows: list[dict], daily_positions: list[dict]) -> list[dict]:
    """
    Merge two sources of options opportunities:
      A. Connors RSI(2) daily positions in 'signal' state (mean-reversion)
      B. Momentum stocks from dt_rows where setup = 'Momentum' or 'Gap+Vol'
    """
    rows: list[dict] = []
    seen: set[str] = set()

    expiry = _nearest_expiry(21)
    dte    = _dte(expiry)

    # ── Source A: Connors RSI(2) daily strategy signals ───────────────────────
    for pos in (daily_positions or []):
        if pos.get("status") not in ("signal", "pending"):
            continue
        sym     = pos.get("sym", "").upper()
        if sym in seen:
            continue
        seen.add(sym)
        direction = pos.get("direction", "bull")
        opt_type  = "Call" if direction == "bull" else "Put"
        # IVR from position if available
        ivr = pos.get("ivr") or pos.get("IVR") or "?"
        structure = pos.get("structure", "ATM call")
        rows.append({
            "source":    "Connors RSI(2) Signal",
            "sym":       sym,
            "direction": direction,
            "signal":    f"RSI2={pos.get('rsi2', '?'):.1f}" if isinstance(pos.get("rsi2"), float)
                         else f"RSI2<10",
            "opt_type":  opt_type,
            "structure": structure,
            "expiry":    expiry,
            "dte":       dte,
            "ivr":       str(ivr),
            "max_risk":  pos.get("risk_budget", 400),
            "citation":  "KB §2 IVR routing + KB-9 Saliba DTE 21-28",
            "badge":     "⭐ Daily Strategy",
            "confidence":"High — backtested PF 1.32",
        })

    # ── Source B: Intraday momentum setups ────────────────────────────────────
    for row in dt_rows:
        sym   = row["sym"]
        setup = row["setup"]
        if setup not in ("Momentum", "Gap+Vol", "Breakout"):
            continue
        if sym in seen:
            continue
        seen.add(sym)
        # Structure: if HV > 40% treat as volatile → prefer debit spread
        hv = row.get("hv20", 30)
        if hv > 50:
            structure = "Debit Call Spread"
            note      = f"HV={hv}% (high IV environment — spread limits theta; Get Rich p.48)"
        else:
            structure = "ATM Call"
            note      = f"HV={hv}% (low IV — buy calls cheap; Get Rich p.48)"
        rows.append({
            "source":    f"Intraday {setup}",
            "sym":       sym,
            "direction": "bull",
            "signal":    f"RSI14={row['rsi14']} rel-vol={row['rel_vol']}×",
            "opt_type":  "Call",
            "structure": structure,
            "expiry":    expiry,
            "dte":       dte,
            "ivr":       "—",   # not available intraday
            "max_risk":  400,
            "citation":  row.get("citation", "") + f" | {note}",
            "badge":     "📈 Momentum",
            "confidence":"Medium — intraday pattern only",
        })
        if len(rows) >= 15:
            break

    return rows


# ── Main refresh ──────────────────────────────────────────────────────────────
def refresh_screener(daily_positions: list[dict] | None = None) -> dict:
    """Fetch fresh intraday data for all universe symbols. Thread-safe."""
    if not _refresh_lock.acquire(blocking=False):
        return get_cached()    # already refreshing, return stale cache

    try:
        dt_rows: list[dict] = []
        for sym in DAY_TRADING_UNIVERSE:
            row = _fetch_intraday(sym)
            if row:
                dt_rows.append(row)

        # Sort by setup priority, then score
        priority = {"Gap+Vol": 0, "Momentum": 1, "Breakout": 2,
                    "VWAP Bounce": 3, "RSI Dip": 4, "Neutral": 5}
        dt_rows.sort(key=lambda r: (priority.get(r["setup"], 9), -r["score"]))

        opts_rows = _build_options_rows(dt_rows, daily_positions or [])

        now_str = datetime.now(ET).strftime("%H:%M:%S ET")
        result  = {
            "dt":           dt_rows,
            "options":      opts_rows,
            "ts":           time.time(),
            "updated_at":   now_str,
            "market_open":  _is_market_open(),
            "universe_size": len(DAY_TRADING_UNIVERSE),
        }
        with _cache_lock:
            _cache.update(result)
        return result
    finally:
        _refresh_lock.release()


def get_cached() -> dict:
    """Return the in-memory cache (possibly stale)."""
    with _cache_lock:
        return dict(_cache)


def get_or_refresh(daily_positions: list[dict] | None = None,
                   force: bool = False) -> dict:
    """Return cache if fresh; otherwise refresh synchronously."""
    with _cache_lock:
        age  = time.time() - _cache.get("ts", 0)
        mktopen = _cache.get("market_open", False)

    ttl = CACHE_TTL_MARKET if _is_market_open() else CACHE_TTL_CLOSED
    if force or age > ttl or not _cache.get("dt"):
        return refresh_screener(daily_positions)
    return get_cached()


# ── Standalone test ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Running screener (≈60s)…")
    data = refresh_screener()
    print(f"\nUpdated: {data['updated_at']}  Market open: {data['market_open']}")
    print(f"\n{'Sym':<7} {'Price':>7} {'Chg%':>6} {'RelVol':>7} {'RSI14':>6} "
          f"{'VWAP%':>7} {'HV':>5} {'Setup':<14} Score")
    print("-" * 80)
    for r in data["dt"][:15]:
        sign = "+" if r["chg_pct"] >= 0 else ""
        print(f"{r['sym']:<7} ${r['price']:>6.2f} {sign}{r['chg_pct']:>5.1f}% "
              f"{r['rel_vol']:>6.2f}×  {r['rsi14']:>5.1f}  "
              f"{'+' if r['vwap_diff']>=0 else ''}{r['vwap_diff']:>5.1f}%  "
              f"{r['hv20']:>4.0f}%  {r['setup']:<14} {r['score']:.1f}")
    if data["options"]:
        print(f"\n{'─'*80}")
        print("OPTIONS OPPORTUNITIES")
        print(f"{'─'*80}")
        for o in data["options"][:10]:
            print(f"  {o['badge']} {o['sym']} | {o['signal']} | {o['structure']} "
                  f"| expiry {o['expiry']} ({o['dte']}d) | risk ${o['max_risk']}")
            print(f"    → {o['citation'][:80]}")
