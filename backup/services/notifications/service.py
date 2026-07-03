"""Notification service for orchestrating notifications across providers."""

import atexit
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from django.utils import timezone

from .base import NotificationEvent, NotificationPayload, NotificationProvider
from .config import get_notification_settings
from .discord import DiscordProvider
from .homeassistant import HomeAssistantProvider
from .pushbullet import PushbulletProvider
from .slack import SlackProvider
from .telegram import TelegramProvider

logger = logging.getLogger(__name__)

PROVIDERS: dict[str, type[NotificationProvider]] = {
    "discord": DiscordProvider,
    "slack": SlackProvider,
    "telegram": TelegramProvider,
    "pushbullet": PushbulletProvider,
    "homeassistant": HomeAssistantProvider,
}


class NotificationService:
    """Manages sending notifications across multiple providers."""

    def __init__(self):
        self._executor: ThreadPoolExecutor | None = None
        self._executor_lock = threading.Lock()
        self.settings = get_notification_settings()
        self._shutdown_registered = False

    @property
    def executor(self) -> ThreadPoolExecutor:
        """Lazily create executor on first use (thread-safe)."""
        # Fast path: already created
        if self._executor is not None:
            return self._executor

        # Slow path: create under lock with double-check
        with self._executor_lock:
            if self._executor is None:
                self._executor = ThreadPoolExecutor(max_workers=5)
                if not self._shutdown_registered:
                    atexit.register(self._shutdown)
                    self._shutdown_registered = True
            return self._executor

    def _shutdown(self):
        """Gracefully shutdown the executor."""
        if self._executor is not None:
            self._executor.shutdown(wait=True, cancel_futures=False)
            self._executor = None

    def send_notification(self, payload: NotificationPayload) -> None:
        """
        Send notification to all configured providers.
        Runs asynchronously to not block the main operation.
        """
        if not self.settings.should_notify(payload.event.value):
            logger.debug(f"Notifications disabled for event: {payload.event.value}")
            return

        for config in self.settings.providers:
            provider_name = config.get("provider")
            if provider_name not in PROVIDERS:
                logger.warning(f"Unknown notification provider: {provider_name}")
                continue

            # Submit to thread pool for async execution
            self.executor.submit(self._send_to_provider, provider_name, config, payload)

    def _send_to_provider(self, provider_name: str, config: dict, payload: NotificationPayload) -> None:
        """Send notification to a single provider."""
        try:
            provider = self._create_provider(provider_name, config)
            if provider is None:
                return

            success = provider.send(payload)
            if success:
                logger.info(f"Notification sent via {provider_name}")
            else:
                logger.warning(f"Notification to {provider_name} returned failure status")
        except Exception as e:
            logger.exception(f"Failed to send notification via {provider_name}: {e}")

    def _create_provider(self, provider_name: str, config: dict) -> NotificationProvider | None:
        """Create provider instance from config."""
        try:
            if provider_name == "discord":
                return DiscordProvider(webhook_url=config["webhook_url"])
            elif provider_name == "slack":
                return SlackProvider(webhook_url=config["webhook_url"])
            elif provider_name == "telegram":
                return TelegramProvider(bot_token=config["bot_token"], chat_id=config["chat_id"])
            elif provider_name == "pushbullet":
                return PushbulletProvider(api_key=config["api_key"])
            elif provider_name == "homeassistant":
                return HomeAssistantProvider(
                    url=config["url"],
                    token=config.get("token", ""),
                    webhook_id=config.get("webhook_id", ""),
                )
            else:
                logger.error(f"Unknown provider: {provider_name}")
                return None
        except KeyError as e:
            logger.error(f"Missing config key for {provider_name}: {e}")
            return None

    def get_enabled_providers(self) -> list[str]:
        """Get list of enabled provider display names."""
        return self.settings.get_enabled_provider_names()

    def is_enabled(self) -> bool:
        """Check if any notification providers are configured."""
        return bool(self.settings.providers)


# Singleton instance (thread-safe)
_service: NotificationService | None = None
_service_lock = threading.Lock()


def get_notification_service() -> NotificationService:
    """Get notification service (cached singleton, thread-safe)."""
    global _service

    # Fast path: already initialized
    if _service is not None:
        return _service

    # Slow path: need to initialize with lock
    with _service_lock:
        # Double-check after acquiring lock
        if _service is None:
            _service = NotificationService()
        return _service


def safe_send_notification(
    service: NotificationService,
    pihole_name: str,
    event: NotificationEvent,
    title: str,
    message: str,
    details: dict | None = None,
) -> None:
    """Send notification, catching any errors to prevent operation failure.

    This is a helper function that wraps notification sending with error handling,
    ensuring that notification failures don't affect the primary operation
    (backup creation, restore, etc.).

    Args:
        service: The notification service instance
        pihole_name: Name of the Pi-hole instance
        event: The notification event type
        title: Notification title
        message: Notification message body
        details: Optional additional details dict
    """
    try:
        payload = NotificationPayload(
            event=event,
            title=title,
            message=message,
            pihole_name=pihole_name,
            timestamp=timezone.now().strftime("%Y-%m-%d %H:%M:%S"),
            details=details,
        )
        service.send_notification(payload)
    except Exception as e:
        logger.warning(f"Failed to send notification: {e}")
