#!/usr/bin/env python3
"""
strategy.py — strategy registry (Phase 0).

A Strategy is a plug-in that turns market data into Signals. Each strategy is
INDEPENDENTLY validated (its own cost-robust ≥3bp/5bp walk-forward) before it is
registered as live-eligible (REQ-202). The registry is the single place that
knows which strategies exist and whether each is validated / enabled.

This is the skeleton for the "portfolio of strategies behind a shared risk brain"
architecture. Phase 0 = registry + metadata; signal generation wiring comes later.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, Optional

from trade_signal import Signal


@dataclass
class StrategySpec:
    name: str
    kb_ref: str                  # KB section(s) the strategy is sourced from
    family: str                  # "mean_reversion" | "trend" | "momentum"
    validated: bool = False      # passed its own cost-robust walk-forward?
    enabled: bool = False        # live-eligible (paper)? requires validated=True
    test_pf_3bp: Optional[float] = None
    test_pf_5bp: Optional[float] = None
    notes: str = ""
    generate: Optional[Callable[[str], Optional[Signal]]] = None  # wired later

    def is_live_eligible(self) -> bool:
        return self.validated and self.enabled


class StrategyRegistry:
    def __init__(self) -> None:
        self._strats: dict[str, StrategySpec] = {}

    def register(self, spec: StrategySpec) -> None:
        if spec.enabled and not spec.validated:
            raise ValueError(f"{spec.name}: cannot enable an unvalidated strategy (REQ-202)")
        self._strats[spec.name] = spec

    def get(self, name: str) -> Optional[StrategySpec]:
        return self._strats.get(name)

    def all(self) -> list[StrategySpec]:
        return list(self._strats.values())

    def live(self) -> list[StrategySpec]:
        return [s for s in self._strats.values() if s.is_live_eligible()]


# ── Default registry — the strategies validated 2026-05-31 (multi-strategy backtest)
# Cost-robust gate: Test PF ≥ 1.10 at BOTH 3 & 5 bp OOS. All four PASSED.
# `enabled` stays False until each completes its own paper incubation (REQ-203).
def default_registry() -> StrategyRegistry:
    r = StrategyRegistry()
    r.register(StrategySpec("connors_rsi2", "§19", "mean_reversion",
                            validated=True, enabled=False,
                            test_pf_3bp=1.35, test_pf_5bp=1.32,
                            notes="live in paper incubation since 2026-05-20"))
    r.register(StrategySpec("bollinger_reversion", "§1", "mean_reversion",
                            validated=True, enabled=False,
                            test_pf_3bp=1.40, test_pf_5bp=1.37))
    r.register(StrategySpec("trend_pullback", "§8/§14", "trend",
                            validated=True, enabled=False,
                            test_pf_3bp=2.11, test_pf_5bp=2.08,
                            notes="best diversifier vs connors (corr 0.31)"))
    r.register(StrategySpec("breakout_52w", "§15", "momentum",
                            validated=True, enabled=False,
                            test_pf_3bp=1.96, test_pf_5bp=1.94))
    return r


if __name__ == "__main__":
    reg = default_registry()
    print("Registered strategies:")
    for s in reg.all():
        print(f"  {s.name:22} {s.family:14} {s.kb_ref:8} "
              f"PF {s.test_pf_3bp}/{s.test_pf_5bp}  "
              f"validated={s.validated} enabled={s.enabled}")
    print(f"Live-eligible: {[s.name for s in reg.live()]}")
