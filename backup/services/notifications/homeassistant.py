"""Home Assistant notification provider."""

import logging

import requests

from .base import NotificationEvent, NotificationPayload, NotificationProvider

logger = logging.getLogger(__name__)


class HomeAssistantProvider(NotificationProvider):
    """Home Assistant notification provider."""

    name = "homeassistant"
    display_name = "Home Assistant"

    def __init__(self, url: str, token: str = "", webhook_id: str = ""):
        self.url = url.rstrip("/")
        self.token = token
        self.webhook_id = webhook_id

    def send(self, payload: NotificationPayload) -> bool:
        """Send notification to Home Assistant."""
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

        try:
            response = requests.post(endpoint, headers=headers, json=data, timeout=10)
            return response.status_code in (200, 201)
        except requests.RequestException as e:
            logger.error(f"Home Assistant notification failed: {e}")
            return False

    def validate_config(self) -> tuple[bool, str]:
        """Validate Home Assistant configuration."""
        if not self.url:
            return False, "Home Assistant URL is required"
        if not self.webhook_id and not self.token:
            return False, "Either webhook ID or long-lived access token is required"
        return True, ""

    def test_connection(self) -> tuple[bool, str]:
        """Send a test notification to Home Assistant."""
        try:
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
