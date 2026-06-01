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
        log.info(f"[shares] BUY {qty} {symbol} → order {order.id}")
        return {"success": True, "symbol": symbol, "qty": qty,
                "order_id": str(order.id), "dry_run": False}
    except Exception as e:
        log.warning(f"[shares] BUY {symbol} failed: {e}")
        return {"success": False, "symbol": symbol, "message": str(e)}


def close(symbol: str, dry_run: bool = False) -> dict:
    """Close the full share position in `symbol` on the paper account."""
    symbol = symbol.upper()
    if dry_run:
        log.info(f"[shares dry_run] CLOSE {symbol}")
        return {"success": True, "symbol": symbol, "order_id": "dry_run", "dry_run": True}
    try:
        c = _client()
        order = c.close_position(symbol)
        log.info(f"[shares] CLOSE {symbol} → order {getattr(order,'id','?')}")
        return {"success": True, "symbol": symbol,
                "order_id": str(getattr(order, "id", "")), "dry_run": False}
    except Exception as e:
        log.warning(f"[shares] CLOSE {symbol} failed: {e}")
        return {"success": False, "symbol": symbol, "message": str(e)}


def current_price(symbol: str) -> float | None:
    """Latest share price for exit checks (reuses trader's data path)."""
    try:
        px, _chg, _sess = trader.get_symbol_price(symbol.upper())
        return float(px) if px else None
    except Exception:
        return None
