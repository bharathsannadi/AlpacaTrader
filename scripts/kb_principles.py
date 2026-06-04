#!/usr/bin/env python3
"""
kb_principles.py — deterministic "does this trade match our knowledge base?" scorer.

Every codified KB rule a candidate satisfies adds to a 0-100% "KB match" score.
This is the SINGLE source for:
  1. the screener Confidence % column (what the user sees per row), and
  2. the pre-trade gate — only take trades that maximize KB-principle alignment.

Pure functions on the screener row dicts (+ a VIX value). No I/O, no LLM — that
keeps it fast (runs on every row, every refresh) and unit-testable. The LLM
bull/bear debate (debate.py) is a SEPARATE, heavier qualitative gate layered on top.

Each principle is (weight, matched_bool, label). Score = sum(matched weights) /
sum(all weights) * 100. The matched/failed labels are surfaced in the row tooltip
so the user can see WHY a candidate scored what it did.

KB references: §2 IV rules · §4 risk/Kelly · §5 strategy selection · §9 checklist ·
§12 cost-robust gate · §19 Connors · §25 Saliba DTE.
"""
from __future__ import annotations
from datetime import date, datetime

# Gate threshold: a candidate must score >= this to be auto-executable.
KB_MATCH_MIN = 60   # percent — "maximum principles" floor for taking a trade


def _dte_from_expiry(expiry: str) -> int | None:
    """Days-to-expiry from an ISO 'YYYY-MM-DD' string, or None if unparseable."""
    if not expiry:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            d = datetime.strptime(expiry[:10], fmt).date()
            return (d - date.today()).days
        except (ValueError, TypeError):
            continue
    return None


def _parse_ivr(ivr) -> float | None:
    """Pull a numeric IVR from '42', 42, 'IVR 42', '—', etc."""
    if ivr is None:
        return None
    if isinstance(ivr, (int, float)):
        return float(ivr)
    s = "".join(ch for ch in str(ivr) if (ch.isdigit() or ch == "."))
    try:
        return float(s) if s else None
    except ValueError:
        return None


def score_option_candidate(row: dict, vix: float | None = None) -> dict:
    """Score an options screener row against the KB. Returns
    {pct, matched:[...], failed:[...], n_matched, n_total}."""
    checks: list[tuple[float, bool, str]] = []

    dir_pct = float(row.get("dir_pct") or 0)
    pf      = float(row.get("pf") or 0)
    ivr     = _parse_ivr(row.get("ivr"))
    dte     = _dte_from_expiry(row.get("expiry", ""))
    structure = str(row.get("structure", "")).lower()
    is_spread = "spread" in structure
    max_risk  = float(row.get("max_risk") or 0)

    # §19/§12 — directional edge must clear the validated bar (core principle, weight 3)
    checks.append((3.0, dir_pct >= 53.0,
                   f"Directional edge {dir_pct:.0f}% ≥ 53% (§19 backtest)"))
    # §12 — cost-robust profit factor (weight 3)
    checks.append((3.0, pf >= 1.10,
                   f"Profit factor {pf:.2f} ≥ 1.10 cost-robust (§12)"))
    # §2/§5 — IVR-correct structure routing (weight 2)
    if ivr is None:
        checks.append((2.0, False, "IVR unknown — can't confirm structure routing (§2/§5)"))
    elif ivr < 30:
        checks.append((2.0, not is_spread,
                       f"IVR {ivr:.0f} < 30 → naked OK, structure={'spread✗' if is_spread else 'naked✓'} (§2)"))
    else:  # ivr >= 30
        checks.append((2.0, is_spread,
                       f"IVR {ivr:.0f} ≥ 30 → spread required, structure={'spread✓' if is_spread else 'naked✗'} (§5)"))
    # §25 Saliba — DTE preference 21-28 (weight 2; partial credit handled as match for 14-30)
    if dte is None:
        checks.append((2.0, False, "DTE unknown (§25 prefers 21-28)"))
    else:
        checks.append((2.0, 14 <= dte <= 30,
                       f"DTE {dte} in 14-30 window (§25 Saliba, optimal 21-28)"))
    # §4/½-Kelly — risk within the $400 budget (weight 2)
    checks.append((2.0, 0 < max_risk <= 400,
                   f"Max risk ${max_risk:.0f} ≤ $400 ½-Kelly budget (§4)"))
    # §appendix — VIX gate (weight 1)
    if vix is not None:
        checks.append((1.0, vix < 30,
                       f"VIX {vix:.1f} < 30 entry gate (§ appendix)"))
    # §9 liquidity — ONE-SIDED gate (rank-liquidity-gate TODO): a confirmed-illiquid
    # contract is disqualified (can't fill), but being liquid is the expected baseline
    # and must NOT *boost* a borderline score above the 60 gate. `row["liquidity"]` is
    # set by app._annotate_liquidity; ok False = illiquid, ok True / None = no change.
    liq = row.get("liquidity") or {}
    disqualified = liq.get("ok") is False
    if disqualified:
        checks.append((3.0, False,
                       f"§9 liquidity FAIL — {liq.get('reason', 'illiquid')} (won't fill)"))

    sc = _tally(checks)
    if disqualified:
        # Hard-floor below the gate so a confirmed-illiquid contract can NEVER rank
        # or show as a top BUY, regardless of its other merits (rank-liquidity-gate).
        sc["pct"] = min(sc["pct"], KB_MATCH_MIN - 1)
    return sc


def score_stock_candidate(row: dict, vix: float | None = None) -> dict:
    """Score a day-trading stock screener row against the KB."""
    checks: list[tuple[float, bool, str]] = []

    valid   = bool(row.get("valid"))
    pf      = float(row.get("bt_pf") or 0)
    rel_vol = float(row.get("rel_vol") or 0)
    rsi14   = float(row.get("rsi14") or 50)
    impulse = str(row.get("impulse", "Blue"))
    setup   = str(row.get("setup", ""))

    # validated setup (weight 3)
    checks.append((3.0, valid, f"Setup '{setup}' is a validated/backtested edge (§ screener)"))
    # PF (weight 3)
    checks.append((3.0, pf >= 1.10, f"Profit factor {pf:.2f} ≥ 1.10 (§12)"))
    # Aziz §31 — Stock in Play: rel vol ≥ 1.5× (weight 2)
    checks.append((2.0, rel_vol >= 1.5,
                   f"Rel-vol {rel_vol:.1f}× ≥ 1.5 'Stock in Play' (Aziz §)"))
    # Elder §47 — Impulse not red for momentum entries (weight 1; RSI Dip exempt)
    if setup == "RSI Dip":
        checks.append((1.0, True, "RSI Dip — Red impulse acceptable (PF 1.82, Elder §47)"))
    else:
        checks.append((1.0, impulse != "Red",
                       f"Elder Impulse {impulse} not Red for momentum (§47)"))
    # §3 — not overbought (weight 1)
    checks.append((1.0, rsi14 <= 70, f"RSI14 {rsi14:.0f} ≤ 70 not overbought (§3)"))
    if vix is not None:
        checks.append((1.0, vix < 30, f"VIX {vix:.1f} < 30 (§ appendix)"))

    return _tally(checks)


def score_signal(strat_pf: float | None, strength: float, asset_class: str,
                 vix: float | None = None, risk_on: bool = True,
                 has_vol_edge: bool = False, route: str = "stocks") -> dict:
    """KB-principles match for an autonomous-engine Signal (REQ-004).
    The validated strategy is the core principle; layered with regime, conviction,
    VIX, and instrument-appropriateness."""
    checks: list[tuple[float, bool, str]] = []
    pf = strat_pf or 0.0
    # §12 — the strategy itself is cost-robust validated (the strongest principle, weight 3)
    checks.append((3.0, pf >= 1.10, f"strategy PF {pf:.2f} ≥ 1.10 cost-robust (§12)"))
    # §8 Gunn — broad-market regime risk-on for longs (weight 2)
    checks.append((2.0, bool(risk_on), "broad-market risk-on SPY>200SMA (§8)"))
    # signal quality — conviction (weight 1)
    checks.append((1.0, strength >= 0.5, f"conviction {strength:.2f} ≥ 0.5 (§ signal quality)"))
    # §appendix — VIX gate (weight 1)
    if vix is not None:
        checks.append((1.0, vix < 30, f"VIX {vix:.1f} < 30 (§ appendix)"))
    # §5/§2 — instrument-appropriate: options need a volatility edge (weight 1)
    if route == "options":
        checks.append((1.0, has_vol_edge, "option route carries a volatility edge (§2/§5)"))
    else:
        checks.append((1.0, asset_class in ("stock", "etf"), "tradable equity/ETF (§14)"))
    return _tally(checks)


def calibrate(pct: int, ivr: float | None = None, win_prob: float | None = None) -> int:
    """Seam for turning the raw KB-match weighted-rule % into a CALIBRATED confidence
    (confidence-calibration TODO). Identity today — a no-op so ranking/gating is
    unchanged until a live IVR / historical win-probability feed is validated (today
    IVR is an HV proxy, screener_engine.py). When that lands, blend `pct` with the
    empirical win rate for the setup at this IVR here, in ONE place, so both the
    displayed % and the gate use the same calibrated number."""
    return int(pct)


def _tally(checks: list[tuple[float, bool, str]]) -> dict:
    total_w = sum(w for w, _, _ in checks) or 1.0
    got_w   = sum(w for w, ok, _ in checks if ok)
    matched = [lbl for _, ok, lbl in checks if ok]
    failed  = [lbl for _, ok, lbl in checks if not ok]
    return {
        "pct":       round(got_w / total_w * 100),
        "matched":   matched,
        "failed":    failed,
        "n_matched": len(matched),
        "n_total":   len(checks),
    }


if __name__ == "__main__":
    # quick smoke
    demo_opt = {"dir_pct": 66.4, "pf": 1.32, "ivr": "IVR 22",
                "expiry": "2026-06-26", "structure": "ATM Call", "max_risk": 400}
    print("Connors-like option:", score_option_candidate(demo_opt, vix=18))
    demo_stock = {"valid": True, "bt_pf": 1.88, "rel_vol": 2.1,
                  "rsi14": 58, "impulse": "Green", "setup": "Breakout"}
    print("Breakout stock:", score_stock_candidate(demo_stock, vix=18))
