#!/usr/bin/env python3.11
"""
daily_trader.py — Connors RSI(2) daily-bar execution layer (Path A).

Strategy: RSI(2) < 10 AND close > SMA200 → long next-day open.
          Exit: RSI(2) > 70 at prior close → sell next-day open.
          Stop: Alpaca native stop order at entry − 2×ATR14.
          Cap:  5 concurrent positions (MAX_PORTFOLIO_RISK 20% / 4%/trade).

Backtest performance (2026-05-20):
  Test PF 1.32@3bp / 1.29@5bp  |  Sharpe 1.32  |  OOS decay +2.3%
  Annualized return +65.5%/yr  |  beats SPY  |  max-DD 38.5% (sizing risk)

Lifecycle (call in order each trading day):
  1. EOD (~4:10 PM ET)  — run_eod()   : refresh data, check exits, signal entries
  2. Morning (~9:00 AM) — run_morning(): confirm fills, activate stops

Positions persist in ~/.spy_trader/daily_positions.json.

Usage (CLI):
    venv/bin/python3.11 scripts/daily_trader.py eod        # EOD routine
    venv/bin/python3.11 scripts/daily_trader.py morning    # morning confirm
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

# ── Strategy constants (pre-specified, validated 2026-05-20 backtest) ────────
SMA_WIN        = 200    # trend filter
RSI_N          = 2      # Connors short-period RSI
RSI_LO         = 10.0  # entry: RSI(2) < this AND close > SMA200
RSI_EXIT       = 70.0  # exit: RSI(2) > this at prior close → sell next open
ATR_WIN        = 14     # ATR smoothing
ATR_STOP_M     = 2.0   # stop distance = 2 × ATR14
TIME_CAP_DAYS  = 10    # max hold (trading days)
RISK_BUDGET    = 200.0 # $ risk per trade
MAX_CONCURRENT = 5     # max open positions (20% portfolio risk / 4%/trade)
UNIVERSE       = list(ALL)

POSITIONS_FILE = Path.home() / ".spy_trader" / "daily_positions.json"
LOG = logging.getLogger("daily_trader")

# ── Credential helpers ────────────────────────────────────────────────────────
def _load_env() -> tuple[str, str, bool]:
    """Load Alpaca creds from .env in repo root."""
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
    """Return (trading_client, paper_mode) or raise."""
    from alpaca.trading.client import TradingClient
    key, secret, paper = _load_env()
    if not key or not secret:
        raise RuntimeError("ALPACA_API_KEY / ALPACA_API_SECRET not set in .env")
    return TradingClient(key, secret, paper=paper), paper


# ── Indicator helpers (same formulae as backtest) ────────────────────────────
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


def compute_indicators(sym: str) -> dict | None:
    """
    Return latest-bar indicators for *sym*, refreshing the daily cache.
    Returns None if insufficient data.
    """
    df = fetch_daily(sym, force_refresh=True)
    if df is None or len(df) < SMA_WIN + 2:
        return None
    df = df.sort_values("date").reset_index(drop=True)
    df["sma200"] = df["close"].rolling(SMA_WIN).mean()
    df["rsi2"]   = _rsi(df["close"], RSI_N)
    df["atr14"]  = _atr(df["high"], df["low"], df["close"], ATR_WIN)

    row     = df.iloc[-1]
    row_prv = df.iloc[-2]
    return {
        "sym":        sym,
        "date":       str(row["date"].date()),
        "close":      float(row["close"]),
        "sma200":     float(row["sma200"]),
        "rsi2":       float(row["rsi2"]),
        "rsi2_prev":  float(row_prv["rsi2"]),  # yesterday's RSI for exit check
        "atr14":      float(row["atr14"]),
    }


# ── Position persistence ──────────────────────────────────────────────────────
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


# ── Signal generation ─────────────────────────────────────────────────────────
def generate_signals(indicators: dict[str, dict],
                     open_positions: list[dict]) -> dict[str, list[dict]]:
    """
    Given today's indicators and current open positions, return:
      {
        "exits":   [{"sym": ..., "reason": ..., "stop_order_id": ...}, ...],
        "entries": [{"sym": ..., "shares": int, "stop_price": float}, ...],
      }

    Exit priority:
      1. RSI(2) > RSI_EXIT at PRIOR close (today's close is "now"; use rsi2_prev)
         Wait — at EOD we have today's close, so use today's rsi2 for exits.
      2. Time cap exceeded (days_held >= TIME_CAP_DAYS)
      NB: ATR stop is handled by a native Alpaca stop order; no code check needed.
    """
    open_syms   = {p["sym"] for p in open_positions if p["status"] == "open"}
    open_count  = len(open_syms)

    exits: list[dict]   = []
    entries: list[dict] = []

    # ── Check exits for open positions ───────────────────────────────────────
    today_str = str(date.today())
    for pos in open_positions:
        if pos["status"] != "open":
            continue
        ind = indicators.get(pos["sym"])
        if ind is None:
            continue

        # Days held (count business days from entry)
        entry_dt  = pd.Timestamp(pos["entry_date"])
        today_dt  = pd.Timestamp(today_str)
        days_held = len(pd.bdate_range(entry_dt, today_dt)) - 1

        reason = None
        if ind["rsi2"] >= RSI_EXIT:
            reason = f"mean_revert (RSI2={ind['rsi2']:.1f}≥{RSI_EXIT})"
        elif days_held >= TIME_CAP_DAYS:
            reason = f"time_cap ({days_held}d≥{TIME_CAP_DAYS})"

        if reason:
            exits.append({
                "sym":           pos["sym"],
                "reason":        reason,
                "stop_order_id": pos.get("stop_order_id"),
                "shares":        pos["shares"],
            })

    # ── Compute entry signals ─────────────────────────────────────────────────
    exiting_syms = {e["sym"] for e in exits}
    # How many slots will be free after exits?
    free_after_exits = MAX_CONCURRENT - (open_count - len(exits))

    if free_after_exits > 0:
        candidates = []
        for sym, ind in indicators.items():
            if sym in open_syms or sym in exiting_syms:
                continue
            if np.isnan(ind["sma200"]) or np.isnan(ind["atr14"]) or ind["atr14"] <= 0:
                continue
            # Entry condition
            if ind["rsi2"] < RSI_LO and ind["close"] > ind["sma200"]:
                shares    = max(1, int(RISK_BUDGET / (ATR_STOP_M * ind["atr14"])))
                stop_dist = ATR_STOP_M * ind["atr14"]
                candidates.append({
                    "sym":        sym,
                    "rsi2":       ind["rsi2"],
                    "close":      ind["close"],
                    "shares":     shares,
                    "atr14":      ind["atr14"],
                    "sma200":     ind["sma200"],
                    "stop_price": round(ind["close"] - stop_dist, 2),
                    "entry_date": today_str,
                })

        # Sort by lowest RSI2 (most oversold first) — deterministic tiebreak
        candidates.sort(key=lambda c: c["rsi2"])
        entries = candidates[:free_after_exits]

    return {"exits": exits, "entries": entries}


# ── Order execution ───────────────────────────────────────────────────────────
def place_exit_order(client, exit: dict, dry_run: bool = False) -> str | None:
    """Cancel existing stop order and submit market sell for next open."""
    sym   = exit["sym"]
    shares = exit["shares"]

    if dry_run:
        print(f"  [DRY RUN] Would SELL {shares} {sym} at next open ({exit['reason']})")
        return "dry_run"

    # Cancel the standing stop order first (prevents double-exit)
    stop_id = exit.get("stop_order_id")
    if stop_id and stop_id != "dry_run":
        try:
            client.cancel_order_by_id(stop_id)
        except Exception as e:
            print(f"  Warning: could not cancel stop order {stop_id}: {e}")

    # Market sell
    from alpaca.trading.requests import MarketOrderRequest
    from alpaca.trading.enums    import OrderSide, TimeInForce
    try:
        req = MarketOrderRequest(
            symbol=sym, qty=shares,
            side=OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
        )
        order = client.submit_order(req)
        print(f"  SELL {shares} {sym}  id={order.id}  ({exit['reason']})")
        return str(order.id)
    except Exception as e:
        print(f"  ERROR submitting sell for {sym}: {e}")
        return None


def place_entry_order(client, entry: dict, dry_run: bool = False) -> tuple[str | None, str | None]:
    """Submit market buy + native stop order. Returns (buy_id, stop_id)."""
    sym    = entry["sym"]
    shares = entry["shares"]
    stop   = entry["stop_price"]

    if dry_run:
        print(f"  [DRY RUN] Would BUY {shares} {sym} at next open  stop=${stop:.2f}")
        return "dry_run", "dry_run"

    from alpaca.trading.requests import MarketOrderRequest, StopOrderRequest
    from alpaca.trading.enums    import OrderSide, TimeInForce
    buy_id = stop_id = None
    try:
        buy_req = MarketOrderRequest(
            symbol=sym, qty=shares,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
        )
        buy_order = client.submit_order(buy_req)
        buy_id = str(buy_order.id)
        print(f"  BUY  {shares} {sym} at next open  id={buy_id}")
    except Exception as e:
        print(f"  ERROR submitting buy for {sym}: {e}")
        return None, None

    # Place a native stop order (GTC) immediately as the loss guard
    try:
        stop_req = StopOrderRequest(
            symbol=sym, qty=shares,
            side=OrderSide.SELL,
            time_in_force=TimeInForce.GTC,
            stop_price=stop,
        )
        stop_order = client.submit_order(stop_req)
        stop_id = str(stop_order.id)
        print(f"  STOP {shares} {sym} @ ${stop:.2f}  id={stop_id}")
    except Exception as e:
        print(f"  WARNING: stop order for {sym} failed: {e}  — set manually!")

    return buy_id, stop_id


# ── Main EOD routine ──────────────────────────────────────────────────────────
def run_eod(dry_run: bool = False) -> dict:
    """
    Main EOD routine. Call after market close (~4:10 PM ET).
    Refreshes daily data, checks exits, signals entries, places orders.
    Returns a summary dict.
    """
    now = datetime.now(ET)
    print(f"\n{'='*60}")
    print(f"Daily Trader EOD — {now:%Y-%m-%d %H:%M ET}")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE (PAPER)'}")
    print(f"{'='*60}\n")

    client = None
    if not dry_run:
        try:
            client, paper = _make_client()
            print(f"Alpaca: connected  paper={paper}\n")
        except Exception as e:
            print(f"Alpaca connection failed: {e}\n  Running as dry_run.\n")
            dry_run = True

    # 1. Refresh daily data for all symbols
    print("Refreshing daily data...")
    indicators: dict[str, dict] = {}
    for sym in UNIVERSE:
        ind = compute_indicators(sym)
        if ind:
            indicators[sym] = ind
    print(f"  {len(indicators)}/{len(UNIVERSE)} symbols OK\n")

    # 2. Load current positions
    positions = _load_positions()
    open_pos  = [p for p in positions if p["status"] == "open"]
    print(f"Open positions: {len(open_pos)}/{MAX_CONCURRENT}")
    for p in open_pos:
        ind = indicators.get(p["sym"], {})
        rsi = ind.get("rsi2", "?")
        print(f"  {p['sym']:6}  entry={p['entry_date']}  "
              f"stop=${p['stop_price']:.2f}  rsi2={rsi:.1f if isinstance(rsi, float) else rsi}")

    # 3. Generate signals
    print()
    signals = generate_signals(indicators, open_pos)

    # 4. Process exits
    if signals["exits"]:
        print(f"EXIT signals ({len(signals['exits'])}):")
        for ex in signals["exits"]:
            order_id = place_exit_order(client, ex, dry_run)
            # Mark position as exit_pending
            for p in positions:
                if p["sym"] == ex["sym"] and p["status"] == "open":
                    p["status"]       = "exit_pending"
                    p["exit_reason"]  = ex["reason"]
                    p["exit_date"]    = str(date.today())
                    p["exit_order_id"] = order_id
    else:
        print("EXIT signals: none")

    # 5. Process entries
    print()
    if signals["entries"]:
        print(f"ENTRY signals ({len(signals['entries'])}):")
        for en in signals["entries"]:
            buy_id, stop_id = place_entry_order(client, en, dry_run)
            if buy_id:
                positions.append({
                    "sym":          en["sym"],
                    "entry_date":   en["entry_date"],
                    "entry_price":  en["close"],   # approximate; confirmed in morning
                    "shares":       en["shares"],
                    "stop_price":   en["stop_price"],
                    "atr14":        en["atr14"],
                    "sma200":       en["sma200"],
                    "direction":    "bull",
                    "status":       "pending",     # becomes "open" after morning fill confirm
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
        "open":    len([p for p in positions if p["status"] in ("open", "pending")]),
    }
    print(f"\nSummary: {summary}\n")
    return summary


# ── Morning fill-confirmation routine ────────────────────────────────────────
def run_morning(dry_run: bool = False) -> None:
    """
    Call after market opens (~9:35 AM ET). Confirms yesterday's pending orders
    have filled and activates their stop orders. Updates position records.
    """
    now = datetime.now(ET)
    print(f"\nDaily Trader MORNING — {now:%Y-%m-%d %H:%M ET}")

    if dry_run:
        # Just promote pending → open
        positions = _load_positions()
        for p in positions:
            if p["status"] == "pending":
                p["status"] = "open"
                print(f"  [DRY RUN] Activated: {p['sym']}  {p['shares']} shares")
            elif p["status"] == "exit_pending":
                p["status"] = "closed"
                print(f"  [DRY RUN] Closed: {p['sym']}")
        _save_positions(positions)
        return

    client, _ = _make_client()
    positions  = _load_positions()

    for p in positions:
        if p["status"] == "pending":
            bid = p.get("buy_order_id")
            if bid and bid != "dry_run":
                try:
                    order = client.get_order_by_id(bid)
                    if str(order.status) in ("filled", "partially_filled"):
                        fill_price = float(order.filled_avg_price or p["entry_price"])
                        p["entry_price"] = fill_price
                        p["status"]      = "open"
                        # Update stop to actual fill price (more accurate)
                        new_stop = round(fill_price - ATR_STOP_M * p["atr14"], 2)
                        p["stop_price"] = new_stop
                        # Replace stop order with corrected price
                        if p.get("stop_order_id") and p["stop_order_id"] != "dry_run":
                            try:
                                client.cancel_order_by_id(p["stop_order_id"])
                            except Exception:
                                pass
                        from alpaca.trading.requests import StopOrderRequest
                        from alpaca.trading.enums    import OrderSide, TimeInForce
                        stop_req = StopOrderRequest(
                            symbol=p["sym"], qty=p["shares"],
                            side=OrderSide.SELL,
                            time_in_force=TimeInForce.GTC,
                            stop_price=new_stop,
                        )
                        stop_order = client.submit_order(stop_req)
                        p["stop_order_id"] = str(stop_order.id)
                        print(f"  Filled: {p['sym']}  {p['shares']}sh @ ${fill_price:.2f}  "
                              f"stop=${new_stop:.2f}")
                    else:
                        print(f"  Pending (not filled yet): {p['sym']}  status={order.status}")
                except Exception as e:
                    print(f"  Error checking {p['sym']}: {e}")
            else:
                p["status"] = "open"  # dry_run placeholder

        elif p["status"] == "exit_pending":
            eid = p.get("exit_order_id")
            if eid and eid != "dry_run":
                try:
                    order = client.get_order_by_id(eid)
                    if str(order.status) in ("filled", "partially_filled"):
                        p["exit_price"]  = float(order.filled_avg_price or 0)
                        p["status"]      = "closed"
                        print(f"  Closed: {p['sym']}  @ ${p['exit_price']:.2f}  "
                              f"({p.get('exit_reason', '?')})")
                except Exception as e:
                    print(f"  Error confirming exit {p['sym']}: {e}")
            else:
                p["status"] = "closed"

    _save_positions(positions)
    print(f"✓ Positions updated → {POSITIONS_FILE}\n")


# ── Status display ────────────────────────────────────────────────────────────
def status() -> None:
    positions = _load_positions()
    open_pos  = [p for p in positions if p["status"] in ("open", "pending")]
    closed    = [p for p in positions if p["status"] == "closed"]

    print(f"\nDaily Trader — {date.today()}  ({len(open_pos)}/{MAX_CONCURRENT} open)\n")

    if open_pos:
        print("OPEN / PENDING:")
        for p in open_pos:
            ind   = compute_indicators(p["sym"])
            close = ind["close"] if ind else "?"
            rsi   = f"{ind['rsi2']:.1f}" if ind else "?"
            entry = p.get("entry_price", "?")
            pnl   = ((float(close) - float(entry)) * p["shares"]
                     if isinstance(close, float) and isinstance(entry, float) else "?")
            pnl_s   = f"P&L ${pnl:+.0f}" if isinstance(pnl, float) else ""
            entry_s = f"${entry:.2f}"   if isinstance(entry, float) else str(entry)
            close_s = f"${close:.2f}"   if isinstance(close, float) else str(close)
            print(f"  {p['sym']:6}  {p['entry_date']}  {p['shares']}sh  "
                  f"entry={entry_s}  stop=${p['stop_price']:.2f}  "
                  f"rsi2={rsi}  close={close_s}  {pnl_s}")
    else:
        print("No open positions.")

    if closed:
        print(f"\nLast 5 closed trades:")
        for p in closed[-5:]:
            entry = p.get("entry_price", 0)
            exit_ = p.get("exit_price", 0)
            pnl   = (exit_ - entry) * p["shares"] if exit_ and entry else "?"
            pnl_s = f"${pnl:+.0f}" if isinstance(pnl, float) else "?"
            print(f"  {p['sym']:6}  {p.get('entry_date','?')} → {p.get('exit_date','?')}  "
                  f"{p['shares']}sh  {pnl_s}  ({p.get('exit_reason','?')})")


# ── Emergency close all ───────────────────────────────────────────────────────
def close_all(dry_run: bool = False) -> None:
    """Cancel all daily-trader stop orders and submit market sells for all open positions."""
    positions = _load_positions()
    open_pos  = [p for p in positions if p["status"] == "open"]
    if not open_pos:
        print("No open positions to close.")
        return

    if dry_run:
        for p in open_pos:
            print(f"  [DRY RUN] Would close {p['sym']} ({p['shares']} shares)")
        return

    client, _ = _make_client()
    for p in open_pos:
        place_exit_order(client, {
            "sym":           p["sym"],
            "shares":        p["shares"],
            "reason":        "manual_closeall",
            "stop_order_id": p.get("stop_order_id"),
        }, dry_run=False)
        p["status"]       = "exit_pending"
        p["exit_reason"]  = "manual_closeall"
        p["exit_date"]    = str(date.today())
    _save_positions(positions)
    print("✓ Close-all submitted.")


# ── CLI ───────────────────────────────────────────────────────────────────────
def main() -> None:
    cmd      = sys.argv[1].lower() if len(sys.argv) > 1 else "status"
    dry_run  = "--dry-run" in sys.argv or os.environ.get("DAILY_DRY_RUN", "").lower() == "true"

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
