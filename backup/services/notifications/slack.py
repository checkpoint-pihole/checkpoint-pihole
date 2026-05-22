"""Slack notification provider."""

import logging

import requests

from .base import NotificationEvent, NotificationPayload, NotificationProvider

logger = logging.getLogger(__name__)


class SlackProvider(NotificationProvider):
    """Slack webhook notification provider."""

    name = "slack"
    display_name = "Slack"

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def send(self, payload: NotificationPayload) -> bool:
        """Send notification via Slack webhook."""
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

        # Add details if present
        if payload.details:
            details_text = "\n".join(f"*{k}:* {v}" for k, v in payload.details.items())
            blocks["attachments"][0]["blocks"].append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": details_text},
                }
            )

        try:
            response = requests.post(self.webhook_url, json=blocks, timeout=10)
            return response.status_code == 200
        except requests.RequestException as e:
            logger.error(f"Slack notification failed: {e}")
            return False

    def validate_config(self) -> tuple[bool, str]:
        """Validate Slack webhook URL."""
        if not self.webhook_url:
            return False, "Webhook URL is required"
        if not self.webhook_url.startswith("https://hooks.slack.com/"):
            return False, "Invalid Slack webhook URL"
        return True, ""

    def test_connection(self) -> tuple[bool, str]:
        """Send a test notification to Slack."""
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
