"""Centralised Alpaca credential resolution.

Single source of truth for "what API key and secret do we use to talk to
Alpaca?". Reads from environment variables (populated by python-dotenv at app
boot) with a fallback chain so older `.env` files keep working:

    1. ALPACA_API_KEY      / ALPACA_API_SECRET     / ALPACA_PAPER       ← canonical
    2. ALPACA_AUTO_KEY     / ALPACA_AUTO_SECRET    / ALPACA_AUTO_PAPER  ← auto-login (legacy)
    3. ALPACA_SECRET_KEY                                                ← oldest name for secret

For new `.env` files, only set the canonical names — see `.env.example`. The
fallbacks exist so existing installs don't break on upgrade.

Usage:
    from credentials import load_alpaca_creds
    creds = load_alpaca_creds()
    if not creds.is_complete:
        log.warning("No Alpaca credentials in .env — auto-login skipped")
        return
    trader.init_clients(creds.key, creds.secret, paper=creds.paper)

This module has zero non-stdlib imports so it can be tested fast and
imported from anywhere without dragging in Alpaca SDK / yfinance / etc.
"""
from __future__ import annotations

import os
from typing import NamedTuple


class AlpacaCreds(NamedTuple):
    key:    str
    secret: str
    paper:  bool

    @property
    def is_complete(self) -> bool:
        """True when both key and secret are non-empty."""
        return bool(self.key) and bool(self.secret)

    @property
    def key_prefix(self) -> str:
        """First 6 chars of the key — safe to log."""
        return self.key[:6] if self.key else ""


# ── Environment variable names, in fallback priority order ────────────────────
_KEY_VARS    = ("ALPACA_API_KEY",    "ALPACA_AUTO_KEY")
_SECRET_VARS = ("ALPACA_API_SECRET", "ALPACA_AUTO_SECRET", "ALPACA_SECRET_KEY")
_PAPER_VARS  = ("ALPACA_PAPER",      "ALPACA_AUTO_PAPER")

# Values that count as "live trading" when present in *_PAPER vars
_LIVE_VALUES = frozenset({"false", "0", "no", "live", "off"})


def _first_set(*var_names: str) -> str:
    """Return the value of the first env var in `var_names` that is set
    and non-empty (after stripping). Returns '' if none are populated."""
    for name in var_names:
        val = os.environ.get(name, "").strip()
        if val:
            return val
    return ""


def load_alpaca_creds() -> AlpacaCreds:
    """Resolve Alpaca credentials from environment with fallback chain.

    Always returns an AlpacaCreds — `is_complete` tells you whether the
    caller can actually use it. We never raise on missing credentials so
    the server can boot in advisory-only mode.
    """
    key    = _first_set(*_KEY_VARS)
    secret = _first_set(*_SECRET_VARS)
    paper_raw = _first_set(*_PAPER_VARS).lower() or "true"
    paper  = paper_raw not in _LIVE_VALUES
    return AlpacaCreds(key=key, secret=secret, paper=paper)
