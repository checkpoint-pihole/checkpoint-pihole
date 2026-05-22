"""Pushbullet notification provider."""

import logging

import requests

from .base import NotificationEvent, NotificationPayload, NotificationProvider

logger = logging.getLogger(__name__)


class PushbulletProvider(NotificationProvider):
    """Pushbullet notification provider."""

    name = "pushbullet"
    display_name = "Pushbullet"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def send(self, payload: NotificationPayload) -> bool:
        """Send notification via Pushbullet."""
        body = f"{payload.message}\n\nPi-hole: {payload.pihole_name}\nTime: {payload.timestamp}"

        if payload.details:
            body += "\n"
            for key, value in payload.details.items():
                body += f"\n{key}: {value}"

        try:
            response = requests.post(
                "https://api.pushbullet.com/v2/pushes",
                headers={"Access-Token": self.api_key},
                json={
                    "type": "note",
                    "title": payload.title,
                    "body": body,
                },
                timeout=10,
            )
            return response.status_code == 200
        except requests.RequestException as e:
            logger.error(f"Pushbullet notification failed: {e}")
            return False

    def validate_config(self) -> tuple[bool, str]:
        """Validate Pushbullet API key."""
        if not self.api_key:
            return False, "API key is required"
        return True, ""

    def test_connection(self) -> tuple[bool, str]:
        """Send a test notification to Pushbullet."""
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
