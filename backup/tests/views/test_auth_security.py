"""Security tests for authentication and login rate limiting."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from django.test import RequestFactory
from django.urls import reverse

from backup.views import _get_client_ip

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.django_db
class TestSessionFixation:
    def test_login_rotates_session_key(self, client, auth_enabled_settings):
        """A successful login must cycle the session key to prevent fixation."""
        session = client.session
        session["preexisting"] = "value"
        session.save()
        old_key = session.session_key
        assert old_key is not None

        response = client.post(reverse("login"), {"password": "testpassword"})

        assert response.status_code == 302
        new_key = client.session.session_key
        assert new_key is not None
        assert new_key != old_key
        assert client.session.get("authenticated") is True


class TestClientIpProxyTrust:
    def test_ignores_forwarded_for_when_proxy_untrusted(self, settings):
        """With TRUST_PROXY off, the spoofable header is ignored."""
        settings.TRUST_PROXY = False
        request = RequestFactory().post("/login/", HTTP_X_FORWARDED_FOR="1.2.3.4", REMOTE_ADDR="10.0.0.1")
        assert _get_client_ip(request) == "10.0.0.1"

    def test_uses_forwarded_for_when_proxy_trusted(self, settings):
        """With TRUST_PROXY on, the real client IP comes from the header."""
        settings.TRUST_PROXY = True
        request = RequestFactory().post("/login/", HTTP_X_FORWARDED_FOR="1.2.3.4, 10.0.0.1", REMOTE_ADDR="10.0.0.1")
        assert _get_client_ip(request) == "1.2.3.4"


def _run_django_setup(env_overrides):
    """Load Django settings in a fresh process so settings-time validation runs."""
    env = dict(os.environ)
    env.update({"DJANGO_SETTINGS_MODULE": "config.settings", "SECRET_KEY": "test-secret-key"})
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-c", "import django; django.setup()"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


class TestAuthFailClosed:
    def test_require_auth_without_password_refuses_to_start(self):
        """REQUIRE_AUTH=true with an empty password must abort startup, not fail open."""
        result = _run_django_setup({"REQUIRE_AUTH": "true", "APP_PASSWORD": ""})
        assert result.returncode != 0
        assert "APP_PASSWORD" in result.stderr

    def test_require_auth_with_password_starts(self):
        """REQUIRE_AUTH=true with a password set still starts normally."""
        result = _run_django_setup({"REQUIRE_AUTH": "true", "APP_PASSWORD": "secret"})
        assert result.returncode == 0, result.stderr
