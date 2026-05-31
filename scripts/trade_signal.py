#!/usr/bin/env python3
"""
signal.py — the unit that flows through the dual-instrument pipeline (Phase 0).

A Signal is what a Strategy emits: a directional opinion on a symbol with the
context the router + risk brain need to decide HOW to express it (shares vs
option), HOW BIG, and WHEN to exit. Pure data — no behavior.

Pipeline: Strategy.generate() -> Signal -> KB/debate gate -> router -> risk_brain
          -> executor -> exit_engine
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Signal:
    symbol: str
    direction: str               # "bull" | "bear"
    strategy: str                # e.g. "connors_rsi2", "trend_pullback"
    strength: float = 0.0        # 0..1 conviction (e.g. KB-match %, or backtest dir%)
    price: float = 0.0           # underlying price at signal
    atr: float = 0.0             # ATR14 for volatility-scaled stops/sizing
    # context for routing (KB §2/§5) — optional, filled when known
    ivr: Optional[float] = None          # implied-vol rank
    iv_hv_ratio: Optional[float] = None  # IV/HV (cheap < 0.8, rich > 1.5)
    has_vol_edge: bool = False           # True only if a volatility edge is present
    asset_class: str = "stock"           # "stock" | "etf"
    kb_match: Optional[int] = None       # KB-principles match % (REQ-004)
    kb_principles: dict = field(default_factory=dict)
    ts: str = field(default_factory=lambda: datetime.now().isoformat())

    @property
    def is_long(self) -> bool:
        return self.direction == "bull"

    def __post_init__(self):
        self.symbol = self.symbol.upper()
        if self.direction not in ("bull", "bear"):
            raise ValueError(f"direction must be bull|bear, got {self.direction!r}")
