"""Tests for the centralised credential loader (#13).

The whole point of this module is the fallback chain — make sure that
chain works in every direction so legacy installs keep booting and new
installs don't accidentally fall through to a stale var.
"""
import pytest

from credentials import load_alpaca_creds, AlpacaCreds


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def clean_env(monkeypatch):
    """Strip every Alpaca-related env var so each test starts from zero."""
    for var in (
        "ALPACA_API_KEY", "ALPACA_AUTO_KEY",
        "ALPACA_API_SECRET", "ALPACA_AUTO_SECRET", "ALPACA_SECRET_KEY",
        "ALPACA_PAPER", "ALPACA_AUTO_PAPER",
    ):
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


# ── AlpacaCreds dataclass ─────────────────────────────────────────────────────

class TestAlpacaCreds:
    def test_is_complete_true_when_both_set(self):
        c = AlpacaCreds(key="PKabc123", secret="secretval", paper=True)
        assert c.is_complete is True

    def test_is_complete_false_when_key_missing(self):
        c = AlpacaCreds(key="", secret="secretval", paper=True)
        assert c.is_complete is False

    def test_is_complete_false_when_secret_missing(self):
        c = AlpacaCreds(key="PKabc123", secret="", paper=True)
        assert c.is_complete is False

    def test_is_complete_false_when_both_missing(self):
        c = AlpacaCreds(key="", secret="", paper=True)
        assert c.is_complete is False

    def test_key_prefix_is_first_six(self):
        c = AlpacaCreds(key="PKREKT364YNIDCGRVQIS7VCMXN", secret="x", paper=True)
        assert c.key_prefix == "PKREKT"

    def test_key_prefix_empty_when_no_key(self):
        c = AlpacaCreds(key="", secret="x", paper=True)
        assert c.key_prefix == ""


# ── Canonical names take priority ─────────────────────────────────────────────

class TestCanonicalNames:
    def test_canonical_only(self, clean_env):
        clean_env.setenv("ALPACA_API_KEY",    "PKcanonical")
        clean_env.setenv("ALPACA_API_SECRET", "secretcanonical")
        clean_env.setenv("ALPACA_PAPER",      "true")
        creds = load_alpaca_creds()
        assert creds.key    == "PKcanonical"
        assert creds.secret == "secretcanonical"
        assert creds.paper  is True

    def test_canonical_wins_over_auto(self, clean_env):
        """If both canonical and AUTO_* are set, canonical wins."""
        clean_env.setenv("ALPACA_API_KEY",    "PKcanonical")
        clean_env.setenv("ALPACA_AUTO_KEY",   "PKauto")
        clean_env.setenv("ALPACA_API_SECRET", "secretcanonical")
        clean_env.setenv("ALPACA_AUTO_SECRET","secretauto")
        creds = load_alpaca_creds()
        assert creds.key    == "PKcanonical"
        assert creds.secret == "secretcanonical"

    def test_canonical_secret_wins_over_legacy(self, clean_env):
        """ALPACA_API_SECRET wins over ALPACA_SECRET_KEY (oldest name)."""
        clean_env.setenv("ALPACA_API_KEY",    "PKfoo")
        clean_env.setenv("ALPACA_API_SECRET", "new_secret")
        clean_env.setenv("ALPACA_SECRET_KEY", "old_secret")
        creds = load_alpaca_creds()
        assert creds.secret == "new_secret"


# ── Fallback chain ────────────────────────────────────────────────────────────

class TestFallbackChain:
    def test_falls_back_to_auto_key(self, clean_env):
        clean_env.setenv("ALPACA_AUTO_KEY",    "PKauto")
        clean_env.setenv("ALPACA_AUTO_SECRET", "secretauto")
        creds = load_alpaca_creds()
        assert creds.key    == "PKauto"
        assert creds.secret == "secretauto"

    def test_falls_back_to_oldest_secret_name(self, clean_env):
        """ALPACA_SECRET_KEY is the oldest name — should still work."""
        clean_env.setenv("ALPACA_API_KEY",    "PKfoo")
        clean_env.setenv("ALPACA_SECRET_KEY", "old_secret")
        creds = load_alpaca_creds()
        assert creds.secret == "old_secret"

    def test_falls_back_to_auto_paper(self, clean_env):
        clean_env.setenv("ALPACA_API_KEY",    "PKfoo")
        clean_env.setenv("ALPACA_API_SECRET", "x" * 30)
        clean_env.setenv("ALPACA_AUTO_PAPER", "false")
        creds = load_alpaca_creds()
        assert creds.paper is False


# ── Paper flag parsing ────────────────────────────────────────────────────────

class TestPaperFlag:
    @pytest.mark.parametrize("val", ["true", "TRUE", "1", "yes", "anything_else", ""])
    def test_paper_true_for_safe_values(self, clean_env, val):
        clean_env.setenv("ALPACA_API_KEY",    "PKfoo")
        clean_env.setenv("ALPACA_API_SECRET", "x" * 30)
        clean_env.setenv("ALPACA_PAPER", val)
        creds = load_alpaca_creds()
        assert creds.paper is True

    @pytest.mark.parametrize("val", ["false", "FALSE", "0", "no", "live", "off"])
    def test_paper_false_for_live_values(self, clean_env, val):
        clean_env.setenv("ALPACA_API_KEY",    "PKfoo")
        clean_env.setenv("ALPACA_API_SECRET", "x" * 30)
        clean_env.setenv("ALPACA_PAPER", val)
        creds = load_alpaca_creds()
        assert creds.paper is False

    def test_paper_defaults_to_true_when_unset(self, clean_env):
        """If no PAPER env var is set, default to PAPER (safe). Forgetting
        to set the flag should never accidentally go live."""
        clean_env.setenv("ALPACA_API_KEY",    "PKfoo")
        clean_env.setenv("ALPACA_API_SECRET", "x" * 30)
        creds = load_alpaca_creds()
        assert creds.paper is True


# ── Missing credentials ───────────────────────────────────────────────────────

class TestMissingCredentials:
    def test_nothing_set_returns_incomplete(self, clean_env):
        creds = load_alpaca_creds()
        assert creds.is_complete is False
        assert creds.key    == ""
        assert creds.secret == ""

    def test_key_only_returns_incomplete(self, clean_env):
        clean_env.setenv("ALPACA_API_KEY", "PKfoo")
        creds = load_alpaca_creds()
        assert creds.is_complete is False

    def test_secret_only_returns_incomplete(self, clean_env):
        clean_env.setenv("ALPACA_API_SECRET", "x" * 30)
        creds = load_alpaca_creds()
        assert creds.is_complete is False

    def test_whitespace_only_treated_as_unset(self, clean_env):
        """A var set to '   ' (just whitespace) should be treated as unset."""
        clean_env.setenv("ALPACA_API_KEY",    "   ")
        clean_env.setenv("ALPACA_API_SECRET", "x" * 30)
        creds = load_alpaca_creds()
        assert creds.is_complete is False
