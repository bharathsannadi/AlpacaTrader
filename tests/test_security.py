"""Tests for security.py validators and the LoginTracker lockout logic.

These functions guard every WebSocket login + every parameter mutation.
A regression here is a security regression — keep this file fast and thorough.
"""
import pytest
from datetime import datetime, timedelta, timezone

from security import (
    validate_api_key, validate_api_secret,
    validate_risk_pct, validate_bool,
    validate_vix_max, validate_stop_loss, validate_profit_target,
    validate_dte, validate_time,
    LoginTracker,
)


# ── validate_api_key ──────────────────────────────────────────────────────────

class TestValidateApiKey:
    def test_accepts_typical_paper_key(self):
        assert validate_api_key("PKREKT364YNIDCGRVQIS7VCMXN") == "PKREKT364YNIDCGRVQIS7VCMXN"

    def test_strips_whitespace(self):
        assert validate_api_key("  PKABCDEFGHIJKLM  ") == "PKABCDEFGHIJKLM"

    def test_rejects_too_short(self):
        with pytest.raises(ValueError, match="invalid"):
            validate_api_key("PK123")          # 5 chars, min is 12

    def test_rejects_too_long(self):
        with pytest.raises(ValueError, match="invalid"):
            validate_api_key("A" * 65)         # 65 chars, max is 64

    def test_rejects_special_chars(self):
        with pytest.raises(ValueError, match="invalid"):
            validate_api_key("PK!@#$%^&*()_+=")

    def test_rejects_empty(self):
        with pytest.raises(ValueError):
            validate_api_key("")

    def test_rejects_none(self):
        with pytest.raises(ValueError):
            validate_api_key(None)


# ── validate_api_secret ───────────────────────────────────────────────────────

class TestValidateApiSecret:
    def test_accepts_typical_secret(self):
        s = "EDvU9QU6WLkz3wdxxEAdjoPtZsvaiLGCTkJ19vhfoki6"
        assert validate_api_secret(s) == s

    def test_accepts_base64_url_safe_chars(self):
        s = "abc/def+ghi=jkl_mno-pqrstuvwxyz0123456"
        assert validate_api_secret(s) == s

    def test_rejects_too_short(self):
        with pytest.raises(ValueError, match="20.80"):
            validate_api_secret("short")

    def test_rejects_too_long(self):
        with pytest.raises(ValueError, match="20.80"):
            validate_api_secret("A" * 81)

    def test_rejects_invalid_chars(self):
        with pytest.raises(ValueError, match="invalid characters"):
            validate_api_secret("a" * 20 + "!@#")


# ── validate_risk_pct ─────────────────────────────────────────────────────────

class TestValidateRiskPct:
    @pytest.mark.parametrize("inp,expected", [
        (0.5, 0.5), (1.0, 1.0), (5.0, 5.0), ("2.5", 2.5),
        (0.1, 0.1),   # boundary
        (5.0, 5.0),   # boundary
    ])
    def test_accepts_valid(self, inp, expected):
        assert validate_risk_pct(inp) == expected

    @pytest.mark.parametrize("inp", [0, 0.09, 5.01, 10, -1, "abc", None])
    def test_rejects_invalid(self, inp):
        with pytest.raises(ValueError):
            validate_risk_pct(inp)


# ── validate_vix_max / stop_loss / profit_target / dte ────────────────────────

class TestRangeValidators:
    def test_vix_max_bounds(self):
        assert validate_vix_max(30) == 30
        assert validate_vix_max("50") == 50
        for bad in [9, 101, "x"]:
            with pytest.raises(ValueError):
                validate_vix_max(bad)

    def test_stop_loss_bounds(self):
        assert validate_stop_loss(50) == 50
        for bad in [9, 91, "x"]:
            with pytest.raises(ValueError):
                validate_stop_loss(bad)

    def test_profit_target_bounds(self):
        assert validate_profit_target(100) == 100
        for bad in [9, 501, "x"]:
            with pytest.raises(ValueError):
                validate_profit_target(bad)

    def test_dte_bounds(self):
        assert validate_dte(7) == 7
        assert validate_dte(0) == 0
        for bad in [-1, 61, "x"]:
            with pytest.raises(ValueError):
                validate_dte(bad)


# ── validate_bool ─────────────────────────────────────────────────────────────

class TestValidateBool:
    def test_accepts_true(self):
        assert validate_bool(True) is True

    def test_accepts_false(self):
        assert validate_bool(False) is False

    def test_rejects_truthy_non_bool(self):
        # Strict: only actual booleans (otherwise a stray 1 from JS could
        # bypass type checks downstream)
        for bad in [1, 0, "true", "false", None, "yes"]:
            with pytest.raises(ValueError):
                validate_bool(bad)


# ── validate_time ─────────────────────────────────────────────────────────────

class TestValidateTime:
    def test_accepts_market_hours(self):
        assert validate_time("09:30") == (9, 30)
        assert validate_time("15:45") == (15, 45)
        assert validate_time("16:00") == (16, 0)

    def test_rejects_before_open(self):
        with pytest.raises(ValueError):
            validate_time("09:29")

    def test_rejects_after_close(self):
        with pytest.raises(ValueError):
            validate_time("16:01")

    def test_rejects_bad_format(self):
        for bad in ["9:30", "09-30", "0930", "noon", ""]:
            with pytest.raises(ValueError):
                validate_time(bad)


# ── LoginTracker ──────────────────────────────────────────────────────────────

class TestLoginTracker:
    def test_unlocked_by_default(self):
        t = LoginTracker()
        locked, remaining = t.is_locked("1.2.3.4")
        assert locked is False
        assert remaining == 0

    def test_lockout_after_max_failures(self):
        t = LoginTracker()
        ip = "1.2.3.4"
        # 4 failures — not locked yet
        for _ in range(t.MAX_FAILURES - 1):
            t.record_failure(ip)
        assert t.is_locked(ip)[0] is False
        # 5th failure — locked
        t.record_failure(ip)
        locked, remaining = t.is_locked(ip)
        assert locked is True
        assert remaining > 0

    def test_success_clears_failures(self):
        t = LoginTracker()
        ip = "1.2.3.4"
        for _ in range(t.MAX_FAILURES - 1):
            t.record_failure(ip)
        t.record_success(ip)
        # Next failure should start the counter over
        t.record_failure(ip)
        assert t.is_locked(ip)[0] is False

    def test_lockout_per_ip(self):
        """Lockout of one IP must not lock out a different IP."""
        t = LoginTracker()
        for _ in range(t.MAX_FAILURES):
            t.record_failure("1.2.3.4")
        assert t.is_locked("1.2.3.4")[0] is True
        assert t.is_locked("5.6.7.8")[0] is False

    def test_window_pruning(self):
        """Failures outside the sliding window should not count."""
        t = LoginTracker()
        ip = "1.2.3.4"
        # Inject 4 old failures (outside window)
        old = datetime.now(timezone.utc) - timedelta(minutes=t.WINDOW_MINUTES + 1)
        t._failures[ip] = [old] * (t.MAX_FAILURES - 1)
        # One new failure should NOT trip the lockout (old ones get pruned)
        t.record_failure(ip)
        assert t.is_locked(ip)[0] is False
