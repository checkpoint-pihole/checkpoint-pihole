"""Notification configuration loaded from environment variables."""

import logging
import os
import threading

from config.env import get_bool_env

logger = logging.getLogger(__name__)

__all__ = ["get_bool_env", "NotificationSettings", "get_notification_settings", "reload_notification_settings"]


class NotificationSettings:
    """Notification settings loaded from environment variables."""

    def __init__(self):
        # Event settings
        self.notify_on_failure = get_bool_env("NOTIFY_ON_FAILURE", True)
        self.notify_on_success = get_bool_env("NOTIFY_ON_SUCCESS", False)
        self.notify_on_connection_lost = get_bool_env("NOTIFY_ON_CONNECTION_LOST", True)

        # Provider configurations
        self.providers = self._load_providers()

    def _load_providers(self) -> list[dict]:
        """Load all enabled provider configurations."""
        providers = []

        # Discord
        if get_bool_env("NOTIFY_DISCORD_ENABLED"):
            webhook_url = os.getenv("NOTIFY_DISCORD_WEBHOOK_URL")
            if webhook_url:
                providers.append({"provider": "discord", "webhook_url": webhook_url})
            else:
                logger.warning("Discord notifications enabled but NOTIFY_DISCORD_WEBHOOK_URL not set")

        # Slack
        if get_bool_env("NOTIFY_SLACK_ENABLED"):
            webhook_url = os.getenv("NOTIFY_SLACK_WEBHOOK_URL")
            if webhook_url:
                providers.append({"provider": "slack", "webhook_url": webhook_url})
            else:
                logger.warning("Slack notifications enabled but NOTIFY_SLACK_WEBHOOK_URL not set")

        # Telegram
        if get_bool_env("NOTIFY_TELEGRAM_ENABLED"):
            bot_token = os.getenv("NOTIFY_TELEGRAM_BOT_TOKEN")
            chat_id = os.getenv("NOTIFY_TELEGRAM_CHAT_ID")
            if bot_token and chat_id:
                providers.append({"provider": "telegram", "bot_token": bot_token, "chat_id": chat_id})
            else:
                logger.warning("Telegram notifications enabled but BOT_TOKEN or CHAT_ID not set")

        # Pushbullet
        if get_bool_env("NOTIFY_PUSHBULLET_ENABLED"):
            api_key = os.getenv("NOTIFY_PUSHBULLET_API_KEY")
            if api_key:
                providers.append({"provider": "pushbullet", "api_key": api_key})
            else:
                logger.warning("Pushbullet notifications enabled but NOTIFY_PUSHBULLET_API_KEY not set")

        # Home Assistant
        if get_bool_env("NOTIFY_HOMEASSISTANT_ENABLED"):
            url = os.getenv("NOTIFY_HOMEASSISTANT_URL")
            token = os.getenv("NOTIFY_HOMEASSISTANT_TOKEN")
            webhook_id = os.getenv("NOTIFY_HOMEASSISTANT_WEBHOOK_ID")
            if url and (token or webhook_id):
                providers.append(
                    {
                        "provider": "homeassistant",
                        "url": url,
                        "token": token or "",
                        "webhook_id": webhook_id or "",
                    }
                )
            else:
                logger.warning("Home Assistant notifications enabled but URL or token/webhook_id not set")

        return providers

    def should_notify(self, event: str) -> bool:
        """Check if notifications are enabled for this event type."""
        if not self.providers:
            return False

        if "failed" in event:
            return self.notify_on_failure
        elif "success" in event:
            return self.notify_on_success
        elif event == "connection_lost":
            return self.notify_on_connection_lost
        return False

    def get_enabled_provider_names(self) -> list[str]:
        """Get list of enabled provider names for display."""
        return [p["provider"] for p in self.providers]


# Singleton instance (thread-safe)
_settings: NotificationSettings | None = None
_settings_lock = threading.Lock()


def get_notification_settings() -> NotificationSettings:
    """Get notification settings (cached singleton, thread-safe)."""
    global _settings

    # Fast path: already initialized
    if _settings is not None:
        return _settings

    # Slow path: need to initialize with lock
    with _settings_lock:
        # Double-check after acquiring lock
        if _settings is None:
            _settings = NotificationSettings()
        return _settings


def reload_notification_settings() -> NotificationSettings:
    """Reload notification settings from environment (useful for testing)."""
    global _settings
    with _settings_lock:
        _settings = NotificationSettings()
        return _settings
