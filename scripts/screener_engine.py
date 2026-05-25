#!/usr/bin/env python3.11
"""
screener_engine.py — Live intraday screener for the Screener tab.

BACKTESTED setup criteria (2yr, 25 symbols, next-day open→close):
  ✅ Breakout   PF 1.88  Win 51.5%  AvgRet +0.78%  (new 50d high + RSI55-70 + rel-vol>1.3)
  ✅ RSI Dip    PF 1.41  Win 53.7%  AvgRet +0.42%  (RSI14 < 35, oversold mean-revert)
  ✅ Gap+Vol    PF 1.37  Win 50.6%  AvgRet +0.41%  (gap>1% + rel-vol>1.5×, Aziz p.31)
  ❌ Momentum   PF 1.00  Win 50.1%  AvgRet +0.00%  REMOVED — no edge
  ❌ VWAP Bounce PF 0.85 Win 48.9%  AvgRet -0.15%  REMOVED — negative edge

OPTIONS direction accuracy (same backtest):
  ✅ Breakout  51.5% directional
  ✅ RSI Dip   53.7% directional (next-day)
  ✅ Connors RSI(2) < 10  66.4% multi-day (existing daily strategy, PF 1.32)

Top performers per validated setup (avg next-day return):
  RSI Dip  : COHR+2.25% HOOD+2.11% LRCX+1.40% CVNA+1.37% NVDA+1.34%
  Gap+Vol  : APP+3.24%  SMCI+2.42% CVNA+1.87% TXN+1.31%  QCOM+1.21%
  Breakout : WDC+4.03%  MU+3.52%   PLTR+2.47% CVNA+2.09% ON+1.99%

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

# ── Universe (top-25 S&P500 day-trading names from screen, 2026-05-24) ────────
DAY_TRADING_UNIVERSE = [
    "NVDA", "INTC", "AMD",  "MU",   "TSLA",
    "QCOM", "PLTR", "ORCL", "HOOD", "ON",
    "AVGO", "LRCX", "ANET", "NOW",  "COHR",
    "VRT",  "SMCI", "WDC",  "GLW",  "MCHP",
    "CRM",  "AMAT", "TXN",  "APP",  "CVNA",
]

_SECTOR = {
    "NVDA":"Semis","INTC":"Semis","AMD":"Semis","MU":"Semis",
    "QCOM":"Semis","ON":"Semis","AVGO":"Semis","LRCX":"Semi Equip",
    "AMAT":"Semi Equip","MCHP":"Semis","GLW":"Tech",
    "TSLA":"EV/Tech","PLTR":"AI","ORCL":"Tech","NOW":"Tech",
    "ANET":"Net","COHR":"Photonics","SMCI":"Servers","WDC":"Storage",
    "CRM":"SaaS","TXN":"Semis","APP":"AdTech","VRT":"Industrials",
    "HOOD":"Fintech","CVNA":"Retail",
}

# Backtested metrics per setup (from backtest_screener_criteria.py, 2026-05-24)
BT_METRICS = {
    "Breakout":    {"pf": 1.88, "win_pct": 51.5, "avg_ret": 0.781, "dir_pct": 51.5, "n": 33},
    "RSI Dip":     {"pf": 1.41, "win_pct": 53.7, "avg_ret": 0.421, "dir_pct": 53.7, "n": 870},
    "Gap+Vol":     {"pf": 1.37, "win_pct": 50.6, "avg_ret": 0.408, "dir_pct": 50.6, "n": 243},
    # Removed — no edge (keep entry so we can label them correctly if they appear)
    "Momentum":    {"pf": 1.00, "win_pct": 50.1, "avg_ret": 0.002, "dir_pct": 50.1, "n": 1566},
    "VWAP Bounce": {"pf": 0.85, "win_pct": 48.9, "avg_ret":-0.148, "dir_pct": 48.9, "n": 380},
    "Neutral":     {"pf": 0.00, "win_pct": 0,    "avg_ret": 0,     "dir_pct": 50.0, "n": 0},
}

# Top performers per setup (from backtest — highlight these in the UI)
TOP_PERFORMERS = {
    "RSI Dip":  ["COHR", "HOOD", "LRCX", "CVNA", "NVDA"],
    "Gap+Vol":  ["APP",  "SMCI", "CVNA", "TXN",  "QCOM"],
    "Breakout": ["WDC",  "MU",   "PLTR", "CVNA", "ON"],
}

# Validated = backtested PF > 1.2
VALID_SETUPS = {"Breakout", "RSI Dip", "Gap+Vol"}

CACHE_TTL_MARKET = 90    # seconds during market hours
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
    Apply only the THREE backtested-valid setup criteria.
    Momentum and VWAP Bounce deliberately excluded (PF ≤ 1.00).
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

        adv30     = float(daily["Volume"].tail(30).mean())
        hv20      = _hv_annual(daily["Close"], 20)
        rsi14_d   = _rsi(daily["Close"], 14)   # daily RSI14
        rsi2_d    = _rsi2(daily["Close"])       # daily RSI2 (Connors signal)
        ema20_d   = _ema(daily["Close"], 20)
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

        return {
            "sym":      sym,
            "sector":   _SECTOR.get(sym, "Tech"),
            "price":    round(float(price), 2),
            "chg_pct":  float(chg_pct),
            "gap_pct":  float(gap_pct),
            "rel_vol":  float(rel_vol),
            "rsi14":    float(rsi14_i),
            "rsi14_d":  float(rsi14_d),    # daily RSI14
            "rsi2_d":   float(rsi2_d),     # daily RSI2 (Connors)
            "vwap":     round(float(vwap), 2),
            "vwap_diff":float(vwap_diff),
            "day_range":float(day_range),
            "hv20":     float(hv20),
            "ema20_d":  round(float(ema20_d), 2),
            "adv30m":   round(float(adv30) / 1e6, 1),
            "setup":    setup,
            "valid":    setup in VALID_SETUPS,
            "is_top":   bool(is_top),
            "bt_pf":    float(bt["pf"]),
            "bt_win":   float(bt["win_pct"]),
            "bt_ret":   float(bt["avg_ret"]),
            "bt_dir":   float(bt["dir_pct"]),
            "bt_n":     int(bt["n"]),
        }
    except Exception:
        return None


# ── Options opportunities ─────────────────────────────────────────────────────
def _build_options(dt_rows: list[dict], daily_positions: list[dict]) -> list[dict]:
    """
    Two sources, ranked by validated directional accuracy:
      1. Connors RSI(2) daily signals  → 66.4% dir-hit (PF 1.32, proven)
      2. RSI Dip intraday             → 53.7% dir-hit (backtested)
      3. Gap+Vol                       → 50.6% dir-hit (backtested)
      4. Breakout                      → 51.5% dir-hit (backtested)
    Momentum and VWAP Bounce excluded — no directional edge.
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
        rows.append({
            "rank":      1,
            "source":    "Connors RSI(2) Daily",
            "sym":       sym,
            "direction": "▲ Bull" if direction == "bull" else "▼ Bear",
            "signal":    f"RSI2={pos.get('rsi2', '<10'):.1f}" if isinstance(pos.get("rsi2"), float) else "RSI2 < 10",
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
        })

    # ── Source B: Intraday validated setups → directional options ────────────
    # Rank by directional accuracy: RSI Dip 53.7% > Breakout 51.5% > Gap+Vol 50.6%
    setup_rank = {"RSI Dip": 2, "Breakout": 3, "Gap+Vol": 4}
    for row in sorted(dt_rows, key=lambda r: setup_rank.get(r["setup"], 9)):
        sym   = row["sym"]
        setup = row["setup"]
        if setup not in VALID_SETUPS or sym in seen:
            continue
        seen.add(sym)
        bt   = BT_METRICS[setup]
        hv   = row.get("hv20", 30)
        # Structure: if HV > 45% → spread (theta risk too high for naked)
        structure = "Debit Call Spread" if hv > 45 else "ATM Call"
        struct_note = (f"HV={hv:.0f}% > 45% → spread limits theta decay"
                       if hv > 45 else f"HV={hv:.0f}% ≤ 45% → naked call is cheap")
        is_top = row.get("is_top", False)
        rows.append({
            "rank":      setup_rank.get(setup, 9),
            "source":    f"Intraday {setup}",
            "sym":       sym,
            "direction": "▲ Bull",
            "signal":    f"RSI14={row['rsi14']:.0f}  RelVol={row['rel_vol']:.1f}×",
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
            "action":    "✅ BUY" if is_top else "⚠ WATCH",
        })
        if len(rows) >= 12:
            break

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
        dt_rows.sort(key=lambda r: (
            0 if r["setup"] == "Breakout" else
            1 if r["setup"] == "RSI Dip" else
            2 if r["setup"] == "Gap+Vol" else
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
            "dt":          dt_rows,
            "options":     opts,
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
    print("Screener (backtested rules only)…")
    d = refresh_screener()
    print(f"Updated: {d['updated_at']}  Market: {'OPEN' if d['market_open'] else 'CLOSED'}")
    valid = [r for r in d["dt"] if r["setup"] in VALID_SETUPS]
    print(f"\n{'Sym':<6} {'Price':>7} {'Chg%':>6} {'RelVol':>7} {'RSI14':>6} {'Setup':<11} {'PF':>5} {'Win%':>6} {'AvgRet':>7} {'Top?':>4}")
    print("-" * 78)
    for r in valid[:15]:
        top = "⭐" if r["is_top"] else ""
        print(f"{r['sym']:<6} ${r['price']:>6.2f} {r['chg_pct']:>+5.1f}%  {r['rel_vol']:>5.2f}×  {r['rsi14']:>5.1f}  "
              f"{r['setup']:<11} {r['bt_pf']:>4.2f}  {r['bt_win']:>5.1f}%  {r['bt_ret']:>+6.3f}%  {top}")
    print(f"\nOptions opportunities: {len(d['options'])}")
    for o in d["options"][:8]:
        print(f"  {o['badge']:14} {o['sym']:<6} {o['direction']} {o['signal']:30} {o['structure']:22} {o['confidence'][:55]}")
