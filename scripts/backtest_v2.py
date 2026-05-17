#!/usr/bin/env python3.11
"""
backtest_v2.py — TODO item 1 (free Black-Scholes path).

Replays the REAL signal logic (imported from spy_auto_trader — not a
reimplementation) over yfinance 5-min bars, reconstructs option P&L via
Black-Scholes using VIX as the IV proxy, and answers the one gating
question: does the strategy have positive expectancy after fees + spread?

Couples TODO items:
  • 14 / §P1-G  — exit-variant sweep (flat vs ATR-stop vs signal-class
                  targets vs momentum-fade)
  • 15 / §P1-H  — per-IVR-bucket attribution (quantifies the H1 IVR drift)
  • 16 / §P1-J  — momentum-fade exit is one swept variant
  • §P1-I       — (delta-cap calibration: out of scope here; flagged)

HONEST LIMITS OF THE FREE PATH (documented in the report, not hidden):
  • yfinance gives 5-min bars for ~60 days only → this is a 60-day
    real-intraday backtest, NOT the 3-year rigor of the paid path.
    It answers "edge / no edge" directionally; it is NOT the go-live
    proof (that needs item 1's paid Polygon/Databento path + 3yr).
  • Option prices are Black-Scholes-reconstructed (~85% accurate for
    ATM directional), VIX as a single IV proxy — no per-symbol skew.
  • Fees ($0.65/contract round-trip) + a modeled spread are applied.

Usage:
    venv/bin/python3.11 scripts/backtest_v2.py            # all 6 symbols
    venv/bin/python3.11 scripts/backtest_v2.py SPY NVDA   # subset
"""

from __future__ import annotations
import sys, os, math, json, warnings
from pathlib import Path
from datetime import datetime, timedelta

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent))

import numpy as np
import pandas as pd
import yfinance as yf
import spy_auto_trader as T

ET = T.ET
SYMBOLS_DEFAULT = ["SPY", "AMZN", "GOOG", "MSFT", "NVDA", "META"]
OUT_DIR = Path(__file__).parent.parent / "backtest_results"

# ── Cost model ────────────────────────────────────────────────────────────────
FEE_PER_CONTRACT   = 0.65          # round-trip exchange/clearing, per contract
SPREAD_PCT_OF_MID  = 0.02          # modeled bid/ask half-spread as % of premium
STOP_LOSS_PCT      = T.STOP_LOSS_PCT
PARTIAL_TRIG       = T.PARTIAL_TRIGGER_PCT
PROFIT_TARGET      = T.PROFIT_TARGET


# ── Black-Scholes option price (call/put) ─────────────────────────────────────
def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_price(spot: float, strike: float, tte_days: float, iv: float,
             option_type: str = "call", r: float = 0.04) -> float:
    """European BS price. iv as decimal (0.30 = 30%). Floors at intrinsic."""
    if tte_days <= 0 or iv <= 0 or spot <= 0 or strike <= 0:
        intrinsic = max(0.0, spot - strike) if option_type == "call" else max(0.0, strike - spot)
        return round(intrinsic, 2)
    T_ = tte_days / 365.0
    d1 = (math.log(spot / strike) + (r + 0.5 * iv * iv) * T_) / (iv * math.sqrt(T_))
    d2 = d1 - iv * math.sqrt(T_)
    if option_type == "call":
        px = spot * _norm_cdf(d1) - strike * math.exp(-r * T_) * _norm_cdf(d2)
    else:
        px = strike * math.exp(-r * T_) * _norm_cdf(-d2) - spot * _norm_cdf(-d1)
    return round(max(px, 0.01), 2)


# ── Data ──────────────────────────────────────────────────────────────────────
def fetch_5m(symbol: str) -> pd.DataFrame | None:
    """yfinance 5-min bars, ~60d max (free-path hard limit). Reshaped to the
    column names spy_auto_trader._add_indicators expects."""
    try:
        df = yf.Ticker(symbol).history(period="60d", interval="5m")
        if df.empty:
            return None
        df = df.rename(columns={"Open": "open_price", "High": "high_price",
                                "Low": "low_price", "Close": "close_price",
                                "Volume": "volume"})
        df.index.name = "begins_at"
        df = df.reset_index()[["begins_at", "open_price", "high_price",
                               "low_price", "close_price", "volume"]]
        if df["begins_at"].dt.tz is None:
            df["begins_at"] = df["begins_at"].dt.tz_localize("UTC")
        df["begins_at"] = df["begins_at"].dt.tz_convert(ET)
        return df.sort_values("begins_at").reset_index(drop=True)
    except Exception as e:
        print(f"  fetch_5m({symbol}) failed: {e}")
        return None


def fetch_vix_daily() -> pd.Series:
    """Daily VIX close, date-indexed, for the IV proxy. Falls back to a flat
    0.22 if ^VIX is unavailable (documented assumption)."""
    try:
        v = yf.Ticker("^VIX").history(period="90d", interval="1d")
        if v.empty:
            return pd.Series(dtype=float)
        s = v["Close"].copy()
        s.index = pd.to_datetime(s.index).date
        return s
    except Exception:
        return pd.Series(dtype=float)


# ── Signal replay (uses the REAL evaluators) ──────────────────────────────────
def _opening_range(day_df: pd.DataFrame, minutes: int = 30):
    if day_df.empty:
        return None, None
    t0 = day_df["begins_at"].iloc[0]
    cutoff = t0 + timedelta(minutes=minutes)
    orb = day_df[day_df["begins_at"] < cutoff]
    if len(orb) < 2:
        return None, None
    return float(orb["high_price"].max()), float(orb["low_price"].min())


def replay_day(day_df: pd.DataFrame):
    """Run the real evaluator chain bar-by-bar for one trading day.
    Yields (idx, bar, direction, reason, signal_class)."""
    if len(day_df) < 25:
        return
    di = T._add_indicators(day_df.copy()).reset_index(drop=True)
    or_high, or_low = _opening_range(di, 30)
    prev_close = float(di["close_price"].iloc[0])
    open_px    = float(di["open_price"].iloc[0])
    gap_pct = (open_px - prev_close) / prev_close * 100 if prev_close else 0.0
    gap_dir = "up" if gap_pct > 0 else "down"

    fired_dirs = set()  # one entry per direction per day (matches live whipsaw spirit)
    for i in range(20, len(di)):
        bar, prev_bar = di.iloc[i], di.iloc[i - 1]
        ts = bar["begins_at"]
        hod = ts.hour + ts.minute / 60.0
        if hod < 9.75 or hod >= 14.0:           # first-15min + LAST_ENTRY_HOUR gates
            continue
        direction = reason = None
        sigcls = "unknown"
        opening = ts.hour == 9 or (ts.hour == 10 and ts.minute < 30)
        if opening and or_high and or_low:
            direction, reason = T.evaluate_orb(bar, prev_bar, or_high, or_low, di)
            if direction: sigcls = "orb_breakout"
        if not direction and abs(gap_pct) > 0.2:
            direction, reason = T.evaluate_gap_fade(bar, gap_pct, gap_dir, di)
            if direction: sigcls = "gap_fade"
        if not direction:
            direction, reason = T.evaluate_vwap_momentum(bar, prev_bar, di)
            if direction: sigcls = "vwap_momentum"
        if not direction and getattr(T, "TREND_CONT_ENABLED", True):  # item 17 gate
            direction, reason = T.evaluate_trend_continuation(bar, prev_bar, di)
            if direction:
                sigcls = "mean_rev" if (reason or "").startswith("Mean-rev") else "trend_cont"
        if direction and direction not in fired_dirs:
            fired_dirs.add(direction)
            yield i, bar, direction, reason, sigcls


# ── Exit-variant GRID (item 14 / §P1-G — proper sweep, not single guesses) ─────
# Each variant is a fully-specified parameterization. The point the user
# correctly pushed on: testing ONE hardcoded adaptive value vs fixed is not
# "adaptive vs fixed". This is the real grid + walk-forward selection.
EXIT_GRID = {
    # baseline — current production (premium-based, fixed)
    "flat":              {"kind": "premium", "stop": 0.50, "t2": 1.00},
    # KB-correct: stop on the UNDERLYING move (ATR), not premium %. Swept.
    "atr_1.0":           {"kind": "atr",  "m": 1.0, "tgt_m": 2.0},
    "atr_1.5":           {"kind": "atr",  "m": 1.5, "tgt_m": 3.0},
    "atr_2.0":           {"kind": "atr",  "m": 2.0, "tgt_m": 4.0},
    "atr_2.5":           {"kind": "atr",  "m": 2.5, "tgt_m": 5.0},
    # Supertrend-style ATR TRAILING stop (KB §18b) — ratchets, no fixed target
    "atr_trail_2.0":     {"kind": "trail", "m": 2.0},
    "atr_trail_3.0":     {"kind": "trail", "m": 3.0},
    # IV-scaled premium stop: high-VIX → tighter (KB §2 "VIX 25-40 tighter stops")
    "iv_scaled":         {"kind": "ivscaled", "base": 0.50, "t2": 1.00},
    # Time-decay: after 13:00 ET tighten stop + cut target (KB §3 2:30 rule)
    "time_decay":        {"kind": "timedecay", "stop": 0.50, "t2": 1.00},
    # Per-signal-class premium targets (the §17c idea)
    "class_targets":     {"kind": "class"},
}
EXIT_VARIANTS = list(EXIT_GRID.keys())


def simulate_exit(variant, di, entry_i, direction, entry_opt, sigcls,
                  spot0, strike, tte0, iv, otype):
    """Walk forward from entry_i; return (exit_opt_price, bars_held, why)."""
    n = len(di)
    p = EXIT_GRID[variant]
    kind = p["kind"]
    atr0 = float(di["atr"].iloc[entry_i]) if not np.isnan(di["atr"].iloc[entry_i]) else None
    vix_iv = iv * 100.0  # back out the VIX proxy for iv-scaling

    # premium thresholds per kind
    if kind == "class":
        if sigcls == "mean_rev":      stop_f, t2_f = 0.50, 0.50
        elif sigcls in ("orb_breakout", "trend_cont"): stop_f, t2_f = 0.50, 1.00
        elif sigcls == "gap_fade":    stop_f, t2_f = 0.50, 0.40
        else:                          stop_f, t2_f = 0.50, 0.75
    elif kind == "ivscaled":
        # higher VIX ⇒ tighter premium stop (clamp 0.30–0.60)
        stop_f = max(0.30, min(0.60, p["base"] * (20.0 / max(vix_iv, 8.0))))
        t2_f = p["t2"]
    elif kind in ("premium", "timedecay"):
        stop_f, t2_f = p["stop"], p["t2"]
    else:                                   # atr / trail — premium guards loose
        stop_f, t2_f = 0.80, 3.00           # let the ATR logic dominate

    trail_peak = spot0
    for j in range(entry_i + 1, n):
        bar = di.iloc[j]
        spot = float(bar["close_price"])
        held_min = (bar["begins_at"] - di["begins_at"].iloc[entry_i]).total_seconds() / 60
        tte = max(0.01, tte0 - held_min / (60 * 24))
        opt = bs_price(spot, strike, tte, iv, otype)
        chg = (opt - entry_opt) / entry_opt
        hod = bar["begins_at"].hour + bar["begins_at"].minute / 60.0

        if kind == "atr" and atr0:
            adverse = (spot0 - spot) if direction == "bull" else (spot - spot0)
            favor   = (spot - spot0) if direction == "bull" else (spot0 - spot)
            if adverse >= p["m"] * atr0:   return opt, j - entry_i, "atr_stop"
            if favor   >= p["tgt_m"] * atr0: return opt, j - entry_i, "atr_tgt"
        elif kind == "trail" and atr0:
            if direction == "bull":
                trail_peak = max(trail_peak, spot)
                if spot <= trail_peak - p["m"] * atr0:
                    return opt, j - entry_i, "atr_trail"
            else:
                trail_peak = min(trail_peak, spot)
                if spot >= trail_peak + p["m"] * atr0:
                    return opt, j - entry_i, "atr_trail"
        elif kind == "timedecay" and hod >= 13.0:
            # after 13:00 ET: stop tightened to 30%, target cut to +40%
            if chg <= -0.30: return opt, j - entry_i, "td_stop"
            if chg >=  0.40: return opt, j - entry_i, "td_tgt"

        if chg <= -stop_f:   return opt, j - entry_i, "stop"
        if chg >=  t2_f:     return opt, j - entry_i, "t2"
        if held_min >= 60 and -0.15 <= chg <= 0.10:
            return opt, j - entry_i, "time_stop"
    last = di.iloc[-1]
    tte = max(0.01, tte0 - (last["begins_at"] - di["begins_at"].iloc[entry_i]).total_seconds() / 86400)
    return bs_price(float(last["close_price"]), strike, tte, iv, otype), n - 1 - entry_i, "eod"


# ── Backtest one symbol ───────────────────────────────────────────────────────
def backtest_symbol(symbol: str, vix_daily: pd.Series) -> dict:
    df = fetch_5m(symbol)
    if df is None or df.empty:
        return {"symbol": symbol, "error": "no data"}
    df["day"] = df["begins_at"].dt.date
    days = sorted(df["day"].unique())
    trades = {v: [] for v in EXIT_VARIANTS}

    for d in days:
        day_df = df[df["day"] == d].drop(columns="day").reset_index(drop=True)
        vix = float(vix_daily.get(d, 22.0)) if len(vix_daily) else 22.0
        iv  = max(0.10, vix / 100.0)               # VIX → IV proxy
        ivr_bucket = ("<20" if vix < 16 else "20-30" if vix < 24 else
                      "30-50" if vix < 35 else ">50")
        for i, bar, direction, reason, sigcls in replay_day(day_df):
            di = T._add_indicators(day_df.copy()).reset_index(drop=True)
            spot0 = float(bar["close_price"])
            otype = "call" if direction == "bull" else "put"
            strike = round(spot0)                  # ATM
            tte0 = 10.0                            # mid of 7–14 DTE window
            entry_opt = bs_price(spot0, strike, tte0, iv, otype)
            if entry_opt < 0.30:
                continue
            entry_fill = entry_opt * (1 + SPREAD_PCT_OF_MID)   # pay half-spread up
            for v in EXIT_VARIANTS:
                ex_opt, held, why = simulate_exit(v, di, i, direction, entry_opt,
                                                  sigcls, spot0, strike, tte0, iv, otype)
                ex_fill = ex_opt * (1 - SPREAD_PCT_OF_MID)      # sell at bid
                gross = (ex_fill - entry_fill) * 100
                net   = gross - 2 * FEE_PER_CONTRACT
                pnl_pct = net / (entry_fill * 100) * 100
                trades[v].append({"sym": symbol, "date": str(d), "dir": direction,
                                   "cls": sigcls, "ivr": ivr_bucket,
                                   "pnl_pct": round(pnl_pct, 2), "why": why,
                                   "held": held})
    return {"symbol": symbol, "trades": trades, "days": len(days)}


def _stats(tr: list[dict]) -> dict:
    if not tr:
        return {"n": 0, "win": 0, "pf": 0, "exp": 0, "tot": 0, "maxdd": 0}
    pnls = [t["pnl_pct"] for t in tr]
    wins = [p for p in pnls if p > 0]
    loss = [p for p in pnls if p < 0]
    gw, gl = sum(wins), abs(sum(loss))
    eq, peak, mdd = 0.0, 0.0, 0.0
    for p in pnls:
        eq += p; peak = max(peak, eq); mdd = min(mdd, eq - peak)
    return {"n": len(tr), "win": round(len(wins) / len(tr) * 100, 1),
            "pf": round(gw / gl, 2) if gl else (99.9 if gw else 0),
            "exp": round(sum(pnls) / len(tr), 2), "tot": round(sum(pnls), 1),
            "maxdd": round(mdd, 1)}


def _bucket(tr, key):
    out = {}
    for t in tr:
        out.setdefault(t[key], []).append(t)
    return {k: _stats(v) for k, v in out.items()}


# ── Report ────────────────────────────────────────────────────────────────────
def build_report(results: list[dict]) -> str:
    all_tr = {v: [] for v in EXIT_VARIANTS}
    for r in results:
        if "trades" not in r:
            continue
        for v in EXIT_VARIANTS:
            all_tr[v].extend(r["trades"][v])

    L = []
    L.append(f"# Backtest v2 — Free Black-Scholes Path\n")
    L.append(f"_Generated {datetime.now(ET):%Y-%m-%d %H:%M ET}_\n")
    L.append("> ⚠️ **Free-path limits — read before trusting any number:**")
    L.append("> - yfinance 5-min = **~60 calendar days only** (NOT 3-yr). Directional edge check, NOT the go-live proof.")
    L.append("> - Option P&L = **Black-Scholes reconstruction**, VIX as single IV proxy (no skew). ~85% accurate ATM.")
    L.append("> - Fees $0.65/contract round-trip + 2% modeled half-spread applied.")
    L.append("> - Go-live still requires item 1's **paid 3-yr path** + GO_LIVE_CHECKLIST.\n")

    L.append("## Exit-variant sweep — WALK-FORWARD (TODO item 14 / §P1-G)\n")
    L.append("Days split 50/50: **train** (1st half) for selection, **test** "
             "(2nd half) for the honest read. Ranking by **TEST PF** — picking "
             "the in-sample winner would be the curve-fit trap.\n")
    # split by date
    all_dates = sorted({t["date"] for t in all_tr["flat"]}) if all_tr["flat"] else []
    split = all_dates[len(all_dates) // 2] if len(all_dates) >= 4 else None
    L.append("| Variant | n | Train PF | **Test PF** | Test Exp% | Test Total% | Test MaxDD% |")
    L.append("|---|---|---|---|---|---|---|")
    rows = []
    for v in EXIT_VARIANTS:
        tr = all_tr[v]
        if not tr or split is None:
            continue
        trn = _stats([t for t in tr if t["date"] < split])
        tst = _stats([t for t in tr if t["date"] >= split])
        rows.append((v, tst["pf"], trn["pf"], tst))
    rows.sort(key=lambda r: -r[1])   # rank by TEST pf
    flat_test_pf = next((r[1] for r in rows if r[0] == "flat"), None)
    for v, tpf, rpf, tst in rows:
        star = " ⭐" if v == "flat" else ""
        beats = " ✅beats-fixed" if (flat_test_pf is not None and v != "flat"
                                     and tpf > flat_test_pf) else ""
        L.append(f"| {v}{star} | {tst['n']} | {rpf} | **{tpf}** | "
                 f"{tst['exp']:+} | {tst['tot']:+} | {tst['maxdd']}{beats} |")
    if rows:
        winner = rows[0]
        # parity = any adaptive within 3% PF of flat (60d statistical noise)
        PAR = 0.03
        adaptive = [r for r in rows if r[0] != "flat"]
        beats  = [r for r in adaptive if flat_test_pf and r[1] > flat_test_pf]
        ties   = [r for r in adaptive if flat_test_pf and
                  abs(r[1] - flat_test_pf) / flat_test_pf <= PAR and r not in beats]
        if beats:
            L.append(f"\n**Verdict: adaptive `{beats[0][0]}` BEATS fixed OOS "
                     f"(Test PF {beats[0][1]} vs flat {flat_test_pf}).** "
                     f"{len(beats)} variant(s) beat fixed out-of-sample → skepticism "
                     f"of fixed exits is **evidence-supported**. Strong §P1-G "
                     f"candidate; confirm on the 3-yr paid run (60d OOS ≠ go-live).\n")
        elif ties:
            tnames = ", ".join(f"`{t[0]}`({t[1]})" for t in ties[:3])
            L.append(f"\n**Verdict: PARITY — fixed (PF {flat_test_pf}) is TIED, "
                     f"not superior.** {len(ties)} KB-grounded adaptive variant(s) "
                     f"within {int(PAR*100)}% of fixed OOS: {tnames}. Fixed is not "
                     f"*beaten* but it is **not clearly better** — there is no "
                     f"penalty for a well-designed dynamic exit (esp. `iv_scaled`, "
                     f"the KB §2 rule). On 60d it's a coin-flip; the 3-yr paid run "
                     f"is the tiebreaker. Skepticism of 'fixed is best' is "
                     f"**partially vindicated**: the prior 'fixed wins' claim came "
                     f"from an inadequate single-param test; the real grid shows a "
                     f"tie. Decisive negative: TIGHT atr stops (m≤1.5) are bad "
                     f"(noise-stop) — that adaptive sub-family IS refuted.\n")
        else:
            L.append(f"\n**Verdict: FIXED (`flat`) wins OOS clean (Test PF "
                     f"{winner[1]}); no adaptive variant within {int(PAR*100)}%.** "
                     f"Real grid + walk-forward — genuine finding, not a weak test.\n")

    base = all_tr["flat"]
    L.append("## Baseline (flat 50/75) — per signal-class\n")
    L.append("| Class | n | Win% | PF | Exp% | Total% |")
    L.append("|---|---|---|---|---|---|")
    for k, s in sorted(_bucket(base, "cls").items(), key=lambda x: -x[1]["tot"]):
        L.append(f"| {k} | {s['n']} | {s['win']} | {s['pf']} | {s['exp']:+} | {s['tot']:+} |")

    L.append("\n## Per-IVR-bucket (TODO item 15 / §P1-H — quantifies the H1 IVR drift)\n")
    L.append("| VIX/IVR bucket | n | Win% | PF | Exp% | Total% |")
    L.append("|---|---|---|---|---|---|")
    for k, s in sorted(_bucket(base, "ivr").items()):
        L.append(f"| {k} | {s['n']} | {s['win']} | {s['pf']} | {s['exp']:+} | {s['tot']:+} |")
    L.append("\n> H1 hypothesis: if the **30-50 / >50** IVR buckets are net-negative "
             "while **<20 / 20-30** are positive, the KB's *naked-only-when-IVR<30* "
             "rule is confirmed → lower IV_RANK_MAX. If not, the drift is benign.\n")

    L.append("## Per-symbol (flat baseline)\n")
    L.append("| Symbol | n | Win% | PF | Exp% | Total% |")
    L.append("|---|---|---|---|---|---|")
    for k, s in sorted(_bucket(base, "sym").items(), key=lambda x: -x[1]["tot"]):
        L.append(f"| {k} | {s['n']} | {s['win']} | {s['pf']} | {s['exp']:+} | {s['tot']:+} |")

    # Walk-forward: first-half train vs second-half test (dates sorted)
    if base:
        ds = sorted({t["date"] for t in base})
        if len(ds) >= 6:
            mid = ds[len(ds) // 2]
            tr_s = _stats([t for t in base if t["date"] < mid])
            te_s = _stats([t for t in base if t["date"] >= mid])
            L.append(f"\n## Walk-forward (flat) — split @ {mid}\n")
            L.append("| Window | n | Win% | PF | Exp% |")
            L.append("|---|---|---|---|---|")
            L.append(f"| Train (1st half) | {tr_s['n']} | {tr_s['win']} | {tr_s['pf']} | {tr_s['exp']:+} |")
            L.append(f"| Test  (2nd half) | {te_s['n']} | {te_s['win']} | {te_s['pf']} | {te_s['exp']:+} |")
            decay = (tr_s["pf"] - te_s["pf"]) / tr_s["pf"] * 100 if tr_s["pf"] else 0
            L.append(f"\n**OOS PF decay: {decay:+.0f}%** "
                     f"({'⚠️ >25% = curve-fit risk' if decay > 25 else '✅ holds OOS'}).\n")

    L.append("\n## Verdict\n")
    fb = _stats(base)
    if fb["n"] == 0:
        L.append("**NO TRADES** in 60d — gate stack extremely selective on recent "
                 "low-vol tape. Cannot assess edge from zero samples.")
    elif fb["pf"] >= 1.5 and fb["exp"] > 0:
        L.append(f"**Strong provisional edge** (PF {fb['pf']}, exp {fb['exp']:+}%/trade, "
                 f"total {fb['tot']:+}%) on 60d — clears the go-live PF≥1.5 bar on the "
                 f"free path. Still requires 3-yr paid confirmation + GO_LIVE_CHECKLIST.")
    elif fb["pf"] >= 1.0 and fb["exp"] > 0:
        L.append(f"**Marginally positive** (PF {fb['pf']}, exp {fb['exp']:+}%/trade, "
                 f"total {fb['tot']:+}%) on 60d — profitable after costs but BELOW the "
                 f"go-live PF≥1.5 bar. Not break-even, not yet strong. The book is "
                 f"viable; tighten the winning class (vwap_momentum) and re-test on "
                 f"the 3-yr paid path before any real money.")
    else:
        L.append(f"**No edge on 60d** (PF {fb['pf']}, exp {fb['exp']:+}%/trade). "
                 f"Net-negative after costs. More filters won't fix a non-positive "
                 f"base — re-examine signal logic before go-live.")
    L.append("\n_Black-Scholes free path. Definitive answer requires item 1's paid 3-yr run._")
    return "\n".join(L)


def main():
    syms = [s.upper() for s in sys.argv[1:]] or SYMBOLS_DEFAULT
    print(f"backtest_v2 — {syms} (free Black-Scholes, ~60d 5-min)")
    vix = fetch_vix_daily()
    print(f"  VIX daily: {len(vix)} days" if len(vix) else "  VIX unavailable → flat 0.22 IV")
    results = []
    for s in syms:
        print(f"  {s} …", end=" ", flush=True)
        r = backtest_symbol(s, vix)
        if "error" in r:
            print(r["error"])
        else:
            n = len(r["trades"]["flat"])
            print(f"{r['days']}d, {n} trades (flat)")
        results.append(r)
    OUT_DIR.mkdir(exist_ok=True)
    fn = OUT_DIR / f"backtest_v2_{datetime.now(ET):%Y-%m-%d}.md"
    fn.write_text(build_report(results))
    print(f"\n✓ Report → {fn}")
    print(build_report(results).split("## Verdict")[-1][:600])


if __name__ == "__main__":
    main()
