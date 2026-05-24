#!/usr/bin/env python3.11
"""
daily_trader.py — Connors RSI(2) daily-bar execution layer (Path A).

Strategy: RSI(2) < 10 AND close > SMA200 → long next-day open.
          Exit: RSI(2) > 70 at prior close → sell at next-day open.
          Stop: 50% of premium paid for options (KB §9).
                2×ATR14 native stop for shares mode.
          Cap:  5 concurrent positions (20% portfolio / 4% per trade).

Instrument: INSTRUMENT = "options" (default) | "shares"

Options routing — every rule sourced from knowledge_base.md:
  §1 Greeks:    target delta ~0.50 (ATM); DTE ≥ 14 (no 7-DTE overnight swing)
  §2 IV Rules:  IV/HV < 0.80 → naked long call (cheap premium, vega tailwind)
                IV/HV 0.80–1.50 → bull call debit spread (cap vega risk)
                IV/HV ≥ 1.50 → debit spread only (KB: "1.5× HV = overpriced")
  §5 Spreads:   ATM long leg (Δ ~0.50), OTM short leg (Δ ~0.25); debit 25–45% of width
  §9 Checklist: OI ≥ 200, bid-ask < 5% of mid, stop = 50% of premium, max loss ≤ $200

Lifecycle (call in order each trading day):
  1. EOD (~4:10 PM ET)  — run_eod()   : refresh data, check exits, identify option contracts
  2. Morning (~9:35 AM) — run_morning(): submit option limit orders, confirm fills, check stops

Positions persist in ~/.spy_trader/daily_positions.json.

Usage (CLI):
    venv/bin/python3.11 scripts/daily_trader.py eod        # EOD routine
    venv/bin/python3.11 scripts/daily_trader.py morning    # morning submit + confirm
    venv/bin/python3.11 scripts/daily_trader.py status     # show positions
    venv/bin/python3.11 scripts/daily_trader.py closeall   # emergency close
"""
from __future__ import annotations
import os, sys, json, logging
from datetime import datetime, date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent))
import warnings; warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)

import numpy as np
import pandas as pd
from daily_data import fetch_daily
from universe import ALL

ET = ZoneInfo("America/New_York")

# ── Strategy constants (pre-specified, validated 2026-05-20 backtest) ─────────
SMA_WIN        = 200    # trend filter — KB §19, §8 Gunn: un-conditioned = no edge
RSI_N          = 2      # Connors short-period RSI
RSI_LO         = 10.0  # entry: RSI(2) < this AND close > SMA200
RSI_EXIT       = 70.0  # exit: RSI(2) > this → sell at next open
ATR_WIN        = 14     # ATR smoothing (shares-mode stop)
ATR_STOP_M     = 2.0   # shares stop distance = 2 × ATR14
TIME_CAP_DAYS  = 10    # max hold in trading days
RISK_BUDGET      = 400.0 # $ max loss per trade — ½-Kelly validated 2026-05-23:
                          # test win%=66.4, PF=1.32 → full-Kelly=16.1% → ½-Kelly=8%=$400 on $5K
                          # (was $500/10%; reduced to align with ½-Kelly sizing constraint)
MAX_CONCURRENT   = 5     # cap open positions (20% portfolio / 4% per trade)
MIN_ATR_PCT      = 0.015 # universe filter: ATR14/close ≥ 1.5% — minimum daily swing for
                          # Connors RSI(2) mean-reversion to be real (not noise-driven)
                          # Pre-specified; OOS test showed mega-cap low-vol names fail this strategy
MAX_CORRELATED   = 3     # KB §4, Appendix: max 3 same-direction (bull) positions at once
OPT_PROFIT_T2    = 0.80  # KB §24 Lowell p.82: close spread at 80% of max profit (width − debit)
OPT_PROFIT_T1    = 0.50  # KB §24 Appendix: T1 partial exit at +50% gain (requires contracts ≥ 2)
VIX_BLOCK_ABOVE  = 30    # KB Appendix: VIX > 30 → skip all new entries
VIX_SPIKE_DAILY  = 5.0   # KB Appendix: VIX spike > 5 pts/day → force spread structure only
OPT_MIN_DTE_PREF = 21    # KB §25 Saliba: prefer DTE ≥ 21 (optimal 21–28 window)
UNIVERSE       = list(ALL)

# ── Instrument selector ────────────────────────────────────────────────────────
INSTRUMENT = "options"   # "options" | "shares"

# ── Options constants (KB §1, §2, §5, §9) ─────────────────────────────────────
OPT_DTE_MIN          = 14    # KB §1: never hold 7-DTE overnight for a swing trade
OPT_DTE_MAX          = 30    # cap vega cost; DTE beyond 30 adds unnecessary vega bleed
OPT_STOP_PCT         = 0.50  # KB §9: exit if premium drops to 50% of entry debit
OPT_MIN_OI           = 200   # KB §9/Appendix: OI ≥ 500 for ETFs; deliberately relaxed to 200
                              # for equity single-names where chain depth is thinner
OPT_MAX_BID_ASK_PCT  = 0.05  # KB §9: bid-ask < 5% of mid
OPT_IV_HV_NAKED_MAX  = 0.80  # KB §2: IV < 80% of HV = cheap → naked OK
OPT_IV_HV_EXPENSIVE  = 1.50  # KB §2: IV > 1.5× HV = overpriced → spread only
OPT_SPREAD_RATIO_LO  = 0.25  # KB §5: debit spread debit should be 25–45% of width
OPT_SPREAD_RATIO_HI  = 0.45

POSITIONS_FILE = Path.home() / ".spy_trader" / "daily_positions.json"
LOG = logging.getLogger("daily_trader")


# ── Credential helpers ─────────────────────────────────────────────────────────
def _load_env() -> tuple[str, str, bool]:
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    key    = os.environ.get("ALPACA_API_KEY", "")
    secret = os.environ.get("ALPACA_API_SECRET", "")
    paper  = os.environ.get("ALPACA_PAPER", "true").lower() != "false"
    return key, secret, paper


def _make_client():
    from alpaca.trading.client import TradingClient
    key, secret, paper = _load_env()
    if not key or not secret:
        raise RuntimeError("ALPACA_API_KEY / ALPACA_API_SECRET not set in .env")
    return TradingClient(key, secret, paper=paper), paper


def _make_option_client():
    from alpaca.data.historical.option import OptionHistoricalDataClient
    key, secret, _ = _load_env()
    return OptionHistoricalDataClient(key, secret)


# ── Indicator helpers (same formulae as backtest) ──────────────────────────────
def _rsi(close: pd.Series, n: int) -> pd.Series:
    d  = close.diff()
    up = d.where(d > 0, 0.0)
    dn = (-d).where(d < 0, 0.0)
    ag = up.ewm(alpha=1.0 / n, adjust=False).mean()
    al = dn.ewm(alpha=1.0 / n, adjust=False).mean()
    rs = ag / al.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50.0)


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, n: int) -> pd.Series:
    prev = close.shift(1)
    tr   = pd.concat([high - low,
                      (high - prev).abs(),
                      (low  - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / n, adjust=False).mean()


def _get_hv21(df: pd.DataFrame) -> float:
    """21-day annualized historical vol from log returns. KB §2: IV/HV ratio gate."""
    lr = np.log(df["close"] / df["close"].shift(1)).dropna()
    if len(lr) < 21:
        return float("nan")
    return float(lr.tail(21).std() * np.sqrt(252))


def _get_hv_range_252(df: pd.DataFrame) -> tuple[float, float]:
    """Return (min, max) of the 21-day rolling HV over the last 252 trading days.
    Used to build an IVR proxy: ivr = (current_iv - hv_min) / (hv_max - hv_min).
    KB §2 Appendix: IVR < 30 → naked, 30-50 → spread, > 50 → spread only."""
    log_ret  = np.log(df["close"] / df["close"].shift(1)).dropna()
    hv_roll  = log_ret.rolling(21).std() * np.sqrt(252)
    hv_252   = hv_roll.iloc[-252:].dropna()
    if len(hv_252) < 21:
        return float("nan"), float("nan")
    return float(hv_252.min()), float(hv_252.max())


def compute_indicators(sym: str) -> dict | None:
    df = fetch_daily(sym, force_refresh=True)
    if df is None or len(df) < SMA_WIN + 2:
        return None
    df = df.sort_values("date").reset_index(drop=True)
    df["sma200"] = df["close"].rolling(SMA_WIN).mean()
    df["rsi2"]   = _rsi(df["close"], RSI_N)
    df["atr14"]  = _atr(df["high"], df["low"], df["close"], ATR_WIN)

    row     = df.iloc[-1]
    row_prv = df.iloc[-2]
    hv252_min, hv252_max = _get_hv_range_252(df)
    return {
        "sym":        sym,
        "date":       str(row["date"].date()),
        "close":      float(row["close"]),
        "sma200":     float(row["sma200"]),
        "rsi2":       float(row["rsi2"]),
        "rsi2_prev":  float(row_prv["rsi2"]),
        "atr14":      float(row["atr14"]),
        "hv21":       _get_hv21(df),
        "hv252_min":  hv252_min,   # IVR proxy lower bound
        "hv252_max":  hv252_max,   # IVR proxy upper bound
    }


# ── Earnings proximity check (KB §3, §7) ─────────────────────────────────────
def _days_to_earnings(sym: str) -> int:
    """Calendar days to next known earnings date. Returns 99 if unknown.
    KB §3: 'Earnings within 2 trading days → never buy naked calls/puts.'"""
    try:
        import yfinance as yf
        cal = yf.Ticker(sym).calendar
        if cal is None:
            return 99
        # yfinance returns either a dict or DataFrame depending on version
        if isinstance(cal, dict):
            raw = cal.get("Earnings Date", [])
            earn_list = raw if hasattr(raw, "__iter__") and not isinstance(raw, str) else [raw]
        elif hasattr(cal, "columns") and "Earnings Date" in cal.columns:
            earn_list = cal["Earnings Date"].tolist()
        else:
            return 99
        today   = date.today()
        future  = []
        for d in earn_list:
            try:
                d2 = d.date() if hasattr(d, "date") else d
                if d2 >= today:
                    future.append(d2)
            except Exception:
                pass
        if not future:
            return 99
        return (min(future) - today).days
    except Exception:
        return 99


# ── Macro blackout calendar 2026 (FOMC / CPI / NFP) ──────────────────────────
# KB §3: "Never enter within 5-10 min before/after major economic data releases."
# KB Cofnas: "Block all entries during scheduled data releases."
# We block the signal day AND the day before (IV inflates into the print).
_MACRO_DATES_2026: dict[date, str] = {
    # FOMC decision days (Federal Reserve pre-announced schedule)
    date(2026,  1, 28): "FOMC", date(2026,  3, 18): "FOMC",
    date(2026,  5,  7): "FOMC", date(2026,  6, 17): "FOMC",
    date(2026,  7, 30): "FOMC", date(2026,  9, 16): "FOMC",
    date(2026, 10, 29): "FOMC", date(2026, 12, 10): "FOMC",
    # CPI releases (BLS, approx 2nd/3rd Wed of month)
    date(2026,  1, 14): "CPI",  date(2026,  2, 11): "CPI",
    date(2026,  3, 11): "CPI",  date(2026,  4, 15): "CPI",
    date(2026,  5, 13): "CPI",  date(2026,  6, 10): "CPI",
    date(2026,  7, 15): "CPI",  date(2026,  8, 12): "CPI",
    date(2026,  9,  9): "CPI",  date(2026, 10, 14): "CPI",
    date(2026, 11, 13): "CPI",  date(2026, 12,  9): "CPI",
    # NFP / Jobs Report (first Friday of month)
    date(2026,  1,  9): "NFP",  date(2026,  2,  6): "NFP",
    date(2026,  3,  6): "NFP",  date(2026,  4,  3): "NFP",
    date(2026,  5,  8): "NFP",  date(2026,  6,  5): "NFP",
    date(2026,  7,  2): "NFP",  date(2026,  8,  7): "NFP",
    date(2026,  9,  4): "NFP",  date(2026, 10,  2): "NFP",
    date(2026, 11,  6): "NFP",  date(2026, 12,  4): "NFP",
}

def _macro_event_on(check_date: date) -> str | None:
    """Return event label if check_date is a macro blackout day, else None."""
    return _MACRO_DATES_2026.get(check_date)


def _fetch_vix() -> tuple[float | None, float | None]:
    """Return (today_vix, yesterday_vix). Used for KB-4 VIX gate and KB-10 spike detection."""
    try:
        import yfinance as yf
        hist = yf.Ticker("^VIX").history(period="5d")
        if len(hist) < 2:
            return None, None
        return float(hist["Close"].iloc[-1]), float(hist["Close"].iloc[-2])
    except Exception:
        return None, None


# ── IVR proxy helper ──────────────────────────────────────────────────────────
def _compute_ivr_proxy(atm_iv: float, hv252_min: float, hv252_max: float) -> float:
    """KB §2 Appendix IVR proxy using 252-day rolling HV range as reference.
    Returns 0-100; 50 if range data unavailable (conservative default).
    True IVR needs historical IV data (expensive); this uses HV range as proxy."""
    if (np.isnan(atm_iv) or np.isnan(hv252_min) or np.isnan(hv252_max)
            or hv252_max <= hv252_min):
        return 50.0   # unknown → treat as moderate, use spread
    return float(np.clip((atm_iv - hv252_min) / (hv252_max - hv252_min) * 100, 0.0, 100.0))


# ── Options contract selection (KB §1, §2, §5, §9) ───────────────────────────
def _get_option_context(sym: str, spot: float, hv21: float,
                        hv252_min: float = float("nan"),
                        hv252_max: float = float("nan"),
                        vix_spike: bool = False) -> dict | None:
    """
    Select the best option structure for a Connors RSI(2) bull entry.

    KB rules applied in order:
      §1: DTE 14–30 (never hold 7-DTE overnight for a swing trade)
      §9: OI ≥ 200, bid-ask < 5% of mid, debit × 100 ≤ RISK_BUDGET
      §2: IV/HV ratio < 0.80 → naked; 0.80–1.50 → spread; ≥ 1.50 → spread only
      §5: ATM long leg (Δ ~0.50); OTM short leg; debit 25–45% of spread width
          "Buy ATM (delta ~0.50), sell 1–2 strikes further OTM (delta ~0.20–0.30)"

    Returns option fields dict to merge into the position record, or None to skip.
    """
    import yfinance as yf
    try:
        expirations = yf.Ticker(sym).options
    except Exception:
        return None

    today = date.today()
    valid = [
        ((date.fromisoformat(e) - today).days, e)
        for e in expirations
        if OPT_DTE_MIN <= (date.fromisoformat(e) - today).days <= OPT_DTE_MAX
    ]
    if not valid:
        return None

    # KB §25 Saliba: prefer DTE ≥ 21 (optimal 21–28 window); fall back to nearest if unavailable
    preferred = [(d, e) for d, e in valid if d >= OPT_MIN_DTE_PREF]
    dte, expiry_str = min(preferred) if preferred else min(valid)

    try:
        chain = yf.Ticker(sym).option_chain(expiry_str)
    except Exception:
        return None

    calls = chain.calls.copy()
    calls = calls[calls["bid"] > 0].copy()
    calls["mid"]  = (calls["bid"] + calls["ask"]) / 2.0
    calls["dist"] = (calls["strike"] - spot).abs()
    if calls.empty:
        return None

    # Long leg: ATM — KB §1 "target delta 0.40–0.60", §5 "buy ATM (delta ~0.50)"
    atm        = calls.sort_values("dist").iloc[0]
    atm_strike = float(atm["strike"])
    atm_mid    = float(atm["mid"])
    atm_bid    = float(atm["bid"])
    atm_ask    = float(atm["ask"])
    atm_iv     = float(atm.get("impliedVolatility", float("nan")))
    atm_oi     = int(atm.get("openInterest", 0) or 0)
    atm_occ    = str(atm["contractSymbol"])

    # Liquidity gates — KB §9
    # Note: bid-ask % gate is enforced at morning order submission (live quotes),
    # not here. At EOD the options market is closed and yfinance quotes are stale,
    # causing artificially wide spreads that would incorrectly block valid entries.
    if atm_mid <= 0:
        return None
    if atm_oi < OPT_MIN_OI:
        return None

    # ── IVR proxy (KB §2 Appendix) ───────────────────────────────────────────
    # True IVR = (current_iv - 52wk_low_iv) / (52wk_high_iv - 52wk_low_iv).
    # We approximate using 252-day rolling HV range (free, no historical IV needed).
    ivr   = _compute_ivr_proxy(atm_iv, hv252_min, hv252_max)
    iv_hv = (atm_iv / hv21) if (not np.isnan(hv21) and hv21 > 0) else 1.0  # kept for logging

    # KB §2 Appendix: IVR > 80 = premium too expensive for any long options structure
    if ivr > 80:
        print(f"  {sym}: IVR={ivr:.0f}% > 80 — premium too expensive, skip (KB §2)")
        return None

    # KB-10: VIX spike > 5 pts/day → spread structure only regardless of IVR (KB Appendix)
    if vix_spike:
        print(f"  {sym}: VIX spike today — forcing spread structure (KB Appendix KB-10)")

    # ── Naked: IVR < 30 → IV historically cheap (KB §2 Appendix) ────────────
    if ivr < 30 and not vix_spike and atm_mid * 100 <= RISK_BUDGET:
        return {
            "structure":    "naked",
            "expiry":       expiry_str,
            "dte":          dte,
            "long_occ":     atm_occ,
            "long_strike":  atm_strike,
            "short_occ":    None,
            "short_strike": None,
            "est_debit":    round(atm_mid, 2),
            "width":        None,
            "iv_hv":        round(iv_hv, 2),
            "ivr":          round(ivr, 1),
            "contracts":    1,
        }

    # ── Debit spread: IVR 30–80 (KB §2, §5) ─────────────────────────────────
    # "Buy ATM (delta ~0.50), sell 1–2 strikes further OTM (delta ~0.20–0.30)"
    # "Debit paid should be 30–40% of spread width for a good risk/reward"
    otm_calls = calls[calls["strike"] > atm_strike].sort_values("strike")
    for _, short_row in otm_calls.head(6).iterrows():
        short_strike = float(short_row["strike"])
        short_bid    = float(short_row["bid"])
        short_mid    = float(short_row["mid"])
        short_oi     = int(short_row.get("openInterest", 0) or 0)
        short_occ    = str(short_row["contractSymbol"])

        if short_bid <= 0 or short_oi < OPT_MIN_OI:
            continue

        width     = short_strike - atm_strike
        # Conservative debit: pay mid on long, receive bid on short (KB §5 slippage note)
        net_debit = atm_mid - short_bid

        if net_debit <= 0 or width <= 0:
            continue

        ratio = net_debit / width
        if not (OPT_SPREAD_RATIO_LO <= ratio <= OPT_SPREAD_RATIO_HI):
            continue  # KB §5: "30–40% of spread width"

        # KB §25 KB-8: spread width must be > 3× per-leg bid-ask (else slippage > 33% of profit)
        if width < 3 * (atm_ask - atm_bid):
            continue

        if net_debit * 100 > RISK_BUDGET:
            continue  # KB §4, §9: max loss = debit paid

        return {
            "structure":    "spread",
            "expiry":       expiry_str,
            "dte":          dte,
            "long_occ":     atm_occ,
            "long_strike":  atm_strike,
            "short_occ":    short_occ,
            "short_strike": short_strike,
            "est_debit":    round(net_debit, 2),
            "width":        round(width, 2),
            "iv_hv":        round(iv_hv, 2),
            "ivr":          round(ivr, 1),
            "contracts":    1,
        }

    return None  # no contract passes all KB gates


# ── Position persistence ───────────────────────────────────────────────────────
def _load_positions() -> list[dict]:
    POSITIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not POSITIONS_FILE.exists():
        return []
    try:
        return json.loads(POSITIONS_FILE.read_text())
    except Exception:
        return []


def _save_positions(positions: list[dict]) -> None:
    POSITIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    POSITIONS_FILE.write_text(json.dumps(positions, indent=2))


# ── Signal generation ──────────────────────────────────────────────────────────
def generate_signals(indicators: dict[str, dict],
                     open_positions: list[dict],
                     vix_block: bool = False,
                     vix_spike: bool = False) -> dict[str, list[dict]]:
    """
    Return exit and entry signals based on Connors RSI(2) rules.
    Options entries include contract context from _get_option_context().
    """
    open_syms  = {p["sym"] for p in open_positions
                  if p["status"] in ("open", "pending", "signal")}
    open_count = len(open_syms)
    today_str  = str(date.today())

    exits: list[dict]   = []
    entries: list[dict] = []

    # ── Check exits ──────────────────────────────────────────────────────────
    for pos in open_positions:
        if pos["status"] not in ("open", "pending", "signal"):
            continue
        ind = indicators.get(pos["sym"])

        entry_dt  = pd.Timestamp(pos["entry_date"])
        days_held = len(pd.bdate_range(entry_dt, pd.Timestamp(today_str))) - 1

        reason = None

        # Primary strategy exits (require indicators)
        if ind is not None:
            if ind["rsi2"] >= RSI_EXIT:
                reason = f"mean_revert (RSI2={ind['rsi2']:.1f}≥{RSI_EXIT})"
            elif days_held >= TIME_CAP_DAYS:
                reason = f"time_cap ({days_held}d≥{TIME_CAP_DAYS})"

        # KB-2: 7-DTE gamma risk (KB §24/§1) — never hold options into gamma danger zone
        if reason is None and pos.get("instrument") == "options" and pos.get("expiry"):
            try:
                days_left = (date.fromisoformat(pos["expiry"]) - date.today()).days
                if days_left <= 7:
                    reason = f"dte_close_7d (DTE={days_left})"
            except Exception:
                pass

        # KB-3: close open positions 2 days before earnings (KB §23/§24)
        if reason is None:
            earn_days = _days_to_earnings(pos["sym"])
            if earn_days <= 2:
                reason = f"earnings_d2 ({earn_days}d to earnings)"

        if reason:
            exits.append({
                "sym":           pos["sym"],
                "reason":        reason,
                "instrument":    pos.get("instrument", "shares"),
                "shares":        pos.get("shares", 0),
                "stop_order_id": pos.get("stop_order_id"),
                "long_occ":      pos.get("long_occ"),
                "short_occ":     pos.get("short_occ"),
                "contracts":     pos.get("contracts", 1),
            })

    # ── Compute entries ──────────────────────────────────────────────────────
    exiting_syms = {e["sym"] for e in exits}
    free_slots   = MAX_CONCURRENT - (open_count - len(exits))

    # ── Macro blackout check — blocks ALL new entries on event day + day before ─
    # KB §3 / Cofnas: IV inflates into the print; entering = overpaying for premium
    today_date = date.today()
    macro_block: str | None = None
    for offset in (0, 1):
        event = _macro_event_on(today_date + timedelta(days=offset))
        if event:
            macro_block = f"{event} {'today' if offset == 0 else 'tomorrow'}"
            break

    if macro_block:
        print(f"  ⚠ Macro blackout: {macro_block} — no new entries (KB §3/Cofnas)")

    # KB-5: max 3 same-direction (bull) positions — KB §4 Appendix
    bull_open = sum(1 for p in open_positions
                    if p["status"] in ("open", "pending", "signal")
                    and p.get("direction") == "bull")
    if bull_open >= MAX_CORRELATED:
        print(f"  ⚠ Correlated cap: {bull_open}/{MAX_CORRELATED} bull positions open "
              f"— no new entries (KB §4 KB-5)")

    if free_slots > 0 and not macro_block and not vix_block and bull_open < MAX_CORRELATED:
        candidates = []
        for sym, ind in indicators.items():
            if sym in open_syms or sym in exiting_syms:
                continue
            if np.isnan(ind["sma200"]) or np.isnan(ind["atr14"]) or ind["atr14"] <= 0:
                continue
            # Universe filter: minimum ATR% (pre-specified, OOS-validated 2026-05-23)
            atr_pct = ind["atr14"] / ind["close"]
            if atr_pct < MIN_ATR_PCT:
                continue  # low-vol name — Connors RSI(2) entries are noise, not edge
            # KB §19: RSI(2) < 10 AND close > SMA200
            if ind["rsi2"] < RSI_LO and ind["close"] > ind["sma200"]:

                # ── Earnings exclusion (KB §3, §7) ──────────────────────────
                earn_days = _days_to_earnings(sym)
                if earn_days <= 2:
                    print(f"  {sym}: earnings in {earn_days}d — skip (KB §3 §7)")
                    continue

                entry = {
                    "sym":        sym,
                    "rsi2":       ind["rsi2"],
                    "close":      ind["close"],
                    "atr14":      ind["atr14"],
                    "sma200":     ind["sma200"],
                    "hv21":       ind.get("hv21", float("nan")),
                    "entry_date": today_str,
                    "instrument": INSTRUMENT,
                }

                if INSTRUMENT == "options":
                    opt = _get_option_context(
                        sym, ind["close"],
                        ind.get("hv21",      float("nan")),
                        ind.get("hv252_min", float("nan")),
                        ind.get("hv252_max", float("nan")),
                        vix_spike=vix_spike,
                    )
                    if opt is None:
                        print(f"  {sym}: RSI2={ind['rsi2']:.1f} — no option passes KB gates, skip")
                        continue
                    entry.update(opt)
                    entry["shares"]     = 0
                    entry["stop_price"] = 0.0
                else:
                    shares = max(1, int(RISK_BUDGET / (ATR_STOP_M * ind["atr14"])))
                    entry["shares"]     = shares
                    entry["stop_price"] = round(ind["close"] - ATR_STOP_M * ind["atr14"], 2)

                candidates.append(entry)

        # Most oversold first — KB §19 "sort by RSI2 asc"
        candidates.sort(key=lambda c: c["rsi2"])
        entries = candidates[:free_slots]

    return {"exits": exits, "entries": entries}


# ── Order execution — shares ───────────────────────────────────────────────────
def place_exit_order(client, exit: dict, dry_run: bool = False) -> str | None:
    sym    = exit["sym"]
    shares = exit["shares"]
    if dry_run:
        print(f"  [DRY RUN] Would SELL {shares} {sym} shares ({exit['reason']})")
        return "dry_run"

    stop_id = exit.get("stop_order_id")
    if stop_id and stop_id != "dry_run":
        try:
            client.cancel_order_by_id(stop_id)
        except Exception as e:
            print(f"  Warning: could not cancel stop {stop_id}: {e}")

    from alpaca.trading.requests import MarketOrderRequest
    from alpaca.trading.enums    import OrderSide, TimeInForce
    try:
        req   = MarketOrderRequest(symbol=sym, qty=shares,
                                   side=OrderSide.SELL, time_in_force=TimeInForce.DAY)
        order = client.submit_order(req)
        print(f"  SELL {shares} {sym}  id={order.id}  ({exit['reason']})")
        return str(order.id)
    except Exception as e:
        print(f"  ERROR submitting sell for {sym}: {e}")
        return None


def place_entry_order(client, entry: dict, dry_run: bool = False) -> tuple[str | None, str | None]:
    sym    = entry["sym"]
    shares = entry["shares"]
    stop   = entry["stop_price"]
    if dry_run:
        print(f"  [DRY RUN] Would BUY {shares} {sym} shares  stop=${stop:.2f}")
        return "dry_run", "dry_run"

    from alpaca.trading.requests import MarketOrderRequest, StopOrderRequest
    from alpaca.trading.enums    import OrderSide, TimeInForce
    buy_id = stop_id = None
    try:
        buy_req   = MarketOrderRequest(symbol=sym, qty=shares,
                                       side=OrderSide.BUY, time_in_force=TimeInForce.DAY)
        buy_order = client.submit_order(buy_req)
        buy_id    = str(buy_order.id)
        print(f"  BUY  {shares} {sym} at next open  id={buy_id}")
    except Exception as e:
        print(f"  ERROR submitting buy for {sym}: {e}")
        return None, None

    try:
        stop_req   = StopOrderRequest(symbol=sym, qty=shares,
                                      side=OrderSide.SELL,
                                      time_in_force=TimeInForce.GTC,
                                      stop_price=stop)
        stop_order = client.submit_order(stop_req)
        stop_id    = str(stop_order.id)
        print(f"  STOP {shares} {sym} @ ${stop:.2f}  id={stop_id}")
    except Exception as e:
        print(f"  WARNING: stop order for {sym} failed: {e}")

    return buy_id, stop_id


# ── Order execution — options ──────────────────────────────────────────────────
def _live_option_mid(opt_client, occ: str) -> float | None:
    """Fetch live mid price for an OCC symbol via Alpaca quote API."""
    try:
        from alpaca.data.requests import OptionLatestQuoteRequest
        resp = opt_client.get_option_latest_quote(
            OptionLatestQuoteRequest(symbol_or_symbols=occ)
        )
        q = resp.get(occ)
        if q and q.bid_price and q.ask_price:
            return (float(q.bid_price) + float(q.ask_price)) / 2.0
    except Exception:
        pass
    # Fallback: yfinance (slightly delayed but free)
    try:
        import yfinance as yf
        sym    = occ[:len(occ) - 15]  # strip date+type+strike suffix (rough)
        ticker = yf.Ticker(sym)
        expiry = f"20{occ[-15:-9][:2]}-{occ[-15:-9][2:4]}-{occ[-15:-9][4:6]}"
        opt_type = "calls" if occ[-9] == "C" else "puts"
        chain  = getattr(ticker.option_chain(expiry), opt_type)
        row    = chain[chain["contractSymbol"] == occ]
        if not row.empty:
            return float((row.iloc[0]["bid"] + row.iloc[0]["ask"]) / 2.0)
    except Exception:
        pass
    return None


def place_option_entry(client, opt_client, position: dict,
                       dry_run: bool = False) -> dict:
    """
    Submit limit option orders at morning open (9:35 AM).
    BTO long leg; STO short leg for spreads.
    Returns order ids and actual debit used.
    """
    long_occ  = position["long_occ"]
    short_occ = position.get("short_occ")
    structure = position["structure"]
    contracts = position.get("contracts", 1)

    if dry_run:
        est = position.get("est_debit", "?")
        if structure == "naked":
            print(f"  [DRY RUN] BTO {contracts} {long_occ}  est=${est}")
        else:
            print(f"  [DRY RUN] spread: BTO {long_occ} / STO {short_occ}  est_debit=${est}")
        return {"long_order_id": "dry_run", "short_order_id": "dry_run",
                "actual_debit": float(position.get("est_debit", 1.0))}

    from alpaca.trading.requests import LimitOrderRequest
    from alpaca.trading.enums    import OrderSide, TimeInForce

    # Get live prices; fall back to EOD estimate if unavailable
    long_mid   = _live_option_mid(opt_client, long_occ) or position.get("est_debit", 2.0)

    # KB §9 bid-ask gate — enforced here with live morning quotes
    try:
        from alpaca.data.requests import OptionLatestQuoteRequest
        resp = opt_client.get_option_latest_quote(
            OptionLatestQuoteRequest(symbol_or_symbols=long_occ)
        )
        q = resp.get(long_occ)
        if q and q.bid_price and q.ask_price and long_mid > 0:
            ba_pct = (float(q.ask_price) - float(q.bid_price)) / long_mid
            if ba_pct > OPT_MAX_BID_ASK_PCT:
                print(f"  SKIP {position['sym']}: bid-ask {ba_pct*100:.1f}% > "
                      f"{OPT_MAX_BID_ASK_PCT*100:.0f}% (live KB §9 gate)")
                return {"long_order_id": None, "short_order_id": None, "actual_debit": 0.0}
    except Exception:
        pass  # if quote unavailable, proceed (don't block on infra failure)

    long_limit = round(long_mid + 0.05, 2)  # pay slightly above mid for fills

    long_order_id = short_order_id = None

    # BTO long leg
    try:
        req = LimitOrderRequest(
            symbol=long_occ, qty=contracts,
            side=OrderSide.BUY, time_in_force=TimeInForce.DAY,
            limit_price=long_limit,
        )
        order = client.submit_order(req)
        long_order_id = str(order.id)
        print(f"  BTO {contracts} {long_occ}  lmt=${long_limit:.2f}  id={long_order_id}")
    except Exception as e:
        print(f"  ERROR BTO {long_occ}: {e}")
        return {"long_order_id": None, "short_order_id": None, "actual_debit": 0.0}

    # STO short leg (spread only)
    short_mid = 0.0
    if structure == "spread" and short_occ:
        short_mid   = _live_option_mid(opt_client, short_occ) or 0.0
        short_limit = round(max(short_mid - 0.05, short_mid * 0.90, 0.01), 2)
        try:
            req = LimitOrderRequest(
                symbol=short_occ, qty=contracts,
                side=OrderSide.SELL, time_in_force=TimeInForce.DAY,
                limit_price=short_limit,
            )
            order = client.submit_order(req)
            short_order_id = str(order.id)
            print(f"  STO {contracts} {short_occ}  lmt=${short_limit:.2f}  id={short_order_id}")
        except Exception as e:
            print(f"  WARNING: STO {short_occ} failed: {e}")

    actual_debit = long_limit - (short_mid if structure == "spread" else 0.0)
    return {
        "long_order_id":  long_order_id,
        "short_order_id": short_order_id,
        "actual_debit":   round(actual_debit, 2),
    }


def place_option_exit(client, opt_client, pos: dict,
                      reason: str, dry_run: bool = False) -> dict:
    """
    Close an option position: STC long leg, BTC short leg for spreads.
    Uses limit orders at current mid ± $0.05.
    """
    long_occ  = pos["long_occ"]
    short_occ = pos.get("short_occ")
    structure = pos.get("structure", "naked")
    contracts = pos.get("contracts", 1)

    if dry_run:
        print(f"  [DRY RUN] Close {long_occ}  ({reason})")
        return {"long_order_id": "dry_run", "short_order_id": "dry_run"}

    from alpaca.trading.requests import LimitOrderRequest, MarketOrderRequest
    from alpaca.trading.enums    import OrderSide, TimeInForce

    long_order_id = short_order_id = None

    # STC long leg
    long_mid = _live_option_mid(opt_client, long_occ)
    try:
        if long_mid and long_mid > 0.01:
            req = LimitOrderRequest(
                symbol=long_occ, qty=contracts,
                side=OrderSide.SELL, time_in_force=TimeInForce.DAY,
                limit_price=round(long_mid - 0.05, 2),
            )
        else:
            req = MarketOrderRequest(
                symbol=long_occ, qty=contracts,
                side=OrderSide.SELL, time_in_force=TimeInForce.DAY,
            )
        order = client.submit_order(req)
        long_order_id = str(order.id)
        print(f"  STC {contracts} {long_occ}  ({reason})  id={long_order_id}")
    except Exception as e:
        print(f"  ERROR STC {long_occ}: {e}")

    # BTC short leg (spread only)
    if structure == "spread" and short_occ:
        short_mid = _live_option_mid(opt_client, short_occ)
        try:
            if short_mid and short_mid > 0.01:
                req = LimitOrderRequest(
                    symbol=short_occ, qty=contracts,
                    side=OrderSide.BUY, time_in_force=TimeInForce.DAY,
                    limit_price=round(short_mid + 0.05, 2),
                )
            else:
                req = MarketOrderRequest(
                    symbol=short_occ, qty=contracts,
                    side=OrderSide.BUY, time_in_force=TimeInForce.DAY,
                )
            order = client.submit_order(req)
            short_order_id = str(order.id)
            print(f"  BTC {contracts} {short_occ}  id={short_order_id}")
        except Exception as e:
            print(f"  WARNING: BTC {short_occ}: {e}")

    return {"long_order_id": long_order_id, "short_order_id": short_order_id}


# ── Main EOD routine ───────────────────────────────────────────────────────────
def run_eod(dry_run: bool = False) -> dict:
    """
    Main EOD routine (~4:10 PM ET).
    Options mode: identifies contracts via yfinance, records signals; orders at morning.
    Shares mode:  submits market orders for next-day open.
    """
    now = datetime.now(ET)
    print(f"\n{'='*60}")
    print(f"Daily Trader EOD — {now:%Y-%m-%d %H:%M ET}  [{INSTRUMENT.upper()}]")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE (PAPER)'}")
    print(f"{'='*60}\n")

    client = None
    if not dry_run and INSTRUMENT == "shares":
        try:
            client, paper = _make_client()
            print(f"Alpaca: connected  paper={paper}\n")
        except Exception as e:
            print(f"Alpaca connection failed: {e}\n  Running as dry_run.\n")
            dry_run = True

    # 1. Refresh daily data
    print("Refreshing daily data...")
    indicators: dict[str, dict] = {}
    for sym in UNIVERSE:
        ind = compute_indicators(sym)
        if ind:
            indicators[sym] = ind
    print(f"  {len(indicators)}/{len(UNIVERSE)} symbols OK\n")

    # KB-4/KB-10: fetch VIX for entry gate and spike detection
    vix_now, vix_prev = _fetch_vix()
    vix_block = vix_now is not None and vix_now > VIX_BLOCK_ABOVE
    vix_spike = (vix_now is not None and vix_prev is not None
                 and vix_now - vix_prev > VIX_SPIKE_DAILY)
    if vix_now is not None:
        spike_str = f"  spike +{vix_now - vix_prev:.1f} → SPREADS ONLY" if vix_spike else ""
        block_str = "  → NO NEW ENTRIES" if vix_block else ""
        print(f"VIX: {vix_now:.1f} (prev {vix_prev:.1f}){spike_str}{block_str}\n")

    # 2. Load positions
    positions = _load_positions()
    open_pos  = [p for p in positions if p["status"] in ("open", "pending", "signal")]
    print(f"Open positions: {len(open_pos)}/{MAX_CONCURRENT}")
    for p in open_pos:
        ind   = indicators.get(p["sym"], {})
        rsi_s = f"{ind['rsi2']:.1f}" if isinstance(ind.get("rsi2"), float) else "?"
        if p.get("instrument") == "options":
            print(f"  {p['sym']:6}  {p.get('structure','?'):6}  "
                  f"entry={p['entry_date']}  "
                  f"debit=${p.get('entry_debit') or p.get('est_debit','?')}  "
                  f"rsi2={rsi_s}  [{p['status']}]")
        else:
            print(f"  {p['sym']:6}  shares  "
                  f"entry={p['entry_date']}  "
                  f"stop=${p.get('stop_price',0):.2f}  rsi2={rsi_s}  [{p['status']}]")

    # 3. Generate signals
    print()
    signals = generate_signals(indicators, open_pos,
                               vix_block=vix_block, vix_spike=vix_spike)

    # 4. Process exits
    if signals["exits"]:
        print(f"EXIT signals ({len(signals['exits'])}):")
        for ex in signals["exits"]:
            if ex.get("instrument") == "options":
                # Option closes are submitted at morning open (market is closed now)
                for p in positions:
                    if (p["sym"] == ex["sym"]
                            and p["status"] in ("open", "pending", "signal")):
                        p["status"]      = "exit_pending"
                        p["exit_reason"] = ex["reason"]
                        p["exit_date"]   = str(date.today())
                print(f"  {ex['sym']}: {ex['reason']} → exit_pending "
                      f"(option close submitted at morning open)")
            else:
                order_id = place_exit_order(client, ex, dry_run)
                for p in positions:
                    if (p["sym"] == ex["sym"]
                            and p["status"] in ("open", "pending")):
                        p["status"]        = "exit_pending"
                        p["exit_reason"]   = ex["reason"]
                        p["exit_date"]     = str(date.today())
                        p["exit_order_id"] = order_id
    else:
        print("EXIT signals: none")

    # 5. Process entries
    print()
    if signals["entries"]:
        print(f"ENTRY signals ({len(signals['entries'])}):")
        for en in signals["entries"]:
            if en.get("instrument") == "options":
                struct = en.get("structure", "?")
                print(f"  {en['sym']}: RSI2={en['rsi2']:.1f}  {struct}  "
                      f"occ={en.get('long_occ','?')}  "
                      f"est_debit=${en.get('est_debit','?')}  "
                      f"exp={en.get('expiry','?')}  "
                      f"IVR={en.get('ivr','?')}%  iv/hv={en.get('iv_hv','?')}")
                positions.append({
                    "sym":          en["sym"],
                    "entry_date":   en["entry_date"],
                    "entry_price":  en["close"],
                    "instrument":   "options",
                    "structure":    en.get("structure"),
                    "long_occ":     en.get("long_occ"),
                    "short_occ":    en.get("short_occ"),
                    "long_strike":  en.get("long_strike"),
                    "short_strike": en.get("short_strike"),
                    "expiry":       en.get("expiry"),
                    "dte":          en.get("dte"),
                    "est_debit":    en.get("est_debit"),
                    "entry_debit":  None,   # set after morning fill
                    "stop_debit":   None,   # set after morning fill (50% of entry_debit)
                    "contracts":    en.get("contracts", 1),
                    "width":        en.get("width"),
                    "iv_hv":        en.get("iv_hv"),
                    "hv21":         en.get("hv21"),
                    "atr14":        en.get("atr14"),
                    "sma200":       en.get("sma200"),
                    "shares":       0,
                    "stop_price":   0.0,
                    "direction":    "bull",
                    "status":       "signal",  # → pending at morning → open after fill
                    "stop_order_id": None,
                    "buy_order_id":  None,
                    "short_order_id": None,
                })
            else:
                buy_id, stop_id = place_entry_order(client, en, dry_run)
                if buy_id:
                    positions.append({
                        "sym":           en["sym"],
                        "entry_date":    en["entry_date"],
                        "entry_price":   en["close"],
                        "instrument":    "shares",
                        "shares":        en["shares"],
                        "stop_price":    en["stop_price"],
                        "atr14":         en["atr14"],
                        "sma200":        en["sma200"],
                        "direction":     "bull",
                        "status":        "pending",
                        "buy_order_id":  buy_id,
                        "stop_order_id": stop_id,
                    })
    else:
        print("ENTRY signals: none")

    _save_positions(positions)
    print(f"\n✓ Positions saved → {POSITIONS_FILE}")

    summary = {
        "date":    str(date.today()),
        "exits":   len(signals["exits"]),
        "entries": len(signals["entries"]),
        "open":    len([p for p in positions
                        if p["status"] in ("open", "pending", "signal")]),
    }
    print(f"\nSummary: {summary}\n")
    return summary


# ── Morning routine ────────────────────────────────────────────────────────────
def run_morning(dry_run: bool = False) -> None:
    """
    Call after market opens (~9:35 AM ET).
    Options: submit limit orders for 'signal' entries, confirm fills,
             check 50% premium stop (KB §9), process exit_pending closes.
    Shares:  confirm fills, update native stop orders.
    """
    now = datetime.now(ET)
    print(f"\nDaily Trader MORNING — {now:%Y-%m-%d %H:%M ET}  [{INSTRUMENT.upper()}]")

    # KB-4: VIX gate — skip NEW option entries if VIX > VIX_BLOCK_ABOVE
    vix_now, _vix_prev = _fetch_vix()
    vix_block = vix_now is not None and vix_now > VIX_BLOCK_ABOVE
    if vix_block:
        print(f"  ⚠ VIX={vix_now:.1f} > {VIX_BLOCK_ABOVE} — new entries deferred (KB-4 Appendix)")

    positions = _load_positions()

    if dry_run:
        for p in positions:
            if p["status"] == "signal":
                p["status"]      = "open"
                p["entry_debit"] = p.get("est_debit", 1.00)
                p["stop_debit"]  = round(float(p["entry_debit"]) * OPT_STOP_PCT, 2)
                print(f"  [DRY RUN] Option activated: {p['sym']}  "
                      f"{p.get('structure')}  debit=${p['entry_debit']}  "
                      f"stop_debit=${p['stop_debit']}")
            elif p["status"] == "pending":
                p["status"] = "open"
                print(f"  [DRY RUN] Shares activated: {p['sym']}  {p.get('shares')} sh")
            elif p["status"] == "exit_pending":
                p["status"] = "closed"
                print(f"  [DRY RUN] Closed: {p['sym']}")
        _save_positions(positions)
        return

    client, _  = _make_client()
    opt_client = _make_option_client()

    for p in positions:
        instr = p.get("instrument", "shares")

        # ── Submit option entry orders (signal → pending) ────────────────────
        if p["status"] == "signal" and instr == "options":
            if vix_block:
                print(f"  Holding {p['sym']} signal: VIX too high — order deferred (KB-4)")
                continue
            result = place_option_entry(client, opt_client, p, dry_run)
            if result.get("long_order_id"):
                p["status"]          = "pending"
                p["buy_order_id"]    = result["long_order_id"]
                p["short_order_id"]  = result.get("short_order_id")
                p["entry_debit"]     = result.get("actual_debit", p.get("est_debit"))

        # ── Confirm option fills (pending → open) ────────────────────────────
        elif p["status"] == "pending" and instr == "options":
            bid = p.get("buy_order_id")
            if bid and bid != "dry_run":
                try:
                    order = client.get_order_by_id(bid)
                    if str(order.status) in ("filled", "partially_filled"):
                        fill = float(order.filled_avg_price or p.get("entry_debit", 1.0))
                        p["entry_debit"] = fill
                        p["status"]      = "open"
                        # KB §9: stop = 50% of premium paid
                        p["stop_debit"]  = round(fill * OPT_STOP_PCT, 2)
                        print(f"  Option filled: {p['sym']}  {p.get('structure')}  "
                              f"debit=${fill:.2f}  stop_debit=${p['stop_debit']:.2f}")
                    else:
                        print(f"  Option pending (not filled): {p['sym']}  "
                              f"status={order.status}")
                except Exception as e:
                    print(f"  Error checking option fill {p['sym']}: {e}")

        # ── Check stops and profit targets on open options ────────────────────
        elif p["status"] == "open" and instr == "options":
            long_occ    = p.get("long_occ")
            stop_debit  = p.get("stop_debit")
            entry_debit = p.get("entry_debit")
            if long_occ and stop_debit and entry_debit:
                cur_mid = _live_option_mid(opt_client, long_occ)

                # KB §9: 50% premium stop
                if cur_mid is not None and cur_mid <= stop_debit:
                    print(f"  ⚠ PREMIUM STOP: {p['sym']}  mid=${cur_mid:.2f} "
                          f"≤ stop_debit=${stop_debit:.2f} — closing")
                    result = place_option_exit(
                        client, opt_client, p,
                        reason=f"premium_stop (mid=${cur_mid:.2f})"
                    )
                    p["status"]              = "exit_pending"
                    p["exit_reason"]         = f"premium_stop (mid=${cur_mid:.2f})"
                    p["exit_date"]           = str(date.today())
                    p["exit_long_order_id"]  = result.get("long_order_id")
                    p["exit_short_order_id"] = result.get("short_order_id")

                elif cur_mid is not None:
                    structure = p.get("structure", "naked")

                    # KB-1: 80% of max profit close for spreads (KB §24 Lowell p.82)
                    if structure == "spread" and p.get("short_occ") and p.get("width"):
                        short_mid  = _live_option_mid(opt_client, p["short_occ"]) or 0.0
                        spread_val = cur_mid - short_mid
                        max_profit = float(p["width"]) - float(entry_debit)
                        if (max_profit > 0
                                and spread_val - float(entry_debit) >= OPT_PROFIT_T2 * max_profit):
                            print(f"  ★ PROFIT TARGET 80%: {p['sym']} spread → closing (KB-1)")
                            result = place_option_exit(
                                client, opt_client, p, reason="profit_target_80pct"
                            )
                            p["status"]              = "exit_pending"
                            p["exit_reason"]         = "profit_target_80pct"
                            p["exit_date"]           = str(date.today())
                            p["exit_long_order_id"]  = result.get("long_order_id")
                            p["exit_short_order_id"] = result.get("short_order_id")

                    # KB-6: T1 partial at +50% gain (requires contracts ≥ 2)
                    elif (p.get("contracts", 1) >= 2
                            and cur_mid >= float(entry_debit) * (1 + OPT_PROFIT_T1)):
                        half = p["contracts"] // 2
                        print(f"  ★ T1 PARTIAL +50%: {p['sym']} — closing {half}/{p['contracts']} "
                              f"contracts (KB-6)")
                        p_half = dict(p)
                        p_half["contracts"] = half
                        result = place_option_exit(
                            client, opt_client, p_half, reason="t1_partial_50pct"
                        )
                        if result.get("long_order_id"):
                            p["contracts"] -= half

        # ── Submit and confirm option exits (exit_pending → closed) ──────────
        elif p["status"] == "exit_pending" and instr == "options":
            # Submit close if not yet submitted this cycle
            if not p.get("exit_long_order_id"):
                result = place_option_exit(
                    client, opt_client, p, reason=p.get("exit_reason", "exit")
                )
                p["exit_long_order_id"]  = result.get("long_order_id")
                p["exit_short_order_id"] = result.get("short_order_id")

            eid = p.get("exit_long_order_id")
            if eid and eid != "dry_run":
                try:
                    order = client.get_order_by_id(eid)
                    if str(order.status) in ("filled", "partially_filled"):
                        exit_debit      = float(order.filled_avg_price or 0)
                        p["exit_debit"] = exit_debit
                        p["status"]     = "closed"
                        entry = p.get("entry_debit", 0)
                        pnl   = (exit_debit - entry) * p.get("contracts", 1) * 100
                        print(f"  Option closed: {p['sym']}  exit_debit=${exit_debit:.2f}  "
                              f"P&L ${pnl:+.0f}  ({p.get('exit_reason','?')})")
                except Exception as e:
                    print(f"  Error confirming option exit {p['sym']}: {e}")

        # ── Shares: confirm fill (pending → open) ────────────────────────────
        elif p["status"] == "pending" and instr == "shares":
            bid = p.get("buy_order_id")
            if bid and bid != "dry_run":
                try:
                    order = client.get_order_by_id(bid)
                    if str(order.status) in ("filled", "partially_filled"):
                        fill_price      = float(order.filled_avg_price or p["entry_price"])
                        p["entry_price"] = fill_price
                        p["status"]      = "open"
                        new_stop         = round(fill_price - ATR_STOP_M * p["atr14"], 2)
                        p["stop_price"]  = new_stop
                        if p.get("stop_order_id") and p["stop_order_id"] != "dry_run":
                            try:
                                client.cancel_order_by_id(p["stop_order_id"])
                            except Exception:
                                pass
                        from alpaca.trading.requests import StopOrderRequest
                        from alpaca.trading.enums    import OrderSide, TimeInForce
                        stop_req   = StopOrderRequest(
                            symbol=p["sym"], qty=p["shares"],
                            side=OrderSide.SELL, time_in_force=TimeInForce.GTC,
                            stop_price=new_stop,
                        )
                        stop_order       = client.submit_order(stop_req)
                        p["stop_order_id"] = str(stop_order.id)
                        print(f"  Share filled: {p['sym']}  {p['shares']}sh "
                              f"@ ${fill_price:.2f}  stop=${new_stop:.2f}")
                    else:
                        print(f"  Share pending: {p['sym']}  status={order.status}")
                except Exception as e:
                    print(f"  Error checking share fill {p['sym']}: {e}")
            else:
                p["status"] = "open"

        # ── Shares: confirm exit (exit_pending → closed) ─────────────────────
        elif p["status"] == "exit_pending" and instr == "shares":
            eid = p.get("exit_order_id")
            if eid and eid != "dry_run":
                try:
                    order = client.get_order_by_id(eid)
                    if str(order.status) in ("filled", "partially_filled"):
                        p["exit_price"] = float(order.filled_avg_price or 0)
                        p["status"]     = "closed"
                        print(f"  Share closed: {p['sym']} @ ${p['exit_price']:.2f}  "
                              f"({p.get('exit_reason','?')})")
                except Exception as e:
                    print(f"  Error confirming share exit {p['sym']}: {e}")
            else:
                p["status"] = "closed"

    _save_positions(positions)
    print(f"✓ Positions updated → {POSITIONS_FILE}\n")


# ── Status display ─────────────────────────────────────────────────────────────
def status() -> None:
    positions = _load_positions()
    open_pos  = [p for p in positions if p["status"] in ("open", "pending", "signal")]
    closed    = [p for p in positions if p["status"] == "closed"]

    print(f"\nDaily Trader — {date.today()}  "
          f"({len(open_pos)}/{MAX_CONCURRENT} open)  [{INSTRUMENT.upper()}]\n")

    if open_pos:
        print("OPEN / PENDING / SIGNAL:")
        for p in open_pos:
            ind   = compute_indicators(p["sym"])
            rsi_s = f"{ind['rsi2']:.1f}" if ind else "?"
            if p.get("instrument") == "options":
                debit = p.get("entry_debit") or p.get("est_debit", "?")
                print(f"  {p['sym']:6}  {p.get('structure','?'):6}  {p['entry_date']}  "
                      f"occ={p.get('long_occ','?')}  "
                      f"debit=${debit}  stop_debit=${p.get('stop_debit','?')}  "
                      f"rsi2={rsi_s}  [{p['status']}]")
            else:
                close = ind["close"] if ind else None
                entry = p.get("entry_price", 0)
                pnl_s = (f"P&L ${((close - entry) * p['shares']):+.0f}"
                         if close and entry else "")
                print(f"  {p['sym']:6}  shares  {p['entry_date']}  {p.get('shares',0)}sh  "
                      f"entry=${entry:.2f}  stop=${p.get('stop_price',0):.2f}  "
                      f"rsi2={rsi_s}  {pnl_s}  [{p['status']}]")
    else:
        print("No open positions.")

    if closed:
        print(f"\nLast 5 closed:")
        for p in closed[-5:]:
            if p.get("instrument") == "options":
                entry = p.get("entry_debit", 0)
                exit_ = p.get("exit_debit", 0)
                pnl   = (exit_ - entry) * p.get("contracts", 1) * 100
                print(f"  {p['sym']:6}  {p.get('structure','?'):6}  "
                      f"{p.get('entry_date','?')} → {p.get('exit_date','?')}  "
                      f"debit ${entry:.2f}→${exit_:.2f}  P&L ${pnl:+.0f}  "
                      f"({p.get('exit_reason','?')})")
            else:
                entry = p.get("entry_price", 0)
                exit_ = p.get("exit_price", 0)
                pnl   = (exit_ - entry) * p.get("shares", 0)
                print(f"  {p['sym']:6}  shares  "
                      f"{p.get('entry_date','?')} → {p.get('exit_date','?')}  "
                      f"{p.get('shares',0)}sh  P&L ${pnl:+.0f}  "
                      f"({p.get('exit_reason','?')})")


# ── Emergency close all ────────────────────────────────────────────────────────
def close_all(dry_run: bool = False) -> None:
    """Close all open positions (options or shares)."""
    positions = _load_positions()
    open_pos  = [p for p in positions
                 if p["status"] in ("open", "pending", "signal")]
    if not open_pos:
        print("No open positions to close.")
        return

    if dry_run:
        for p in open_pos:
            print(f"  [DRY RUN] Would close {p['sym']} ({p.get('instrument','shares')})")
        return

    client, _  = _make_client()
    opt_client = _make_option_client()

    for p in open_pos:
        if p.get("instrument") == "options":
            place_option_exit(client, opt_client, p, reason="manual_closeall")
        else:
            place_exit_order(client, {
                "sym":           p["sym"],
                "shares":        p["shares"],
                "reason":        "manual_closeall",
                "stop_order_id": p.get("stop_order_id"),
            })
        p["status"]      = "exit_pending"
        p["exit_reason"] = "manual_closeall"
        p["exit_date"]   = str(date.today())

    _save_positions(positions)
    print("✓ Close-all submitted.")


# ── CLI ────────────────────────────────────────────────────────────────────────
def main() -> None:
    cmd     = sys.argv[1].lower() if len(sys.argv) > 1 else "status"
    dry_run = "--dry-run" in sys.argv or os.environ.get("DAILY_DRY_RUN", "").lower() == "true"

    if cmd == "eod":
        run_eod(dry_run=dry_run)
    elif cmd == "morning":
        run_morning(dry_run=dry_run)
    elif cmd == "status":
        status()
    elif cmd == "closeall":
        close_all(dry_run=dry_run)
    else:
        print(f"Unknown command: {cmd}")
        print("Usage: daily_trader.py [eod|morning|status|closeall] [--dry-run]")
        sys.exit(1)


if __name__ == "__main__":
    main()
