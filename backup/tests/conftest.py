"""Shared fixtures for Checkpoint Pi-hole tests."""

import tempfile
from datetime import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from django.test import Client

from backup.models import BackupRecord, PiholeConfig


@pytest.fixture(autouse=True)
def use_simple_staticfiles_storage(settings, tmp_path):
    """Use simple staticfiles storage for tests to avoid manifest issues.

    Also sets STATIC_ROOT to a temp directory to prevent warnings about
    missing staticfiles configuration.
    """
    settings.STATIC_ROOT = str(tmp_path / "static")
    settings.STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }


@pytest.fixture
def client():
    """Django test client."""
    return Client()


@pytest.fixture
def authenticated_client(client):
    """Django test client with authenticated session."""
    session = client.session
    session["authenticated"] = True
    session.save()
    return client


@pytest.fixture(autouse=True)
def pihole_credentials(monkeypatch):
    """Configure Pi-hole credentials via prefixed environment variables for tests."""
    monkeypatch.setenv("PIHOLE_PRIMARY_URL", "https://pihole.local")
    monkeypatch.setenv("PIHOLE_PRIMARY_PASSWORD", "testpassword123")
    monkeypatch.setenv("PIHOLE_PRIMARY_VERIFY_SSL", "false")


@pytest.fixture
def pihole_config(db):
    """Create a test PiholeConfig instance."""
    return PiholeConfig.objects.create(
        name="Test Pi-hole",
        env_prefix="PRIMARY",
        backup_frequency="daily",
        backup_time=time(3, 0),
        backup_day=0,
        max_backups=10,
        max_age_days=30,
        is_active=True,
    )


@pytest.fixture
def inactive_config(db):
    """Create an inactive PiholeConfig instance."""
    return PiholeConfig.objects.create(
        name="Inactive Pi-hole",
        env_prefix="INACTIVE",
        backup_frequency="daily",
        backup_time=time(3, 0),
        is_active=False,
    )


@pytest.fixture
def backup_record(pihole_config, temp_backup_dir):
    """Create a test BackupRecord with an actual file."""
    filepath = temp_backup_dir / "test_backup.zip"
    filepath.write_bytes(b"PK\x03\x04" + b"test backup content")

    return BackupRecord.objects.create(
        config=pihole_config,
        filename="test_backup.zip",
        file_path=str(filepath),
        file_size=len(b"PK\x03\x04" + b"test backup content"),
        checksum="abc123def456",
        status="success",
        is_manual=False,
    )


@pytest.fixture
def failed_backup_record(pihole_config):
    """Create a failed BackupRecord."""
    return BackupRecord.objects.create(
        config=pihole_config,
        filename="failed_backup.zip",
        file_path="",
        file_size=0,
        status="failed",
        error_message="Connection failed",
        is_manual=False,
    )


@pytest.fixture
def temp_backup_dir(settings):
    """Create a temporary backup directory and patch settings."""
    with tempfile.TemporaryDirectory() as tmpdir:
        backup_path = Path(tmpdir) / "backups"
        backup_path.mkdir()
        settings.BACKUP_DIR = backup_path
        yield backup_path


@pytest.fixture
def sample_backup_data():
    """Mock ZIP file content for testing."""
    return b"PK\x03\x04" + b"\x00" * 100 + b"mock backup data"


@pytest.fixture
def mock_pihole_auth_response():
    """Mock successful Pi-hole authentication response."""
    return {
        "session": {
            "sid": "test-session-id-12345",
            "validity": 300,
        }
    }


@pytest.fixture
def mock_pihole_version_response():
    """Mock Pi-hole version info response."""
    return {
        "version": {
            "core": {
                "local": {
                    "version": "v6.0",
                    "branch": "master",
                }
            },
            "ftl": {
                "local": {
                    "version": "v6.0",
                }
            },
            "web": {
                "local": {
                    "version": "v6.0",
                }
            },
        }
    }


@pytest.fixture
def auth_disabled_settings(settings):
    """Configure settings with authentication disabled."""
    settings.REQUIRE_AUTH = False
    settings.APP_PASSWORD_HASH = ""
    return settings


@pytest.fixture
def auth_enabled_settings(settings):
    """Configure settings with authentication enabled."""
    from django.contrib.auth.hashers import make_password

    settings.REQUIRE_AUTH = True
    settings.APP_PASSWORD_HASH = make_password("testpassword")
    return settings


@pytest.fixture
def mock_requests_session():
    """Mock requests.Session for API testing."""
    with patch("requests.Session") as mock_session_class:
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session
        yield mock_session
