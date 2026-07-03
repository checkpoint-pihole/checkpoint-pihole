"""Unit tests for CredentialService."""

import pytest

from backup.services.credential_service import CredentialService


@pytest.mark.django_db
class TestCredentialServiceGetCredentials:
    """Tests for CredentialService.get_credentials()."""

    def test_returns_credentials_with_prefix(self, pihole_config, monkeypatch):
        """get_credentials should return credentials from prefix env vars."""
        monkeypatch.setenv("PIHOLE_PRIMARY_URL", "https://test.pihole.local")
        monkeypatch.setenv("PIHOLE_PRIMARY_PASSWORD", "testpassword")
        monkeypatch.setenv("PIHOLE_PRIMARY_VERIFY_SSL", "true")

        creds = CredentialService.get_credentials(pihole_config)

        assert creds["url"] == "https://test.pihole.local"
        assert creds["password"] == "testpassword"
        assert creds["verify_ssl"] is True

    def test_raises_error_when_url_missing(self, pihole_config, monkeypatch):
        """get_credentials should raise ValueError when URL is missing."""
        monkeypatch.delenv("PIHOLE_PRIMARY_URL", raising=False)
        monkeypatch.setenv("PIHOLE_PRIMARY_PASSWORD", "testpassword")

        with pytest.raises(ValueError, match="PIHOLE_PRIMARY_URL"):
            CredentialService.get_credentials(pihole_config)

    def test_raises_error_when_password_missing(self, pihole_config, monkeypatch):
        """get_credentials should raise ValueError when password is missing."""
        monkeypatch.setenv("PIHOLE_PRIMARY_URL", "https://test.pihole.local")
        monkeypatch.delenv("PIHOLE_PRIMARY_PASSWORD", raising=False)

        with pytest.raises(ValueError, match="PIHOLE_PRIMARY_PASSWORD"):
            CredentialService.get_credentials(pihole_config)

    def test_returns_false_verify_ssl_by_default(self, pihole_config, monkeypatch):
        """get_credentials should return verify_ssl=False by default."""
        monkeypatch.setenv("PIHOLE_PRIMARY_URL", "https://test.pihole.local")
        monkeypatch.setenv("PIHOLE_PRIMARY_PASSWORD", "testpassword")
        monkeypatch.delenv("PIHOLE_PRIMARY_VERIFY_SSL", raising=False)

        creds = CredentialService.get_credentials(pihole_config)

        assert creds["verify_ssl"] is False

    @pytest.mark.parametrize("value", ["true", "1", "yes", "YES"])
    def test_verify_ssl_accepts_all_truthy_spellings(self, pihole_config, monkeypatch, value):
        """VERIFY_SSL parses like every other bool flag (not just the literal 'true')."""
        monkeypatch.setenv("PIHOLE_PRIMARY_URL", "https://test.pihole.local")
        monkeypatch.setenv("PIHOLE_PRIMARY_PASSWORD", "testpassword")
        monkeypatch.setenv("PIHOLE_PRIMARY_VERIFY_SSL", value)

        creds = CredentialService.get_credentials(pihole_config)

        assert creds["verify_ssl"] is True


@pytest.mark.django_db
class TestCredentialServiceIsConfigured:
    """Tests for CredentialService.is_configured()."""

    def test_returns_true_when_configured(self, pihole_config):
        """is_configured should return True when URL and password are set."""
        assert CredentialService.is_configured(pihole_config) is True

    def test_returns_false_when_url_missing(self, pihole_config, monkeypatch):
        """is_configured should return False when URL is missing."""
        monkeypatch.delenv("PIHOLE_PRIMARY_URL", raising=False)

        assert CredentialService.is_configured(pihole_config) is False

    def test_returns_false_when_password_missing(self, pihole_config, monkeypatch):
        """is_configured should return False when password is missing."""
        monkeypatch.delenv("PIHOLE_PRIMARY_PASSWORD", raising=False)

        assert CredentialService.is_configured(pihole_config) is False

    def test_returns_false_when_both_missing(self, pihole_config, monkeypatch):
        """is_configured should return False when both are missing."""
        monkeypatch.delenv("PIHOLE_PRIMARY_URL", raising=False)
        monkeypatch.delenv("PIHOLE_PRIMARY_PASSWORD", raising=False)

        assert CredentialService.is_configured(pihole_config) is False


@pytest.mark.django_db
class TestCredentialServiceGetStatus:
    """Tests for CredentialService.get_status()."""

    def test_returns_status_dict(self, pihole_config, monkeypatch):
        """get_status should return a dict with url, has_password, verify_ssl, env_prefix."""
        monkeypatch.setenv("PIHOLE_PRIMARY_URL", "https://test.pihole.local")
        monkeypatch.setenv("PIHOLE_PRIMARY_PASSWORD", "testpassword")
        monkeypatch.setenv("PIHOLE_PRIMARY_VERIFY_SSL", "true")

        status = CredentialService.get_status(pihole_config)

        assert status["url"] == "https://test.pihole.local"
        assert status["has_password"] is True
        assert status["verify_ssl"] is True
        assert status["env_prefix"] == "PRIMARY"

    def test_returns_none_url_when_not_set(self, pihole_config, monkeypatch):
        """get_status should return url=None when env var is not set."""
        monkeypatch.delenv("PIHOLE_PRIMARY_URL", raising=False)

        status = CredentialService.get_status(pihole_config)

        assert status["url"] is None

    def test_returns_false_has_password_when_not_set(self, pihole_config, monkeypatch):
        """get_status should return has_password=False when password is not set."""
        monkeypatch.delenv("PIHOLE_PRIMARY_PASSWORD", raising=False)

        status = CredentialService.get_status(pihole_config)

        assert status["has_password"] is False
