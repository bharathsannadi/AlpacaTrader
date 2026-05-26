#!/usr/bin/env python3.11
"""
screener_executor.py — Execute a screener options recommendation via Alpaca.

Called from app.py when the user clicks "Execute" on an options row.
Reuses the KB-validated contract selection logic from daily_trader.py.

OCC Symbol format: TICKER + YYMMDD + C/P + STRIKE×1000 (8 digits, zero-padded)
Example: NVDA260620C00120000  (NVDA, Jun 20 2026, Call, $120 strike)

KB rules applied (same as daily_trader.py):
  §9  — OI ≥ 200, bid-ask < 5% of mid
  §5  — ATM long leg; OTM short leg debit 25–45% of spread width
  §4  — max risk ≤ $400 per trade
  §1  — DTE validated by screener (21-30 preferred)
"""
from __future__ import annotations
import os
import logging
from pathlib import Path

log = logging.getLogger("screener_executor")

# ── KB-sourced constants (mirror daily_trader.py) ─────────────────────────────
OPT_MIN_OI           = 200     # KB §9: minimum open interest for liquidity
OPT_MAX_BID_ASK_PCT  = 0.05   # KB §9: bid-ask < 5% of mid (live quote gate)
OPT_SPREAD_RATIO_LO  = 0.25   # KB §5: spread debit ≥ 25% of width
OPT_SPREAD_RATIO_HI  = 0.45   # KB §5: spread debit ≤ 45% of width
RISK_BUDGET          = 400.0  # KB §4: $400 max loss per trade


# ── Credential helpers (same pattern as daily_trader.py) ──────────────────────
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


def _make_clients():
    """Returns (TradingClient, OptionHistoricalDataClient, is_paper)."""
    from alpaca.trading.client import TradingClient
    from alpaca.data.historical.option import OptionHistoricalDataClient
    key, secret, paper = _load_env()
    if not key or not secret:
        raise RuntimeError("ALPACA_API_KEY / ALPACA_API_SECRET not set in .env")
    tc = TradingClient(key, secret, paper=paper)
    oc = OptionHistoricalDataClient(key, secret)
    return tc, oc, paper


def _normalize_alpaca_status(raw: str) -> str:
    """Collapse Alpaca's many status enum values into the categories our
    rollback / dedup logic actually cares about."""
    s = (raw or "").lower().split(".")[-1]
    if s in ("filled", "done_for_day"):
        return "filled"
    if s == "partially_filled":
        return "partial"
    if s in ("canceled", "cancelled", "expired", "rejected", "suspended"):
        return "rejected"
    return "pending"   # new, accepted, pending_new, accepted_for_bidding, etc.


def _verify_fill(tc, order_id: str, timeout_sec: int = 30,
                 poll_interval: float = 2.0) -> dict:
    """Poll Alpaca for the order's terminal status.

    Returns a dict the caller can use to decide success / failure / rollback:
        status       — "filled" | "partial" | "rejected" | "pending"
        filled_qty   — int
        filled_avg_price — float | None
        raw_status   — Alpaca's raw status string (for logs)

    "pending" means we timed out before the order reached a terminal state.
    For limit orders that's expected when our limit is far from the touch;
    the caller should NOT treat pending as a hard failure, only as "unknown
    yet". Terminal-rejection caller can then trigger rollback safely.
    """
    import time as _time
    terminal = {"filled", "partial", "rejected"}
    deadline = _time.time() + timeout_sec
    last = {"status": "pending", "filled_qty": 0,
            "filled_avg_price": None, "raw_status": "unknown"}
    while _time.time() < deadline:
        try:
            order = tc.get_order_by_id(order_id)
            raw   = str(order.status)
            cat   = _normalize_alpaca_status(raw)
            try:
                fq = int(order.filled_qty or 0)
            except (TypeError, ValueError):
                fq = 0
            try:
                fap = float(order.filled_avg_price) if order.filled_avg_price else None
            except (TypeError, ValueError):
                fap = None
            last = {"status": cat, "filled_qty": fq,
                    "filled_avg_price": fap, "raw_status": raw.split(".")[-1]}
            if cat in terminal:
                return last
        except Exception as e:
            log.warning(f"  fill check error for {order_id}: {e}")
        _time.sleep(poll_interval)
    return last


def _live_option_mid(opt_client, occ: str) -> float | None:
    """Get live mid price for an OCC symbol via Alpaca data API.
    Falls back to yfinance if Alpaca unavailable."""
    # Try Alpaca first (most current)
    try:
        from alpaca.data.requests import OptionLatestQuoteRequest
        resp = opt_client.get_option_latest_quote(
            OptionLatestQuoteRequest(symbol_or_symbols=occ)
        )
        q = resp.get(occ)
        if q and q.bid_price is not None and q.ask_price is not None:
            bid = float(q.bid_price)
            ask = float(q.ask_price)
            if bid > 0 and ask > 0:
                return (bid + ask) / 2.0
    except Exception:
        pass
    # Fallback: yfinance (slightly delayed)
    try:
        import yfinance as yf
        # OCC format: {TICKER}{YYMMDD}{C|P}{8-digit-strike}
        # Extract underlying by stripping fixed suffix (15 chars from right)
        underlying = occ[: len(occ) - 15]
        date_part  = occ[-15:-9]          # YYMMDD
        expiry     = f"20{date_part[:2]}-{date_part[2:4]}-{date_part[4:6]}"
        opt_type   = "calls" if occ[-9] == "C" else "puts"
        chain      = getattr(yf.Ticker(underlying).option_chain(expiry), opt_type)
        row        = chain[chain["contractSymbol"] == occ]
        if not row.empty:
            return float((row.iloc[0]["bid"] + row.iloc[0]["ask"]) / 2.0)
    except Exception:
        pass
    return None


def execute_screener_option(opt_row: dict, dry_run: bool = False) -> dict:
    """
    Execute a screener options recommendation.

    opt_row keys (from screener_engine._build_options()):
      sym        — underlying ticker, e.g. "NVDA"
      structure  — "ATM Call" | "Debit Call Spread"
      expiry     — "2026-06-20"   (YYYY-MM-DD, from _nearest_expiry)
      opt_type   — "Call" | "Put"
      max_risk   — int, default 400  ($400 max loss)

    Execution flow:
      1. Fetch live option chain via yfinance for given expiry
      2. Find ATM strike (closest to spot)
      3. Apply KB §9 liquidity gates (OI, bid-ask)
      4. For "Debit Call Spread": find OTM short leg (KB §5)
      5. Get live Alpaca quote for limit price
      6. Submit BTO (+ STO for spread) via Alpaca trading API
      7. Return result dict

    Returns dict with keys:
      success         — bool
      message         — human-readable status
      long_occ        — OCC symbol of long leg (e.g. "NVDA260620C00120000")
      short_occ       — OCC symbol of short leg (spread only, else None)
      long_order_id   — Alpaca order ID string
      short_order_id  — Alpaca order ID string (spread only)
      actual_debit    — net debit paid per contract
      paper           — bool: True = paper account
      error           — str | None
    """
    sym       = opt_row["sym"].upper()
    expiry    = opt_row["expiry"]                      # YYYY-MM-DD
    structure = opt_row.get("structure", "ATM Call")
    opt_type  = opt_row.get("opt_type", "Call")        # "Call" | "Put"
    max_risk  = float(opt_row.get("max_risk", RISK_BUDGET))

    result = {
        "success": False, "message": "", "sym": sym,
        "long_occ": None, "short_occ": None,
        "long_order_id": None, "short_order_id": None,
        "actual_debit": 0.0, "paper": True, "error": None,
    }

    try:
        import yfinance as yf

        # ── 1. Spot price ────────────────────────────────────────────────────
        ticker = yf.Ticker(sym)
        hist   = ticker.history(period="1d")
        if hist.empty:
            raise ValueError(f"Cannot get spot price for {sym}")
        spot = float(hist["Close"].iloc[-1])
        log.info(f"[screener_executor] {sym} spot=${spot:.2f}  expiry={expiry}  "
                 f"structure={structure}  opt_type={opt_type}  dry_run={dry_run}")

        # ── 2. Option chain for chosen expiry ────────────────────────────────
        try:
            chain = ticker.option_chain(expiry)
        except Exception as e:
            raise ValueError(f"Cannot load option chain {sym}/{expiry}: {e}")

        opts = chain.calls if opt_type == "Call" else chain.puts
        opts = opts[opts["bid"] > 0].copy()
        if opts.empty:
            raise ValueError(f"No liquid {opt_type} contracts for {sym}/{expiry}")

        opts["mid"]  = (opts["bid"] + opts["ask"]) / 2.0
        opts["dist"] = (opts["strike"] - spot).abs()

        # ── 3. ATM long leg ──────────────────────────────────────────────────
        atm        = opts.sort_values("dist").iloc[0]
        atm_strike = float(atm["strike"])
        atm_mid    = float(atm["mid"])
        atm_bid    = float(atm["bid"])
        atm_ask    = float(atm["ask"])
        atm_oi     = int(atm.get("openInterest", 0) or 0)
        atm_occ    = str(atm["contractSymbol"])
        result["long_occ"] = atm_occ

        # ── KB §9 liquidity gates ────────────────────────────────────────────
        if atm_mid <= 0:
            raise ValueError(f"{sym}: ATM mid ≤ 0 (no valid quote)")
        if atm_oi < OPT_MIN_OI:
            raise ValueError(f"{sym}: ATM OI={atm_oi} < {OPT_MIN_OI} (KB §9 gate)")
        ba_pct = (atm_ask - atm_bid) / atm_mid if atm_mid > 0 else 1.0
        if ba_pct > OPT_MAX_BID_ASK_PCT:
            raise ValueError(f"{sym}: bid-ask spread {ba_pct*100:.1f}% > 5% (KB §9 gate)")

        log.info(f"  ATM: {atm_occ}  strike=${atm_strike:.2f}  mid=${atm_mid:.2f}  "
                 f"OI={atm_oi}  ba={ba_pct*100:.1f}%")

        # ── 4. Short leg for spread ──────────────────────────────────────────
        short_occ    = None
        short_strike = None
        short_mid    = 0.0
        net_debit    = atm_mid
        use_spread   = "Spread" in structure

        if use_spread:
            otm_opts = opts[opts["strike"] > atm_strike].sort_values("strike")
            spread_found = False
            for _, srow in otm_opts.head(8).iterrows():
                s_strike = float(srow["strike"])
                s_bid    = float(srow["bid"])
                s_mid    = float(srow["mid"])
                s_oi     = int(srow.get("openInterest", 0) or 0)
                if s_bid <= 0 or s_oi < OPT_MIN_OI:
                    continue
                width = s_strike - atm_strike
                nd    = atm_mid - s_bid   # KB §5: pay mid on long, receive bid on short
                if nd <= 0 or width <= 0:
                    continue
                ratio = nd / width
                if not (OPT_SPREAD_RATIO_LO <= ratio <= OPT_SPREAD_RATIO_HI):
                    continue
                # KB §25: spread width > 3× per-leg bid-ask
                if width < 3 * (atm_ask - atm_bid):
                    continue
                if nd * 100 > max_risk:
                    continue
                short_occ    = str(srow["contractSymbol"])
                short_strike = s_strike
                short_mid    = s_mid
                net_debit    = nd
                spread_found = True
                result["short_occ"] = short_occ
                log.info(f"  Short: {short_occ}  strike=${s_strike:.2f}  bid=${s_bid:.2f}  "
                         f"net_debit=${nd:.2f}  ratio={ratio:.0%}  width=${width:.2f}")
                break
            if not spread_found:
                # Fallback to naked if no spread leg passes all KB gates
                log.warning(f"  No valid spread leg found for {sym} — falling back to ATM naked")
                use_spread = False
                structure  = "ATM Call" if opt_type == "Call" else "ATM Put"
                net_debit  = atm_mid

        # ── Risk gate ────────────────────────────────────────────────────────
        if net_debit * 100 > max_risk:
            raise ValueError(f"{sym}: debit ${net_debit*100:.0f} > max_risk ${max_risk:.0f} (KB §4)")

        # ── 5. Dry run ───────────────────────────────────────────────────────
        if dry_run:
            msg = (f"[DRY RUN] BTO 1 {atm_occ}  "
                   f"strike=${atm_strike:.2f}  est=${net_debit:.2f}/contract  "
                   f"structure={structure}")
            if short_occ:
                msg += f"  /  STO 1 {short_occ}  strike=${short_strike:.2f}"
            result.update({
                "success": True, "message": msg, "paper": True,
                "long_order_id": "dry_run",
                "short_order_id": "dry_run" if short_occ else None,
                "actual_debit": round(net_debit, 2),
            })
            log.info(msg)
            return result

        # ── 6. Live execution via Alpaca ─────────────────────────────────────
        tc, oc, paper = _make_clients()
        result["paper"] = paper

        from alpaca.trading.requests import LimitOrderRequest
        from alpaca.trading.enums    import OrderSide, TimeInForce

        # Refresh long leg price from Alpaca (more current than yfinance EOD)
        live_long_mid = _live_option_mid(oc, atm_occ) or atm_mid
        long_limit    = round(live_long_mid + 0.05, 2)   # pay slightly above mid

        # ── BTO long leg ─────────────────────────────────────────────────────
        req = LimitOrderRequest(
            symbol=atm_occ, qty=1,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
            limit_price=long_limit,
        )
        order         = tc.submit_order(req)
        long_order_id = str(order.id)
        log.info(f"  BTO {atm_occ}  lmt=${long_limit:.2f}  id={long_order_id}  paper={paper}")
        result["long_order_id"] = long_order_id

        # ── Fill verification (BTO) ──────────────────────────────────────────
        # Catches the case where submit_order succeeded but Alpaca rejected
        # the order downstream (insufficient buying power, bad contract, etc.)
        long_fill = _verify_fill(tc, long_order_id)
        result["long_fill_status"]   = long_fill["status"]
        result["long_filled_qty"]    = long_fill["filled_qty"]
        result["long_fill_price"]    = long_fill["filled_avg_price"]
        log.info(f"  BTO fill: {long_fill['raw_status']}  qty={long_fill['filled_qty']}  "
                 f"avg=${long_fill['filled_avg_price'] or 0:.2f}")

        if long_fill["status"] == "rejected":
            # Order was rejected downstream — no position taken, no rollback
            # needed. Mark trade as failed and return.
            result["error"]   = f"BTO rejected by Alpaca: {long_fill['raw_status']}"
            result["message"] = f"❌ {sym} BTO rejected: {long_fill['raw_status']}"
            log.error(result["message"])
            return result

        # ── STO short leg (spread) ────────────────────────────────────────────
        short_order_id   = None
        actual_short_mid = 0.0

        if use_spread and short_occ:
            live_short_mid = _live_option_mid(oc, short_occ) or short_mid
            short_limit    = round(max(live_short_mid - 0.05,
                                       live_short_mid * 0.90, 0.01), 2)
            try:
                req = LimitOrderRequest(
                    symbol=short_occ, qty=1,
                    side=OrderSide.SELL,
                    time_in_force=TimeInForce.DAY,
                    limit_price=short_limit,
                )
                order          = tc.submit_order(req)
                short_order_id = str(order.id)
                actual_short_mid = live_short_mid
                log.info(f"  STO {short_occ}  lmt=${short_limit:.2f}  id={short_order_id}")

                # Verify STO didn't get rejected downstream. If it did, we
                # have an unhedged long — trigger the same rollback path as
                # a submit failure (cancel BTO if unfilled, flatten if filled).
                short_fill = _verify_fill(tc, short_order_id)
                result["short_fill_status"] = short_fill["status"]
                result["short_filled_qty"]  = short_fill["filled_qty"]
                result["short_fill_price"]  = short_fill["filled_avg_price"]
                log.info(f"  STO fill: {short_fill['raw_status']}  "
                         f"qty={short_fill['filled_qty']}")
                if short_fill["status"] == "rejected":
                    raise RuntimeError(
                        f"STO rejected downstream by Alpaca: {short_fill['raw_status']}"
                    )
            except Exception as e:
                # ── Naked-leg rollback ─────────────────────────────────────
                # The STO failed AFTER the BTO was submitted. To avoid being
                # left holding undefined-risk naked long premium, try to:
                #   1. Cancel the BTO if it hasn't filled yet
                #   2. If it has filled, place a market sell to flatten
                log.error(f"  STO {short_occ} failed: {e} — initiating rollback of long leg")
                rolled_back = False
                try:
                    # Check fill status of long leg
                    long_order = tc.get_order_by_id(long_order_id)
                    long_status = str(long_order.status).lower()
                    log.info(f"  rollback: long leg status = {long_status}")
                    if "filled" not in long_status and "canceled" not in long_status:
                        tc.cancel_order_by_id(long_order_id)
                        log.info(f"  rollback: cancelled unfilled BTO {long_order_id}")
                        rolled_back = True
                    elif "filled" in long_status:
                        # Already filled — flatten with a market sell
                        from alpaca.trading.requests import MarketOrderRequest
                        req_flat = MarketOrderRequest(
                            symbol=atm_occ, qty=1,
                            side=OrderSide.SELL,
                            time_in_force=TimeInForce.DAY,
                        )
                        flat_order = tc.submit_order(req_flat)
                        log.warning(f"  rollback: BTO already filled — submitted "
                                    f"market SELL {flat_order.id} to flatten naked long")
                        rolled_back = True
                except Exception as rb_err:
                    log.error(f"  rollback FAILED: {rb_err} — POSITION MAY BE NAKED LONG, "
                              f"manual intervention required for order {long_order_id}")
                result["error"] = (
                    f"STO failed: {e}. " +
                    ("Long leg rolled back successfully." if rolled_back
                     else "ROLLBACK FAILED — check Alpaca dashboard for naked long.")
                )
                raise   # re-raise so caller marks the trade as failed

        actual_debit = round(long_limit - actual_short_mid, 2)
        acct_type    = "📄 PAPER" if paper else "🔴 LIVE"
        spread_part  = f" / STO {short_occ}" if short_order_id else ""
        result.update({
            "success":        True,
            "short_order_id": short_order_id,
            "actual_debit":   actual_debit,
            "message": (
                f"✅ {acct_type}  BTO {atm_occ}@${long_limit:.2f}{spread_part}  "
                f"net_debit=${actual_debit:.2f}  structure={structure}  "
                f"strike=${atm_strike:.2f}  expiry={expiry}"
            ),
        })
        log.info(result["message"])
        return result

    except Exception as exc:
        result["error"]   = str(exc)
        result["message"] = f"❌ {sym} execution failed: {exc}"
        log.error(result["message"])
        return result
