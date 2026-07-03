"""Tests for security-related Django settings computed from environment.

These reload ``config.settings`` with the relevant env var set/unset so we can
assert the module-level values it derives (Finding 2 — secure cookies).
"""

import importlib

import config.settings as settings_module


def _reload_settings():
    return importlib.reload(settings_module)


class TestSecureCookiesSetting:
    """The SECURE_COOKIES flag toggles cookie/proxy HTTPS hardening."""

    def test_disabled_by_default(self, monkeypatch):
        """Unset flag keeps the plain-HTTP dev defaults (all off)."""
        monkeypatch.delenv("SECURE_COOKIES", raising=False)
        try:
            mod = _reload_settings()
            assert mod.SECURE_COOKIES is False
            assert mod.SESSION_COOKIE_SECURE is False
            assert mod.CSRF_COOKIE_SECURE is False
            assert mod.SECURE_PROXY_SSL_HEADER is None
        finally:
            _reload_settings()

    def test_enabled_sets_secure_flags(self, monkeypatch):
        """SECURE_COOKIES=true flags cookies Secure and trusts the proxy proto header."""
        monkeypatch.setenv("SECURE_COOKIES", "true")
        try:
            mod = _reload_settings()
            assert mod.SECURE_COOKIES is True
            assert mod.SESSION_COOKIE_SECURE is True
            assert mod.CSRF_COOKIE_SECURE is True
            assert mod.SECURE_PROXY_SSL_HEADER == ("HTTP_X_FORWARDED_PROTO", "https")
        finally:
            monkeypatch.delenv("SECURE_COOKIES", raising=False)
            _reload_settings()
