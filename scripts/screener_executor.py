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
import time as _time
from pathlib import Path

log = logging.getLogger("screener_executor")


# ── Defensive direct-to-file trail ───────────────────────────────────────────
# Python logging in this app is fragile — propagation through eventlet is
# inconsistent, and several recent execute failures left no on-disk evidence.
# This helper writes UNCONDITIONALLY to a flat file so we can always tail it
# during incident triage.  `tail -f logs/screener_executor.trail`
_TRAIL_PATH = Path(__file__).parent.parent / "logs" / "screener_executor.trail"


def _trail(msg: str) -> None:
    """Write a single timestamped line to the executor trail file.
    Never raises — log handler failures must not break order placement."""
    try:
        _TRAIL_PATH.parent.mkdir(parents=True, exist_ok=True)
        ts = _time.strftime("%Y-%m-%d %H:%M:%S")
        with open(_TRAIL_PATH, "a") as fh:
            fh.write(f"{ts}  {msg}\n")
            fh.flush()
    except Exception:
        pass

# ── KB-sourced constants (mirror daily_trader.py) ─────────────────────────────
OPT_MIN_OI           = 200     # KB §9: minimum open interest for liquidity
OPT_MAX_BID_ASK_PCT  = 0.05   # KB §9: bid-ask < 5% of mid (live quote gate)
OPT_TIGHT_BA_PCT     = 0.02   # §9 (#28): a ≤2% LIVE spread proves a liquid market
                              # even when yfinance reports stale/low OI (e.g. SPY
                              # weeklies read OI 144 with a 0.4% spread). The live
                              # bid-ask is the reliable signal; it overrides the OI
                              # floor. Wide spreads (HOOD 19.9%) still hard-fail.
OPT_SPREAD_RATIO_LO  = 0.25   # KB §5: spread debit ≥ 25% of width
OPT_SPREAD_RATIO_HI  = 0.45   # KB §5: spread debit ≤ 45% of width
RISK_BUDGET          = 400.0  # KB §4: $400 max loss per trade

# ── Operator 2026-06-02: RELAXED-FILL mode ────────────────────────────────────
# Fill everything (incl. illiquid) at market, no $400 cap. Every time a KB rule is
# relaxed to let an order through, log a 'KB-RELAXED' note + append to an audit
# file so it can be analysed later. (Paper; dry-run on by default.)
OPT_RELAX_LIQUIDITY  = True    # §9 liquidity gate advisory, not blocking
OPT_MARKET_ORDERS    = True    # place option legs at market so they fill
OPT_ENFORCE_MAX_RISK = False   # drop the $400 per-trade max-loss SOFT cap
OPT_HARD_MAX_USD     = 600.0   # operator 2026-06-02: HARD ceiling — max $600 per
                               # option trade, ALWAYS enforced even in relaxed mode
                               # (stops a garbage quote, e.g. the $11k MU glitch).
OPT_HARD_MAX_USD_ETF = 1500.0  # ETFs get a higher ceiling (operator) — liquid index
                               # options (SPY/QQQ ATM) legitimately cost > $600.
try:
    from universe import ETFS_TRADE as _ETFS_T, ETFS_HEDGE as _ETFS_H
    _ETF_SET = set(_ETFS_T) | set(_ETFS_H)
except Exception:
    _ETF_SET = set()
OPT_TAKE_PROFIT_PCT  = 0.20    # sell an option position at +20% (net debit)
OPT_STOP_LOSS_PCT    = 0.20    # sell an option position at -20% (net debit)
OPT_MAX_OPEN         = 3       # max concurrent option positions (by underlying)
_KB_RELAXED_LOG = os.path.expanduser("~/.spy_trader/kb_relaxed.jsonl")


def _log_kb_relaxed(sym: str, rule: str, detail: str) -> None:
    """Audit a KB rule that was relaxed to fill an order (operator override) — to
    the logger (also surfaces in the UI log) AND a structured file for analysis."""
    log.warning(f"⚠️ KB-RELAXED [{rule}] {sym}: {detail} — order allowed anyway "
                f"(operator relaxed-fill override)")
    try:
        import json as _j, datetime as _dt
        os.makedirs(os.path.dirname(_KB_RELAXED_LOG), exist_ok=True)
        with open(_KB_RELAXED_LOG, "a") as fh:
            fh.write(_j.dumps({"ts": _dt.datetime.now().isoformat(), "sym": sym,
                               "rule": rule, "detail": detail}) + "\n")
    except Exception:
        pass


# ── Credential helpers ────────────────────────────────────────────────────────
def _load_env() -> tuple[str, str, bool]:
    """Backwards-compat shim — resolves credentials via the shared loader.

    The previous implementation reimplemented .env parsing and only honoured
    ALPACA_API_KEY/ALPACA_API_SECRET. The shared `credentials.load_alpaca_creds`
    now handles the full fallback chain (canonical → legacy AUTO_* → oldest
    ALPACA_SECRET_KEY) — see scripts/credentials.py.

    Returns (key, secret, paper) for callers that still want the tuple shape.
    """
    # Make sure .env values are in os.environ even if python-dotenv wasn't
    # already imported (callers may invoke screener_executor outside the
    # Flask app context — e.g. CLI usage or tests).
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

    from credentials import load_alpaca_creds
    creds = load_alpaca_creds()
    return creds.key, creds.secret, creds.paper


def _make_clients():
    """Returns (TradingClient, OptionHistoricalDataClient, is_paper)."""
    from alpaca.trading.client import TradingClient
    from alpaca.data.historical.option import OptionHistoricalDataClient
    key, secret, paper = _load_env()
    if not key or not secret:
        raise RuntimeError(
            "Alpaca credentials not set in .env "
            "(checked ALPACA_API_KEY, ALPACA_AUTO_KEY, ALPACA_API_SECRET, "
            "ALPACA_AUTO_SECRET, ALPACA_SECRET_KEY)"
        )
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


def liquidity_check(sym: str, expiry: str, opt_type: str = "Call") -> dict:
    """KB §9 liquidity pre-check for the screener ranking (#22): fetch the ATM
    contract and verify OI + bid-ask WITHOUT placing an order, so an illiquid
    option never shows as a Top Pick / ✅ BUY the executor would later reject.

    Returns {ok, reason, atm_oi, ba_pct}. `ok` is True (liquid), False (confirmed
    illiquid → demote the row), or None (couldn't check → leave the row as-is)."""
    from datetime import datetime as _dt
    sym = sym.upper()
    try:
        import yfinance as yf
        ticker = yf.Ticker(sym)
        hist = ticker.history(period="1d")
        if hist.empty:
            return {"ok": None, "reason": "no spot price"}
        spot = float(hist["Close"].iloc[-1])
        try:
            chain = ticker.option_chain(expiry)
        except Exception:
            avail = list(ticker.options or ())
            if not avail:
                return {"ok": None, "reason": "no option chain"}
            try:
                tgt = _dt.strptime(expiry, "%Y-%m-%d").date()
                expiry = min(avail, key=lambda d: abs((_dt.strptime(d, "%Y-%m-%d").date() - tgt).days))
            except Exception:
                expiry = avail[0]
            chain = ticker.option_chain(expiry)
        opts = (chain.calls if opt_type == "Call" else chain.puts)
        opts = opts[opts["bid"] > 0].copy()
        if opts.empty:
            return {"ok": False, "reason": "no contracts with a live bid"}
        opts["mid"]  = (opts["bid"] + opts["ask"]) / 2.0
        opts["dist"] = (opts["strike"] - spot).abs()
        atm = opts.sort_values("dist").iloc[0]
        mid = float(atm["mid"]); bid = float(atm["bid"]); ask = float(atm["ask"])
        oi  = int(atm.get("openInterest", 0) or 0)
        ba  = (ask - bid) / mid if mid > 0 else 1.0
        if mid <= 0:
            return {"ok": False, "reason": "no valid ATM quote", "atm_oi": oi, "ba_pct": ba}
        # bid-ask is the hard, reliable gate; OI is satisfied by a real count OR a
        # very tight live spread (which proves liquidity when yfinance OI is stale).
        wide   = ba > OPT_MAX_BID_ASK_PCT
        thinOI = oi < OPT_MIN_OI and ba > OPT_TIGHT_BA_PCT
        if wide or thinOI:
            why = (f"bid-ask {ba*100:.1f}% > {OPT_MAX_BID_ASK_PCT*100:.0f}%" if wide
                   else f"ATM OI {oi} < {OPT_MIN_OI} and spread {ba*100:.1f}% not tight")
            if OPT_RELAX_LIQUIDITY:        # operator: fill anyway — keep it tradable, just audit
                _log_kb_relaxed(sym, "§9 liquidity (rank)", why)
                return {"ok": True, "reason": f"§9 relaxed: {why}", "atm_oi": oi, "ba_pct": ba,
                        "relaxed": True}
            return {"ok": False, "reason": why, "atm_oi": oi, "ba_pct": ba}
        return {"ok": True, "reason": "liquid", "atm_oi": oi, "ba_pct": ba}
    except Exception as e:
        return {"ok": None, "reason": f"liquidity check failed: {e}"}


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

    _trail(f"ENTRY  sym={sym}  structure={structure}  expiry={expiry}  "
           f"opt_type={opt_type}  max_risk=${max_risk}  dry_run={dry_run}")

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
        # The screener computes expiry from a Friday-cadence heuristic. Many
        # symbols (e.g. COHR) list Thursday weeklies instead — requesting the
        # Friday throws "Expiration X cannot be found". Fall back to the
        # nearest available expiry that's still ≥ DTE_MIN to preserve the
        # KB §1 21-28 DTE window intent.
        try:
            chain = ticker.option_chain(expiry)
        except Exception as e:
            # Try to recover by picking the nearest valid expiry.
            try:
                from datetime import datetime as _dt
                target_dt = _dt.strptime(expiry, "%Y-%m-%d").date()
                available = list(ticker.options or ())
                _trail(f"FALLBACK  sym={sym}  requested={expiry}  available={available}")
                if not available:
                    raise ValueError(f"No option chain available for {sym}")

                # Prefer the closest expiry with DTE >= 21 (KB §1 window).
                # If none qualify, take the closest one overall.
                today = _dt.now().date()
                MIN_DTE = 21
                candidates = []
                for d_str in available:
                    try:
                        d = _dt.strptime(d_str, "%Y-%m-%d").date()
                    except ValueError:
                        continue
                    dte = (d - today).days
                    delta = abs((d - target_dt).days)
                    candidates.append((dte, delta, d_str, d))

                if not candidates:
                    raise ValueError(f"Cannot parse any expiry from {available}")

                # Pick: among DTE >= 21, the one closest to the requested date.
                # Otherwise the one with the largest DTE under 21.
                qualifying = [c for c in candidates if c[0] >= MIN_DTE]
                if qualifying:
                    qualifying.sort(key=lambda c: c[1])    # closest-to-requested wins
                    chosen_dte, _, chosen_str, chosen_d = qualifying[0]
                else:
                    candidates.sort(key=lambda c: -c[0])   # max DTE under 21
                    chosen_dte, _, chosen_str, chosen_d = candidates[0]

                log.warning(
                    f"[screener_executor] {sym}: requested expiry {expiry} not "
                    f"available — falling back to {chosen_str} (DTE={chosen_dte})"
                )
                _trail(f"FALLBACK_PICK  sym={sym}  was={expiry}  now={chosen_str}  dte={chosen_dte}")
                expiry = chosen_str   # update for the rest of this execution
                chain  = ticker.option_chain(expiry)
            except Exception as inner:
                raise ValueError(f"Cannot load option chain {sym}/{expiry}: {inner}")

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
        # bid-ask is the hard, reliable gate; OI is satisfied by a real count OR a
        # very tight live spread (proves liquidity when yfinance OI is stale, #28).
        if atm_mid <= 0:
            raise ValueError(f"{sym}: KB §9 Liquidity — ATM mid ≤ 0 (no valid quote)")
        ba_pct = (atm_ask - atm_bid) / atm_mid if atm_mid > 0 else 1.0
        _wide   = ba_pct > OPT_MAX_BID_ASK_PCT
        _thinOI = atm_oi < OPT_MIN_OI and ba_pct > OPT_TIGHT_BA_PCT
        if _wide or _thinOI:
            _why = (f"bid-ask spread {ba_pct*100:.1f}% > {OPT_MAX_BID_ASK_PCT*100:.0f}% max"
                    if _wide else f"ATM OI {atm_oi} < {OPT_MIN_OI} and spread {ba_pct*100:.1f}% not tight")
            if OPT_RELAX_LIQUIDITY:        # operator relaxed-fill: allow it, audit it
                _log_kb_relaxed(sym, "§9 liquidity (exec)",
                                f"{_why} — filling at market, expect to pay the spread")
            else:
                raise ValueError(f"{sym}: KB §9 Liquidity — {_why} — illiquid, would not fill")

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
        # HARD sanity ceiling first — ALWAYS blocks, even in relaxed mode, so a
        # single mispriced/garbage contract can't blow a huge position (the MU
        # $11k glitch). This is NOT relaxable.
        _ceiling = OPT_HARD_MAX_USD_ETF if sym.upper() in _ETF_SET else OPT_HARD_MAX_USD
        if net_debit * 100 > _ceiling:
            raise ValueError(f"{sym}: HARD ceiling — debit ${net_debit*100:.0f} "
                             f"> ${_ceiling:.0f} (sanity guard; likely a bad quote)")
        if net_debit * 100 > max_risk:
            if OPT_ENFORCE_MAX_RISK:
                raise ValueError(f"{sym}: KB §4 Risk — debit ${net_debit*100:.0f} "
                                 f"> ${max_risk:.0f} max-risk (½-Kelly per-trade budget)")
            _log_kb_relaxed(sym, "§4 max-risk",
                            f"debit ${net_debit*100:.0f} > ${max_risk:.0f} soft cap (relaxed)")

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

        from alpaca.trading.requests import LimitOrderRequest, MarketOrderRequest
        from alpaca.trading.enums    import OrderSide, TimeInForce

        # Refresh long leg price from Alpaca (more current than yfinance EOD)
        live_long_mid = _live_option_mid(oc, atm_occ) or atm_mid
        long_limit    = round(live_long_mid + 0.05, 2)   # pay slightly above mid

        # ── BTO long leg ─────────────────────────────────────────────────────
        # operator relaxed-fill: market order so it fills even on a wide spread
        # (you pay the ask). Otherwise a limit slightly above mid.
        if OPT_MARKET_ORDERS:
            req = MarketOrderRequest(symbol=atm_occ, qty=1, side=OrderSide.BUY,
                                     time_in_force=TimeInForce.DAY)
        else:
            req = LimitOrderRequest(symbol=atm_occ, qty=1, side=OrderSide.BUY,
                                    time_in_force=TimeInForce.DAY, limit_price=long_limit)
        order         = tc.submit_order(req)
        long_order_id = str(order.id)
        log.info(f"  BTO {atm_occ}  {'MKT' if OPT_MARKET_ORDERS else f'lmt=${long_limit:.2f}'}  "
                 f"id={long_order_id}  paper={paper}")
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
                if OPT_MARKET_ORDERS:
                    req = MarketOrderRequest(symbol=short_occ, qty=1, side=OrderSide.SELL,
                                             time_in_force=TimeInForce.DAY)
                else:
                    req = LimitOrderRequest(symbol=short_occ, qty=1, side=OrderSide.SELL,
                                            time_in_force=TimeInForce.DAY, limit_price=short_limit)
                order          = tc.submit_order(req)
                short_order_id = str(order.id)
                actual_short_mid = live_short_mid
                log.info(f"  STO {short_occ}  {'MKT' if OPT_MARKET_ORDERS else f'lmt=${short_limit:.2f}'}  id={short_order_id}")

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
        _trail(f"OK    sym={sym}  long={atm_occ}  short={short_occ}  "
               f"debit=${actual_debit}  paper={paper}")
        return result

    except Exception as exc:
        result["error"]   = str(exc)
        result["message"] = f"❌ {sym} execution failed: {exc}"
        log.error(result["message"])
        # Defensive trail — never lose an error to a broken log handler
        import traceback as _tb
        _trail(f"FAIL  sym={sym}  exc={type(exc).__name__}: {exc}")
        _trail(f"  traceback: {_tb.format_exc().replace(chr(10), ' | ')}")
        return result
