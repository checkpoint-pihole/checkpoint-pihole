# ADR-0009: Backup Failure Notifications

**Status:** Implemented
**Date:** 2026-01-18

---

## Context

Checkpoint Pi-hole creates automated backups on a schedule, but there's no way to alert users when backups fail. Silent failures are dangerous for any backup system - users may assume backups are working when they're not, leading to data loss during disaster recovery.

Common failure scenarios:
- Pi-hole unreachable (network issues, Pi-hole down)
- Authentication failures (password changed)
- Disk full or write errors
- Pi-hole API errors

Users need proactive notification when backups fail so they can investigate and fix issues promptly.

---

## Decision

Implement a notification system that alerts users when backup operations fail. Support multiple popular notification services commonly used in self-hosted/homelab environments:

1. **Discord** - Webhook-based, very popular in tech communities
2. **Slack** - Webhook-based, common in professional environments
3. **Telegram** - Bot API, popular for personal notifications
4. **Pushbullet** - Push notifications to devices
5. **Home Assistant** - Webhook integration for smart home users

### Design Principles

1. **Provider-agnostic architecture** - Easy to add new notification providers
2. **Non-blocking** - Notifications shouldn't delay or break backup operations
3. **Configurable** - Users choose which events trigger notifications
4. **Fail-safe** - Notification failures don't affect backup functionality
5. **Environment-based configuration** - All notification settings via env vars (no database storage)

---

## Environment Variables

All notification providers are configured via environment variables, following the pattern used for other settings in this project. No notification settings are stored in the database.

### General Settings

| Variable | Description | Default |
|----------|-------------|---------|
| `NOTIFY_ON_FAILURE` | Enable notifications for backup/restore failures | `true` |
| `NOTIFY_ON_SUCCESS` | Enable notifications for backup/restore success | `false` |
| `NOTIFY_ON_CONNECTION_LOST` | Enable notifications when Pi-hole is unreachable | `true` |

### Discord

| Variable | Description | Required |
|----------|-------------|----------|
| `NOTIFY_DISCORD_ENABLED` | Enable Discord notifications | No |
| `NOTIFY_DISCORD_WEBHOOK_URL` | Discord webhook URL | Yes (if enabled) |

### Slack

| Variable | Description | Required |
|----------|-------------|----------|
| `NOTIFY_SLACK_ENABLED` | Enable Slack notifications | No |
| `NOTIFY_SLACK_WEBHOOK_URL` | Slack incoming webhook URL | Yes (if enabled) |

### Telegram

| Variable | Description | Required |
|----------|-------------|----------|
| `NOTIFY_TELEGRAM_ENABLED` | Enable Telegram notifications | No |
| `NOTIFY_TELEGRAM_BOT_TOKEN` | Telegram bot token from BotFather | Yes (if enabled) |
| `NOTIFY_TELEGRAM_CHAT_ID` | Target chat/channel ID | Yes (if enabled) |

### Pushbullet

| Variable | Description | Required |
|----------|-------------|----------|
| `NOTIFY_PUSHBULLET_ENABLED` | Enable Pushbullet notifications | No |
| `NOTIFY_PUSHBULLET_API_KEY` | Pushbullet access token | Yes (if enabled) |

### Home Assistant

| Variable | Description | Required |
|----------|-------------|----------|
| `NOTIFY_HOMEASSISTANT_ENABLED` | Enable Home Assistant notifications | No |
| `NOTIFY_HOMEASSISTANT_URL` | Home Assistant base URL | Yes (if enabled) |
| `NOTIFY_HOMEASSISTANT_TOKEN` | Long-lived access token | No (use webhook instead) |
| `NOTIFY_HOMEASSISTANT_WEBHOOK_ID` | Webhook ID (alternative to token) | No |

### Example `.env` Configuration

```bash
# Enable failure notifications (default)
NOTIFY_ON_FAILURE=true
NOTIFY_ON_SUCCESS=false

# Discord notifications
NOTIFY_DISCORD_ENABLED=true
NOTIFY_DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/123456/abcdef

# Telegram notifications (can enable multiple providers)
NOTIFY_TELEGRAM_ENABLED=true
NOTIFY_TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
NOTIFY_TELEGRAM_CHAT_ID=-1001234567890
```

---

## Implementation Plan

### 1. Notification Provider Base Class (`backup/services/notifications/base.py`)

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum


class NotificationEvent(Enum):
    BACKUP_FAILED = "backup_failed"
    BACKUP_SUCCESS = "backup_success"  # Optional, off by default
    RESTORE_FAILED = "restore_failed"
    RESTORE_SUCCESS = "restore_success"  # Optional, off by default
    CONNECTION_LOST = "connection_lost"


@dataclass
class NotificationPayload:
    event: NotificationEvent
    title: str
    message: str
    pihole_name: str
    timestamp: str
    details: dict | None = None


class NotificationProvider(ABC):
    """Base class for notification providers."""

    name: str = "base"
    display_name: str = "Base Provider"

    @abstractmethod
    def send(self, payload: NotificationPayload) -> bool:
        """
        Send a notification.

        Returns:
            True if sent successfully, False otherwise
        """
        pass

    @abstractmethod
    def validate_config(self, config: dict) -> tuple[bool, str]:
        """
        Validate provider-specific configuration.

        Returns:
            (is_valid, error_message)
        """
        pass

    @abstractmethod
    def test_connection(self, config: dict) -> tuple[bool, str]:
        """
        Send a test notification to verify configuration.

        Returns:
            (success, message)
        """
        pass
```

### 2. Provider Implementations

#### Discord (`backup/services/notifications/discord.py`)

```python
import requests
from .base import NotificationProvider, NotificationPayload


class DiscordProvider(NotificationProvider):
    name = "discord"
    display_name = "Discord"

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def send(self, payload: NotificationPayload) -> bool:
        color = 0xFF0000 if "failed" in payload.event.value else 0x00FF00

        embed = {
            "title": payload.title,
            "description": payload.message,
            "color": color,
            "fields": [
                {"name": "Pi-hole", "value": payload.pihole_name, "inline": True},
                {"name": "Time", "value": payload.timestamp, "inline": True},
            ],
            "footer": {"text": "Checkpoint Pi-hole"},
        }

        if payload.details:
            for key, value in payload.details.items():
                embed["fields"].append({"name": key, "value": str(value), "inline": False})

        response = requests.post(
            self.webhook_url,
            json={"embeds": [embed]},
            timeout=10,
        )
        return response.status_code == 204

    def validate_config(self, config: dict) -> tuple[bool, str]:
        webhook_url = config.get("webhook_url", "")
        if not webhook_url:
            return False, "Webhook URL is required"
        if not webhook_url.startswith("https://discord.com/api/webhooks/"):
            return False, "Invalid Discord webhook URL"
        return True, ""

    def test_connection(self, config: dict) -> tuple[bool, str]:
        try:
            self.webhook_url = config["webhook_url"]
            payload = NotificationPayload(
                event=NotificationEvent.BACKUP_SUCCESS,
                title="Test Notification",
                message="Checkpoint Pi-hole notifications are working!",
                pihole_name="Test",
                timestamp="Now",
            )
            if self.send(payload):
                return True, "Test notification sent successfully"
            return False, "Failed to send test notification"
        except Exception as e:
            return False, str(e)
```

#### Slack (`backup/services/notifications/slack.py`)

```python
class SlackProvider(NotificationProvider):
    name = "slack"
    display_name = "Slack"

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def send(self, payload: NotificationPayload) -> bool:
        color = "danger" if "failed" in payload.event.value else "good"

        blocks = {
            "attachments": [
                {
                    "color": color,
                    "blocks": [
                        {
                            "type": "header",
                            "text": {"type": "plain_text", "text": payload.title},
                        },
                        {
                            "type": "section",
                            "text": {"type": "mrkdwn", "text": payload.message},
                        },
                        {
                            "type": "context",
                            "elements": [
                                {"type": "mrkdwn", "text": f"*Pi-hole:* {payload.pihole_name}"},
                                {"type": "mrkdwn", "text": f"*Time:* {payload.timestamp}"},
                            ],
                        },
                    ],
                }
            ]
        }

        response = requests.post(self.webhook_url, json=blocks, timeout=10)
        return response.status_code == 200

    def validate_config(self, config: dict) -> tuple[bool, str]:
        webhook_url = config.get("webhook_url", "")
        if not webhook_url:
            return False, "Webhook URL is required"
        if not webhook_url.startswith("https://hooks.slack.com/"):
            return False, "Invalid Slack webhook URL"
        return True, ""
```

#### Telegram (`backup/services/notifications/telegram.py`)

```python
class TelegramProvider(NotificationProvider):
    name = "telegram"
    display_name = "Telegram"

    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id

    def send(self, payload: NotificationPayload) -> bool:
        icon = "\u274c" if "failed" in payload.event.value else "\u2705"
        text = f"{icon} *{payload.title}*\n\n{payload.message}\n\n"
        text += f"\U0001F4CD Pi-hole: {payload.pihole_name}\n"
        text += f"\U0001F552 Time: {payload.timestamp}"

        response = requests.post(
            f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
            json={
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": "Markdown",
            },
            timeout=10,
        )
        return response.status_code == 200

    def validate_config(self, config: dict) -> tuple[bool, str]:
        if not config.get("bot_token"):
            return False, "Bot token is required"
        if not config.get("chat_id"):
            return False, "Chat ID is required"
        return True, ""
```

#### Pushbullet (`backup/services/notifications/pushbullet.py`)

```python
class PushbulletProvider(NotificationProvider):
    name = "pushbullet"
    display_name = "Pushbullet"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def send(self, payload: NotificationPayload) -> bool:
        response = requests.post(
            "https://api.pushbullet.com/v2/pushes",
            headers={"Access-Token": self.api_key},
            json={
                "type": "note",
                "title": payload.title,
                "body": f"{payload.message}\n\nPi-hole: {payload.pihole_name}\nTime: {payload.timestamp}",
            },
            timeout=10,
        )
        return response.status_code == 200

    def validate_config(self, config: dict) -> tuple[bool, str]:
        if not config.get("api_key"):
            return False, "API key is required"
        return True, ""
```

#### Home Assistant (`backup/services/notifications/homeassistant.py`)

```python
class HomeAssistantProvider(NotificationProvider):
    name = "homeassistant"
    display_name = "Home Assistant"

    def __init__(self, url: str, token: str, webhook_id: str = None):
        self.url = url.rstrip("/")
        self.token = token
        self.webhook_id = webhook_id

    def send(self, payload: NotificationPayload) -> bool:
        # Support both webhook and REST API methods
        if self.webhook_id:
            # Webhook method (simpler, no auth needed)
            endpoint = f"{self.url}/api/webhook/{self.webhook_id}"
            headers = {}
        else:
            # REST API method
            endpoint = f"{self.url}/api/events/checkpoint_pihole_notification"
            headers = {"Authorization": f"Bearer {self.token}"}

        data = {
            "event": payload.event.value,
            "title": payload.title,
            "message": payload.message,
            "pihole_name": payload.pihole_name,
            "timestamp": payload.timestamp,
            "details": payload.details or {},
        }

        response = requests.post(endpoint, headers=headers, json=data, timeout=10)
        return response.status_code in (200, 201)

    def validate_config(self, config: dict) -> tuple[bool, str]:
        if not config.get("url"):
            return False, "Home Assistant URL is required"
        if not config.get("webhook_id") and not config.get("token"):
            return False, "Either webhook ID or long-lived access token is required"
        return True, ""
```

### 3. Notification Configuration (`backup/services/notifications/config.py`)

Load notification settings from environment variables:

```python
import os
import logging

logger = logging.getLogger(__name__)


def get_bool_env(key: str, default: bool = False) -> bool:
    """Get boolean from environment variable."""
    return os.getenv(key, str(default)).lower() in ("true", "1", "yes")


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
                providers.append({
                    "provider": "homeassistant",
                    "url": url,
                    "token": token or "",
                    "webhook_id": webhook_id or "",
                })
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


# Singleton instance
_settings = None


def get_notification_settings() -> NotificationSettings:
    """Get notification settings (cached singleton)."""
    global _settings
    if _settings is None:
        _settings = NotificationSettings()
    return _settings
```

### 4. Notification Service (`backup/services/notifications/service.py`)

```python
import logging
from concurrent.futures import ThreadPoolExecutor
from .base import NotificationPayload, NotificationEvent
from .config import get_notification_settings
from .discord import DiscordProvider
from .slack import SlackProvider
from .telegram import TelegramProvider
from .pushbullet import PushbulletProvider
from .homeassistant import HomeAssistantProvider

logger = logging.getLogger(__name__)

PROVIDERS = {
    "discord": DiscordProvider,
    "slack": SlackProvider,
    "telegram": TelegramProvider,
    "pushbullet": PushbulletProvider,
    "homeassistant": HomeAssistantProvider,
}


class NotificationService:
    """Manages sending notifications across multiple providers."""

    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=5)
        self.settings = get_notification_settings()

    def send_notification(self, payload: NotificationPayload) -> None:
        """
        Send notification to all configured providers.
        Runs asynchronously to not block the main operation.
        """
        if not self.settings.should_notify(payload.event.value):
            return

        for config in self.settings.providers:
            provider_name = config.get("provider")
            if provider_name not in PROVIDERS:
                logger.warning(f"Unknown notification provider: {provider_name}")
                continue

            # Submit to thread pool for async execution
            self.executor.submit(self._send_to_provider, provider_name, config, payload)

    def _send_to_provider(
        self, provider_name: str, config: dict, payload: NotificationPayload
    ) -> None:
        """Send notification to a single provider."""
        try:
            provider_class = PROVIDERS[provider_name]
            provider = self._create_provider(provider_class, config)
            success = provider.send(payload)
            if not success:
                logger.warning(f"Notification to {provider_name} returned failure status")
        except Exception as e:
            logger.exception(f"Failed to send notification via {provider_name}: {e}")

    def _create_provider(self, provider_class, config: dict):
        """Create provider instance from config."""
        if provider_class == DiscordProvider:
            return DiscordProvider(webhook_url=config["webhook_url"])
        elif provider_class == SlackProvider:
            return SlackProvider(webhook_url=config["webhook_url"])
        elif provider_class == TelegramProvider:
            return TelegramProvider(bot_token=config["bot_token"], chat_id=config["chat_id"])
        elif provider_class == PushbulletProvider:
            return PushbulletProvider(api_key=config["api_key"])
        elif provider_class == HomeAssistantProvider:
            return HomeAssistantProvider(
                url=config["url"],
                token=config.get("token", ""),
                webhook_id=config.get("webhook_id"),
            )
        raise ValueError(f"Unknown provider: {provider_class}")
```

### 5. Integration with Backup Service

Modify `backup/services/backup_service.py` to send notifications:

```python
from .notifications.service import NotificationService
from .notifications.base import NotificationPayload, NotificationEvent
from datetime import datetime

class BackupService:
    def __init__(self, config: PiholeConfig):
        self.config = config
        self.notification_service = NotificationService()

    def create_backup(self) -> BackupRecord:
        try:
            # ... existing backup logic ...
            record = self._perform_backup()

            # Send success notification (if configured via env vars)
            self._notify(
                NotificationEvent.BACKUP_SUCCESS,
                "Backup Completed",
                f"Successfully created backup: {record.filename}",
            )
            return record

        except Exception as e:
            # Send failure notification
            self._notify(
                NotificationEvent.BACKUP_FAILED,
                "Backup Failed",
                f"Failed to create backup: {str(e)}",
                details={"error": str(e)},
            )
            raise

    def _notify(
        self,
        event: NotificationEvent,
        title: str,
        message: str,
        details: dict = None,
    ) -> None:
        """Send notification for an event."""
        payload = NotificationPayload(
            event=event,
            title=title,
            message=message,
            pihole_name=self.config.name or self.config.pihole_url,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            details=details,
        )
        self.notification_service.send_notification(payload)
```

### 6. Django Settings Integration (`config/settings.py`)

Add notification environment variables to the settings for documentation and validation:

```python
# Notification settings (all optional - disabled by default)
NOTIFY_ON_FAILURE = os.getenv("NOTIFY_ON_FAILURE", "true").lower() in ("true", "1", "yes")
NOTIFY_ON_SUCCESS = os.getenv("NOTIFY_ON_SUCCESS", "false").lower() in ("true", "1", "yes")
NOTIFY_ON_CONNECTION_LOST = os.getenv("NOTIFY_ON_CONNECTION_LOST", "true").lower() in ("true", "1", "yes")
```

### 7. Update `.env.example`

Add notification configuration examples:

```bash
# =============================================================================
# Notification Settings (Optional)
# =============================================================================
# Enable notifications for backup failures (default: true)
# NOTIFY_ON_FAILURE=true

# Enable notifications for successful backups (default: false)
# NOTIFY_ON_SUCCESS=false

# Enable notifications when Pi-hole is unreachable (default: true)
# NOTIFY_ON_CONNECTION_LOST=true

# --- Discord ---
# NOTIFY_DISCORD_ENABLED=true
# NOTIFY_DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...

# --- Slack ---
# NOTIFY_SLACK_ENABLED=true
# NOTIFY_SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...

# --- Telegram ---
# NOTIFY_TELEGRAM_ENABLED=true
# NOTIFY_TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
# NOTIFY_TELEGRAM_CHAT_ID=-1001234567890

# --- Pushbullet ---
# NOTIFY_PUSHBULLET_ENABLED=true
# NOTIFY_PUSHBULLET_API_KEY=o.xxxxxxxxxxxxx

# --- Home Assistant ---
# NOTIFY_HOMEASSISTANT_ENABLED=true
# NOTIFY_HOMEASSISTANT_URL=http://homeassistant.local:8123
# NOTIFY_HOMEASSISTANT_WEBHOOK_ID=my_webhook_id
# Or use token instead of webhook:
# NOTIFY_HOMEASSISTANT_TOKEN=eyJ0eX...
```

---

## Files to Create/Modify

| File | Change |
|------|--------|
| `backup/services/notifications/__init__.py` | New - package init |
| `backup/services/notifications/base.py` | New - base classes |
| `backup/services/notifications/config.py` | New - env var configuration loader |
| `backup/services/notifications/discord.py` | New - Discord provider |
| `backup/services/notifications/slack.py` | New - Slack provider |
| `backup/services/notifications/telegram.py` | New - Telegram provider |
| `backup/services/notifications/pushbullet.py` | New - Pushbullet provider |
| `backup/services/notifications/homeassistant.py` | New - Home Assistant provider |
| `backup/services/notifications/service.py` | New - notification orchestration |
| `backup/services/backup_service.py` | Integrate notification calls |
| `config/settings.py` | Add notification env var documentation |
| `.env.example` | Add notification configuration examples |

---

## Dashboard Status Display

While notifications are configured via environment variables (no UI for configuration), the dashboard can display the current notification status:

- Show which providers are enabled (read from env vars)
- Display a "Notifications: Enabled" or "Notifications: Disabled" indicator
- Link to documentation for setup instructions

---

## Consequences

### Positive
- Users are alerted when backups fail
- Supports popular self-hosted notification platforms
- Provider-agnostic design makes adding new providers easy
- Non-blocking implementation doesn't slow down backups
- Environment variable configuration aligns with Docker best practices
- No database migrations needed for notification config
- Secrets stay out of the database (12-factor app compliant)
- Consistent with existing `REQUIRE_AUTH`, `APP_PASSWORD` pattern

### Negative
- Configuration requires container restart to take effect
- No UI for managing notifications (must edit `.env` or Docker Compose)
- Cannot configure different providers per Pi-hole instance (global config only)

### Risks
- **Rate limiting:** Some providers have rate limits. Rapid failures could hit limits.
  - Mitigation: Add cooldown period between notifications for same event type
- **Provider API changes:** External APIs could change
  - Mitigation: Graceful error handling, provider validation on startup
- **Misconfiguration:** Invalid env vars won't be caught until notification is attempted
  - Mitigation: Log warnings on startup for incomplete configs, validate URLs

---

## Alternatives Considered

### 1. Database Storage with UI
Store notification config in database with web UI for management.

**Rejected:** Adds complexity (migrations, forms, UI) for a feature that rarely changes after initial setup. Environment variables are simpler and more aligned with Docker deployment patterns.

### 2. Email Only
Just support email notifications via SMTP.

**Rejected:** Requires SMTP server configuration which is complex. Most self-hosted users prefer webhook-based solutions.

### 3. Apprise Integration
Use the [Apprise](https://github.com/caronc/apprise) library which supports 90+ notification services.

**Considered for future:** Good option if we need to support many more providers. For initial implementation, native support for 5 popular services is cleaner and has fewer dependencies. Could add Apprise as an optional provider later (`NOTIFY_APPRISE_URL`).

### 4. Generic Webhook Only
Just support a single generic webhook endpoint.

**Rejected:** Requires users to set up their own webhook handlers. Provider-specific integrations offer much better UX with proper formatting (embeds, colors, etc.).

---

## Future Enhancements

1. **Notification history** - Log all sent notifications (to file or database)
2. **Rate limiting** - Prevent notification spam during repeated failures
3. **Apprise integration** - Add as optional backend for 90+ services
4. **Email support** - SMTP-based email notifications via env vars
5. **Test command** - Django management command to test notification config
6. **Startup validation** - Validate and test notification providers on container start
