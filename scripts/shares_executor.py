#!/usr/bin/env python3
"""
shares_executor.py — places PAPER share orders for the autonomous engine (REQ-606).

Minimal, safe, market-order share execution on the Alpaca PAPER account. Used by
auto_engine in execute mode. Mirrors daily_trader's order pattern.

Safety:
  • refuses if not connected or not in paper mode (extra guard — never live here)
  • dry_run=True simulates (no order sent)
  • fixed-qty BUY (REQ-606: 10 shares); full close on exit
"""
from __future__ import annotations
import logging

import spy_auto_trader as trader

log = logging.getLogger("shares_executor")


def _client():
    c = getattr(trader, "TRADING_CLIENT", None)
    if c is None:
        raise RuntimeError("not connected to Alpaca")
    if not getattr(trader, "PAPER_MODE", True):
        # hard guard: this autonomous path is PAPER-ONLY by design
        raise RuntimeError("shares_executor refuses to run on a LIVE account")
    return c


def buy(symbol: str, qty: int, dry_run: bool = False) -> dict:
    """Market BUY `qty` shares of `symbol` on the paper account."""
    symbol = symbol.upper()
    if qty <= 0:
        return {"success": False, "symbol": symbol, "message": "qty<=0"}
    if dry_run:
        log.info(f"[shares dry_run] BUY {qty} {symbol}")
        return {"success": True, "symbol": symbol, "qty": qty,
                "order_id": "dry_run", "dry_run": True}
    try:
        from alpaca.trading.requests import MarketOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce
        c = _client()
        order = c.submit_order(MarketOrderRequest(
            symbol=symbol, qty=qty, side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY))
        fill = _fill_price(c, order.id)   # best-effort actual fill (paper fills fast)
        log.info(f"[shares] BUY {qty} {symbol} → order {order.id} fill={fill}")
        return {"success": True, "symbol": symbol, "qty": qty,
                "order_id": str(order.id), "fill_price": fill, "dry_run": False}
    except Exception as e:
        log.warning(f"[shares] BUY {symbol} failed: {e}")
        return {"success": False, "symbol": symbol, "message": str(e)}


# ── Protective resting stop (2026-09-11) ─────────────────────────────────────
# manage_exits only POLLS the stop on the position_monitor tick, so the stop is
# only as reliable as this process. Ledger evidence: 17 of 40 stop exits realised
# worse than -3.5% (SMCI -20.6%, ORCL -12.8%, COHR -11.4%) — $2,878 beyond a
# clean -3%. The poll is not broken (it stopped HOOD and XLK at -3.1% on the same
# day SMCI ran to -20.6%); it just cannot act while the app is down, the monitor
# is wedged, the Mac is asleep, a symbol's price feed is dead, or the market is
# closed. A GTC stop RESTING AT THE BROKER holds through all of those.
# Kill switch: config.PROTECTIVE_STOP_ENABLED.

def open_sell_orders(symbol: str) -> list:
    """Resting SELL orders on `symbol` (the protective stops we placed)."""
    try:
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus, OrderSide
        return list(_client().get_orders(GetOrdersRequest(
            status=QueryOrderStatus.OPEN, symbols=[symbol.upper()],
            side=OrderSide.SELL)))
    except Exception as e:
        log.debug(f"[shares] open sell-order lookup {symbol}: {e}")
        return []


def cancel_sell_orders(symbol: str, dry_run: bool = False) -> int:
    """Cancel every resting SELL order on `symbol`; returns how many were cancelled.
    Must run before a market close — a resting stop RESERVES the shares, so
    close_position would otherwise fail with 'insufficient qty available'."""
    if dry_run:
        return 0
    symbol = symbol.upper()
    n = 0
    for o in open_sell_orders(symbol):
        try:
            _client().cancel_order_by_id(o.id)
            n += 1
        except Exception as e:
            log.warning(f"[shares] cancel resting sell {getattr(o, 'id', '?')} "
                        f"on {symbol}: {e}")
    if n:
        log.info(f"[shares] cancelled {n} resting sell order(s) on {symbol}")
    return n


def place_protective_stop(symbol: str, qty: int, stop_price: float,
                          dry_run: bool = True, last_price: float | None = None) -> dict:
    """Rest a GTC SELL stop at `stop_price` so the position stays protected when
    this process can't act. Cancels any existing resting stop first so a symbol
    never carries two claims on the same shares.

    Refuses when the stop is at or above the market. A sell stop above the last
    price triggers the instant it is accepted, so placing one is not protection —
    it is an immediate market liquidation. This matters most when an already
    underwater position is first brought under management (a restart running
    _protect_untracked_stocks over the open book): its entry-derived stop can sit
    above today's price. Those exits belong to the polled logic, not to us."""
    symbol = symbol.upper()
    stop_price = round(float(stop_price or 0.0), 2)
    if qty <= 0 or stop_price <= 0:
        return {"success": False, "symbol": symbol, "message": "bad qty/stop"}
    if not dry_run:
        px = last_price if last_price is not None else current_price(symbol)
        if px and stop_price >= float(px):
            log.warning(f"[shares] refusing resting stop {symbol} @ ${stop_price:.2f} "
                        f"— at/above market ${float(px):.2f}; it would fill instantly. "
                        f"Leaving the exit to the polled stop.")
            return {"success": False, "symbol": symbol,
                    "message": f"stop {stop_price} >= market {px}"}
    if dry_run:
        log.info(f"[shares dry_run] STOP {qty} {symbol} @ ${stop_price:.2f}")
        return {"success": True, "symbol": symbol, "stop_price": stop_price,
                "order_id": "dry_run", "dry_run": True}
    try:
        from alpaca.trading.requests import StopOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce
        c = _client()
        cancel_sell_orders(symbol)
        order = c.submit_order(StopOrderRequest(
            symbol=symbol, qty=int(qty), side=OrderSide.SELL,
            time_in_force=TimeInForce.GTC, stop_price=stop_price))
        log.info(f"[shares] STOP {qty} {symbol} @ ${stop_price:.2f} → order {order.id}")
        return {"success": True, "symbol": symbol, "stop_price": stop_price,
                "order_id": str(order.id), "dry_run": False}
    except Exception as e:
        log.warning(f"[shares] protective stop {symbol} @ ${stop_price:.2f} failed: {e}")
        return {"success": False, "symbol": symbol, "message": str(e)}


def close(symbol: str, dry_run: bool = False) -> dict:
    """Close the full share position in `symbol` on the paper account."""
    symbol = symbol.upper()
    if dry_run:
        log.info(f"[shares dry_run] CLOSE {symbol}")
        return {"success": True, "symbol": symbol, "order_id": "dry_run", "dry_run": True}
    try:
        c = _client()
        cancel_sell_orders(symbol)   # free the shares a resting stop has reserved
        order = c.close_position(symbol)
        log.info(f"[shares] CLOSE {symbol} → order {getattr(order,'id','?')}")
        return {"success": True, "symbol": symbol,
                "order_id": str(getattr(order, "id", "")), "dry_run": False}
    except Exception as e:
        log.warning(f"[shares] CLOSE {symbol} failed: {e}")
        return {"success": False, "symbol": symbol, "message": str(e)}


def _fill_price(client, order_id) -> float | None:
    """Best-effort actual fill price (paper market orders fill near-instantly)."""
    try:
        import time as _t
        for _ in range(3):
            o = client.get_order_by_id(order_id)
            if getattr(o, "filled_avg_price", None):
                return float(o.filled_avg_price)
            _t.sleep(0.4)
    except Exception:
        pass
    return None


def held_quantities() -> dict | None:
    """sym → qty for every equity position actually in the account.

    Returns None when the lookup fails — callers MUST treat that as "unknown" and
    never as "nothing held", or a transient API blip would reap the whole store."""
    try:
        out = {}
        for p in _client().get_all_positions():
            if "option" in str(getattr(p, "asset_class", "")).lower():
                continue
            out[str(p.symbol).upper()] = int(float(p.qty))
        return out
    except Exception as e:
        log.debug(f"[shares] account position lookup failed: {e}")
        return None


def resting_sell_quantities() -> dict | None:
    """symbol → total share qty currently resting in open SELL orders.

    Lets the exit loop VERIFY its protective stops against the broker instead of
    trusting a stored order id. A stop can vanish without the app knowing — the
    stale-order sweep cancelled all 8 on 2026-09-11 — and a stored id that no
    longer exists is worse than no id, because it suppresses the re-place.
    Returns None on failure; callers must read that as "unknown", never as
    "nothing is resting", or a transient blip would re-place every stop."""
    try:
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus, OrderSide
        out: dict = {}
        for o in _client().get_orders(GetOrdersRequest(
                status=QueryOrderStatus.OPEN, side=OrderSide.SELL)):
            sym = str(o.symbol).upper()
            out[sym] = out.get(sym, 0) + int(float(o.qty or 0))
        return out
    except Exception as e:
        log.debug(f"[shares] resting sell-order lookup failed: {e}")
        return None


def last_sell_fill(symbol: str) -> float | None:
    """Fill price of the most recent closed SELL on `symbol` — prices an exit that
    happened outside the engine, i.e. a resting protective stop that triggered."""
    try:
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus, OrderSide
        orders = _client().get_orders(GetOrdersRequest(
            status=QueryOrderStatus.CLOSED, symbols=[symbol.upper()],
            side=OrderSide.SELL, limit=5))
        for o in orders:                    # default sort is most-recent-first
            if getattr(o, "filled_avg_price", None):
                return float(o.filled_avg_price)
    except Exception as e:
        log.debug(f"[shares] last sell fill {symbol}: {e}")
    return None


def close_fill(symbol: str) -> float | None:
    """Approximate close fill = latest price (for slippage on exit)."""
    return current_price(symbol)


def current_price(symbol: str) -> float | None:
    """Latest share price for exit checks (reuses trader's data path)."""
    try:
        px, _chg, _sess = trader.get_symbol_price(symbol.upper())
        return float(px) if px else None
    except Exception:
        return None
