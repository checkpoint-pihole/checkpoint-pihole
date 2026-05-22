"""Discord notification provider."""

import logging

import requests

from .base import NotificationEvent, NotificationPayload, NotificationProvider

logger = logging.getLogger(__name__)


class DiscordProvider(NotificationProvider):
    """Discord webhook notification provider."""

    name = "discord"
    display_name = "Discord"

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def send(self, payload: NotificationPayload) -> bool:
        """Send notification via Discord webhook."""
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

        try:
            response = requests.post(
                self.webhook_url,
                json={"embeds": [embed]},
                timeout=10,
            )
            return response.status_code == 204
        except requests.RequestException as e:
            logger.error(f"Discord notification failed: {e}")
            return False

    def validate_config(self) -> tuple[bool, str]:
        """Validate Discord webhook URL."""
        if not self.webhook_url:
            return False, "Webhook URL is required"
        if not self.webhook_url.startswith("https://discord.com/api/webhooks/"):
            return False, "Invalid Discord webhook URL"
        return True, ""

    def test_connection(self) -> tuple[bool, str]:
        """Send a test notification to Discord."""
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
