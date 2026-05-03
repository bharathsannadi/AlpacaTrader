"""
Security utilities for SPY Auto Trader Dashboard
- Secret key management
- Login attempt tracking with lockout
- Input validation & sanitization
"""

import os
import re
import secrets
import logging
from datetime import datetime, timedelta, timezone
from collections import defaultdict

log = logging.getLogger(__name__)

# ── Secret key ────────────────────────────────────────────────────────────────

def get_or_create_secret_key(env_path=".env"):
    """
    Load SECRET_KEY from .env; generate and persist a new one if absent.
    Never hardcode secrets in source code.
    """
    from dotenv import load_dotenv, set_key
    load_dotenv(env_path)
    key = os.getenv("SECRET_KEY")
    if not key or len(key) < 32:
        key = secrets.token_hex(32)
        set_key(env_path, "SECRET_KEY", key)
        log.info("Generated new SECRET_KEY and saved to .env")
    return key


# ── Login lockout ─────────────────────────────────────────────────────────────

class LoginTracker:
    """
    Track failed login attempts per IP.
    Lock out an IP for LOCKOUT_MINUTES after MAX_FAILURES failures.
    """
    MAX_FAILURES    = 5
    LOCKOUT_MINUTES = 15
    WINDOW_MINUTES  = 10      # sliding window for counting failures

    def __init__(self):
        self._failures  = defaultdict(list)   # ip → [datetime, ...]
        self._locked    = {}                  # ip → unlock_datetime

    def is_locked(self, ip: str) -> tuple[bool, int]:
        """Return (locked, seconds_remaining)."""
        until = self._locked.get(ip)
        if until:
            remaining = (until - datetime.now(timezone.utc)).total_seconds()
            if remaining > 0:
                return True, int(remaining)
            del self._locked[ip]
            self._failures.pop(ip, None)
        return False, 0

    def record_failure(self, ip: str) -> bool:
        now    = datetime.now(timezone.utc)
        cutoff = now - timedelta(minutes=self.WINDOW_MINUTES)
        # Prune old entries
        self._failures[ip] = [t for t in self._failures[ip] if t > cutoff]
        self._failures[ip].append(now)
        count = len(self._failures[ip])
        if count >= self.MAX_FAILURES:
            unlock = now + timedelta(minutes=self.LOCKOUT_MINUTES)
            self._locked[ip] = unlock
            log.warning(f"SECURITY: IP {ip} locked out for {self.LOCKOUT_MINUTES} min after {count} failed logins")
            return True
        log.warning(f"SECURITY: Failed login from {ip} ({count}/{self.MAX_FAILURES})")
        return False

    def record_success(self, ip: str):
        self._failures.pop(ip, None)
        self._locked.pop(ip, None)


# ── Input validation ──────────────────────────────────────────────────────────

_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")

def validate_email(value: str) -> str:
    """Return sanitized email or raise ValueError."""
    value = (value or "").strip().lower()[:254]
    if not _EMAIL_RE.match(value):
        raise ValueError("Invalid email address.")
    return value

def validate_password(value: str) -> str:
    """Basic password presence check. Never log passwords."""
    value = value or ""
    if len(value) < 6 or len(value) > 256:
        raise ValueError("Password must be 6–256 characters.")
    return value

def validate_api_key(value: str) -> str:
    """Validate Alpaca API key format (alphanumeric, ~16-32 chars)."""
    value = (value or "").strip()
    if not re.match(r"^[A-Za-z0-9]{12,64}$", value):
        raise ValueError("API key looks invalid (expected 12–64 alphanumeric chars).")
    return value

def validate_api_secret(value: str) -> str:
    """Validate Alpaca API secret format (alphanumeric + some punctuation, ~32-64 chars)."""
    value = (value or "").strip()
    if not (20 <= len(value) <= 80):
        raise ValueError("API secret must be 20–80 characters.")
    if not re.match(r"^[A-Za-z0-9/+=_\-]+$", value):
        raise ValueError("API secret contains invalid characters.")
    return value

def validate_risk_pct(value) -> float:
    """Risk must be 0.1%–5.0%."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise ValueError("Risk must be a number.")
    if not (0.1 <= v <= 5.0):
        raise ValueError("Risk must be between 0.1% and 5.0%.")
    return round(v, 2)

def validate_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    raise ValueError("Expected a boolean.")

def validate_vix_max(value) -> int:
    try:
        v = int(value)
    except (TypeError, ValueError):
        raise ValueError("VIX max must be a number.")
    if not (10 <= v <= 100):
        raise ValueError("VIX max must be between 10 and 100.")
    return v

def validate_stop_loss(value) -> int:
    """Returns integer percent (e.g. 50 for 50%)."""
    try:
        v = int(value)
    except (TypeError, ValueError):
        raise ValueError("Stop loss must be a number.")
    if not (10 <= v <= 90):
        raise ValueError("Stop loss must be between 10% and 90%.")
    return v

def validate_profit_target(value) -> int:
    """Returns integer percent."""
    try:
        v = int(value)
    except (TypeError, ValueError):
        raise ValueError("Profit target must be a number.")
    if not (10 <= v <= 500):
        raise ValueError("Profit target must be between 10% and 500%.")
    return v

def validate_dte(value) -> int:
    try:
        v = int(value)
    except (TypeError, ValueError):
        raise ValueError("DTE must be a number.")
    if not (0 <= v <= 60):
        raise ValueError("DTE must be between 0 and 60.")
    return v


_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")

def validate_time(value: str) -> tuple[int, int]:
    """Parse a HH:MM string between 09:30 and 16:00 (US market hours)."""
    value = (value or "").strip()
    m = _TIME_RE.match(value)
    if not m:
        raise ValueError("Invalid time format. Use HH:MM (24-hour).")
    h, mm = int(m.group(1)), int(m.group(2))
    total = h * 60 + mm
    if total < 9 * 60 + 30 or total > 16 * 60:
        raise ValueError("Time must be between 09:30 and 16:00 ET.")
    return h, mm


# ── Security headers ──────────────────────────────────────────────────────────

SECURITY_HEADERS = {
    "X-Frame-Options":           "DENY",
    "X-Content-Type-Options":    "nosniff",
    "X-XSS-Protection":          "1; mode=block",
    "Referrer-Policy":           "strict-origin-when-cross-origin",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains; preload",
    "Permissions-Policy":        "geolocation=(), microphone=(), camera=()",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.socket.io; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "connect-src 'self' wss: ws:; "
        "img-src 'self' data:; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self';"
    ),
}
