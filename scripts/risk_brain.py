#!/usr/bin/env python3
"""
risk_brain.py — shared money-management brain for the dual-instrument system (Phase 1).

ONE place that enforces every capital/risk rule across both routes. Pure logic +
in-memory state (+ optional JSON persistence) — no broker I/O, fully unit-testable.
The router/executors CONSULT it; it never places orders itself.

Implements:
  REQ-602  capital sleeves: $95,000 stock route, remaining equity = options route
  REQ-605  options caps: ≤ $500 risk/trade, ≤ $1,500 risk/rolling-week
  REQ-606  stock sizing: fixed 10 shares per buy signal
  REQ-604.2 tier priority: ETF → large-cap → small-cap when capacity-limited

Discipline: this is enforcement *logic*. It is NOT wired into live execution yet
(Phase 2/5b). Default-safe: refuses on any ambiguity.
"""
from __future__ import annotations
import json
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

# ── Constants (operator requirements) ─────────────────────────────────────────
STOCK_SLEEVE_USD       = 95_000.0   # REQ-602
OPT_PER_TRADE_MAX_USD  = 500.0      # REQ-605
OPT_WEEK_MAX_USD       = 1_500.0    # REQ-605
STOCK_SHARES_FIXED     = 10         # REQ-606
WEEK_MODE              = "rolling5" # REQ-605.3: "rolling5" (5 trading days) | "calendar" (Mon-Fri)
SIX_PCT_MONTH_CAP      = 0.06       # Elder 6% Rule: month losses + open risk ≤ 6% equity (REQ-611)

STATE_FILE = Path.home() / ".spy_trader" / "risk_brain_state.json"

# Tier order for prioritization (lower = higher priority) — REQ-604.2
TIER_ETF, TIER_LARGE, TIER_SMALL = 0, 1, 2


@dataclass
class RouteState:
    name: str                       # "stocks" | "options"
    sleeve_usd: float               # capital allocated to this route
    deployed_usd: float = 0.0       # capital currently in open positions
    open_positions: int = 0

    def free_usd(self) -> float:
        return max(0.0, self.sleeve_usd - self.deployed_usd)


class RiskBrain:
    def __init__(self, total_equity: float,
                 stock_sleeve: float = STOCK_SLEEVE_USD,
                 week_mode: str = WEEK_MODE):
        self.total_equity = float(total_equity)
        self.week_mode = week_mode
        # REQ-602: $95K stocks, the rest options (never negative)
        s = min(stock_sleeve, self.total_equity)
        self.stocks = RouteState("stocks", sleeve_usd=s)
        self.options = RouteState("options", sleeve_usd=max(0.0, self.total_equity - s))
        # REQ-605: rolling weekly options risk — list of (date, risk_usd)
        self._opt_risk_log: list[tuple[str, float]] = []

    # ── capital sleeves (REQ-602) ─────────────────────────────────────────────
    def options_sleeve_usd(self) -> float:
        return self.options.sleeve_usd

    # ── stock sizing (REQ-606) ────────────────────────────────────────────────
    def stock_shares(self, price: float) -> int:
        """Fixed 10 shares per signal (REQ-606), but 0 if it won't fit the sleeve."""
        if price <= 0:
            return 0
        cost = STOCK_SHARES_FIXED * price
        return STOCK_SHARES_FIXED if cost <= self.stocks.free_usd() else 0

    # ── weekly options risk window (REQ-605) ──────────────────────────────────
    def _week_start(self, today: Optional[date] = None) -> date:
        today = today or date.today()
        if self.week_mode == "calendar":
            return today - timedelta(days=today.weekday())   # Monday
        return today - timedelta(days=4)                     # rolling 5 calendar days

    def week_options_risk(self, today: Optional[date] = None) -> float:
        start = self._week_start(today)
        return round(sum(r for d, r in self._opt_risk_log
                         if date.fromisoformat(d) >= start), 2)

    # ── entry admission (the gate the router calls) ───────────────────────────
    def can_enter(self, route: str, est_cost_usd: float,
                  est_risk_usd: float, today: Optional[date] = None) -> tuple[bool, str]:
        """Return (allowed, reason). est_cost = capital tied up; est_risk = max $ loss."""
        if route == "stocks":
            if est_cost_usd > self.stocks.free_usd():
                return False, (f"stock sleeve full: cost ${est_cost_usd:.0f} > "
                               f"free ${self.stocks.free_usd():.0f} (REQ-602)")
            return True, "ok"
        if route == "options":
            if est_risk_usd > OPT_PER_TRADE_MAX_USD:
                return False, (f"options per-trade risk ${est_risk_usd:.0f} > "
                               f"${OPT_PER_TRADE_MAX_USD:.0f} cap (REQ-605)")
            wk = self.week_options_risk(today)
            if wk + est_risk_usd > OPT_WEEK_MAX_USD:
                return False, (f"options weekly risk ${wk:.0f}+${est_risk_usd:.0f} > "
                               f"${OPT_WEEK_MAX_USD:.0f} cap (REQ-605)")
            if est_cost_usd > self.options.free_usd():
                return False, (f"options sleeve full: cost ${est_cost_usd:.0f} > "
                               f"free ${self.options.free_usd():.0f} (REQ-602)")
            return True, "ok"
        return False, f"unknown route {route!r}"

    # ── state mutation ────────────────────────────────────────────────────────
    def register_entry(self, route: str, cost_usd: float,
                       risk_usd: float = 0.0, today: Optional[date] = None) -> None:
        rs = self.stocks if route == "stocks" else self.options
        rs.deployed_usd += cost_usd
        rs.open_positions += 1
        if route == "options":
            d = (today or date.today()).isoformat()
            self._opt_risk_log.append((d, risk_usd))

    def register_exit(self, route: str, cost_usd: float) -> None:
        rs = self.stocks if route == "stocks" else self.options
        rs.deployed_usd = max(0.0, rs.deployed_usd - cost_usd)
        rs.open_positions = max(0, rs.open_positions - 1)

    # ── Elder 6% Rule (REQ-611, book-dig 2026-05-31) ──────────────────────────
    def six_percent_ok(self, new_risk_usd: float, open_risk_usd: float,
                       month_loss_usd: float,
                       month_start_equity: float | None = None) -> tuple[bool, str]:
        """Elder's 6% Rule: refuse a new entry if this month's realized losses PLUS
        open risk on all positions PLUS this trade's risk would exceed 6% of
        month-start equity. Note: a position stopped at breakeven has ZERO open
        risk (caller excludes it), so protecting profits (REQ-608) frees budget."""
        base = month_start_equity or self.total_equity
        cap = base * SIX_PCT_MONTH_CAP
        total = abs(month_loss_usd) + max(0.0, open_risk_usd) + max(0.0, new_risk_usd)
        if total > cap:
            return False, (f"6% rule: month-loss ${abs(month_loss_usd):.0f} + open-risk "
                           f"${open_risk_usd:.0f} + trade ${new_risk_usd:.0f} = ${total:.0f} "
                           f"> 6% cap ${cap:.0f} (Elder)")
        return True, "ok"

    # ── tier prioritization (REQ-604.2) ───────────────────────────────────────
    @staticmethod
    def tier_of(symbol: str, etf_set: set[str],
                large_cap_set: Optional[set[str]] = None,
                dollar_volume: Optional[float] = None,
                dv_large_threshold: float = 5e8) -> int:
        sym = symbol.upper()
        if sym in etf_set:
            return TIER_ETF
        if large_cap_set and sym in large_cap_set:
            return TIER_LARGE
        if dollar_volume is not None:
            return TIER_LARGE if dollar_volume >= dv_large_threshold else TIER_SMALL
        return TIER_SMALL

    @classmethod
    def prioritize(cls, signals: list, etf_set: set[str],
                   large_cap_set: Optional[set[str]] = None) -> list:
        """Order signals ETF → large → small, then by strength desc (REQ-604.2)."""
        def key(sig):
            tier = cls.tier_of(getattr(sig, "symbol", sig), etf_set, large_cap_set,
                               getattr(sig, "dollar_volume", None))
            return (tier, -getattr(sig, "strength", 0.0))
        return sorted(signals, key=key)

    # ── snapshot / persistence ────────────────────────────────────────────────
    def snapshot(self) -> dict:
        return {
            "total_equity": self.total_equity,
            "stocks": asdict(self.stocks),
            "options": asdict(self.options),
            "options_week_risk": self.week_options_risk(),
            "options_per_trade_cap": OPT_PER_TRADE_MAX_USD,
            "options_week_cap": OPT_WEEK_MAX_USD,
        }

    def save(self, path: Path = STATE_FILE) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({
            "total_equity": self.total_equity,
            "week_mode": self.week_mode,
            "stocks": asdict(self.stocks),
            "options": asdict(self.options),
            "opt_risk_log": self._opt_risk_log,
        }, indent=2))
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path = STATE_FILE) -> Optional["RiskBrain"]:
        if not path.exists():
            return None
        d = json.loads(path.read_text())
        rb = cls(d["total_equity"], week_mode=d.get("week_mode", WEEK_MODE))
        rb.stocks = RouteState(**d["stocks"])
        rb.options = RouteState(**d["options"])
        rb._opt_risk_log = [tuple(x) for x in d.get("opt_risk_log", [])]
        return rb


if __name__ == "__main__":
    rb = RiskBrain(total_equity=107_846)
    print("Sleeves: stocks $%.0f | options $%.0f" % (rb.stocks.sleeve_usd, rb.options.sleeve_usd))
    print("10 shares of $200 stock fits?", rb.stock_shares(200))
    print("can_enter options $300 risk?", rb.can_enter("options", 300, 300))
    print("can_enter options $600 risk (>cap)?", rb.can_enter("options", 600, 600))
    rb.register_entry("options", 400, 400); rb.register_entry("options", 400, 400)
    print("after 2x$400 options risk, can add $400 (week cap $1500)?",
          rb.can_enter("options", 400, 400))
