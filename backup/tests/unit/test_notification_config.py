"""Unit tests for backup.services.notifications.config (Finding 13).

Covers _load_providers() env branches (a provider is only registered when its
NOTIFY_<PROVIDER>_ENABLED flag is set *and* its required vars are present) and
the should_notify() event-routing truth table.
"""

import pytest

import backup.services.notifications.config as config_module
from backup.services.notifications.base import NotificationEvent
from backup.services.notifications.config import reload_notification_settings

# All provider enable flags — cleared before each test for a clean baseline.
ENABLE_FLAGS = [
    "NOTIFY_DISCORD_ENABLED",
    "NOTIFY_SLACK_ENABLED",
    "NOTIFY_TELEGRAM_ENABLED",
    "NOTIFY_PUSHBULLET_ENABLED",
    "NOTIFY_HOMEASSISTANT_ENABLED",
]

# Every provider-related env var, cleared before each test so the host env can't
# leak real credentials into the "missing required vars" assertions.
ALL_PROVIDER_VARS = ENABLE_FLAGS + [
    "NOTIFY_DISCORD_WEBHOOK_URL",
    "NOTIFY_SLACK_WEBHOOK_URL",
    "NOTIFY_TELEGRAM_BOT_TOKEN",
    "NOTIFY_TELEGRAM_CHAT_ID",
    "NOTIFY_PUSHBULLET_API_KEY",
    "NOTIFY_HOMEASSISTANT_URL",
    "NOTIFY_HOMEASSISTANT_TOKEN",
    "NOTIFY_HOMEASSISTANT_WEBHOOK_ID",
    "NOTIFY_ON_FAILURE",
    "NOTIFY_ON_SUCCESS",
    "NOTIFY_ON_CONNECTION_LOST",
]


@pytest.fixture(autouse=True)
def clean_notification_env(monkeypatch):
    """Start each test with no provider env vars and reset the cached singleton."""
    for var in ALL_PROVIDER_VARS:
        monkeypatch.delenv(var, raising=False)
    yield
    # Drop the singleton built from test env so later tests re-read real env.
    config_module._settings = None


# One entry per provider: (enable flag, required vars mapping, provider name).
PROVIDER_CASES = [
    ("NOTIFY_DISCORD_ENABLED", {"NOTIFY_DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/1/a"}, "discord"),
    ("NOTIFY_SLACK_ENABLED", {"NOTIFY_SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/x"}, "slack"),
    (
        "NOTIFY_TELEGRAM_ENABLED",
        {"NOTIFY_TELEGRAM_BOT_TOKEN": "bot-token", "NOTIFY_TELEGRAM_CHAT_ID": "12345"},
        "telegram",
    ),
    ("NOTIFY_PUSHBULLET_ENABLED", {"NOTIFY_PUSHBULLET_API_KEY": "api-key"}, "pushbullet"),
    (
        "NOTIFY_HOMEASSISTANT_ENABLED",
        {"NOTIFY_HOMEASSISTANT_URL": "https://ha.local", "NOTIFY_HOMEASSISTANT_TOKEN": "tok"},
        "homeassistant",
    ),
]


class TestLoadProviders:
    @pytest.mark.parametrize("flag,required,name", PROVIDER_CASES)
    def test_enabled_with_required_vars_registers_provider(self, monkeypatch, flag, required, name):
        monkeypatch.setenv(flag, "true")
        for key, value in required.items():
            monkeypatch.setenv(key, value)

        settings = reload_notification_settings()

        assert name in settings.get_enabled_provider_names()

    @pytest.mark.parametrize("flag,required,name", PROVIDER_CASES)
    def test_enabled_without_required_vars_skips_provider(self, monkeypatch, flag, required, name):
        monkeypatch.setenv(flag, "true")
        # Required vars intentionally left unset (cleared by the autouse fixture).

        settings = reload_notification_settings()

        assert name not in settings.get_enabled_provider_names()
        assert settings.providers == []

    def test_disabled_provider_not_registered_even_with_vars(self, monkeypatch):
        # Flag off but credentials present -> still skipped.
        monkeypatch.setenv("NOTIFY_DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/1/a")
        settings = reload_notification_settings()
        assert "discord" not in settings.get_enabled_provider_names()

    def test_telegram_requires_both_token_and_chat_id(self, monkeypatch):
        monkeypatch.setenv("NOTIFY_TELEGRAM_ENABLED", "true")
        monkeypatch.setenv("NOTIFY_TELEGRAM_BOT_TOKEN", "bot-token")
        # chat_id missing
        settings = reload_notification_settings()
        assert "telegram" not in settings.get_enabled_provider_names()

    def test_homeassistant_url_only_is_skipped(self, monkeypatch):
        monkeypatch.setenv("NOTIFY_HOMEASSISTANT_ENABLED", "true")
        monkeypatch.setenv("NOTIFY_HOMEASSISTANT_URL", "https://ha.local")
        # neither token nor webhook_id
        settings = reload_notification_settings()
        assert "homeassistant" not in settings.get_enabled_provider_names()

    def test_homeassistant_url_plus_webhook_registers(self, monkeypatch):
        monkeypatch.setenv("NOTIFY_HOMEASSISTANT_ENABLED", "true")
        monkeypatch.setenv("NOTIFY_HOMEASSISTANT_URL", "https://ha.local")
        monkeypatch.setenv("NOTIFY_HOMEASSISTANT_WEBHOOK_ID", "hook123")
        settings = reload_notification_settings()
        assert "homeassistant" in settings.get_enabled_provider_names()

    def test_multiple_providers_registered_together(self, monkeypatch):
        monkeypatch.setenv("NOTIFY_DISCORD_ENABLED", "true")
        monkeypatch.setenv("NOTIFY_DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/1/a")
        monkeypatch.setenv("NOTIFY_PUSHBULLET_ENABLED", "true")
        monkeypatch.setenv("NOTIFY_PUSHBULLET_API_KEY", "api-key")

        names = reload_notification_settings().get_enabled_provider_names()

        assert set(names) == {"discord", "pushbullet"}


def _settings_with_discord_and_toggles(monkeypatch, on_failure, on_success, on_conn):
    """Configure one provider plus the three event toggles, return settings."""
    monkeypatch.setenv("NOTIFY_DISCORD_ENABLED", "true")
    monkeypatch.setenv("NOTIFY_DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/1/a")
    monkeypatch.setenv("NOTIFY_ON_FAILURE", str(on_failure).lower())
    monkeypatch.setenv("NOTIFY_ON_SUCCESS", str(on_success).lower())
    monkeypatch.setenv("NOTIFY_ON_CONNECTION_LOST", str(on_conn).lower())
    return reload_notification_settings()


class TestShouldNotify:
    # (event, on_failure, on_success, on_conn, expected)
    TRUTH_TABLE = [
        (NotificationEvent.BACKUP_FAILED, True, False, False, True),
        (NotificationEvent.BACKUP_FAILED, False, True, True, False),
        (NotificationEvent.RESTORE_FAILED, True, False, False, True),
        (NotificationEvent.RESTORE_FAILED, False, True, True, False),
        (NotificationEvent.BACKUP_SUCCESS, False, True, False, True),
        (NotificationEvent.BACKUP_SUCCESS, True, False, True, False),
        (NotificationEvent.RESTORE_SUCCESS, False, True, False, True),
        (NotificationEvent.RESTORE_SUCCESS, True, False, True, False),
        (NotificationEvent.CONNECTION_LOST, False, False, True, True),
        (NotificationEvent.CONNECTION_LOST, True, True, False, False),
    ]

    @pytest.mark.parametrize("event,on_failure,on_success,on_conn,expected", TRUTH_TABLE)
    def test_should_notify_routing(self, monkeypatch, event, on_failure, on_success, on_conn, expected):
        settings = _settings_with_discord_and_toggles(monkeypatch, on_failure, on_success, on_conn)
        assert settings.should_notify(event.value) is expected

    def test_no_providers_never_notifies(self, monkeypatch):
        # All toggles on, but no provider configured -> always False.
        monkeypatch.setenv("NOTIFY_ON_FAILURE", "true")
        monkeypatch.setenv("NOTIFY_ON_SUCCESS", "true")
        monkeypatch.setenv("NOTIFY_ON_CONNECTION_LOST", "true")
        settings = reload_notification_settings()

        assert settings.providers == []
        for event in NotificationEvent:
            assert settings.should_notify(event.value) is False

    def test_unknown_event_returns_false(self, monkeypatch):
        settings = _settings_with_discord_and_toggles(monkeypatch, True, True, True)
        assert settings.should_notify("something_else") is False
