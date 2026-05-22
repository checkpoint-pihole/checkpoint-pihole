"""Telegram notification provider."""

import logging

import requests

from .base import NotificationEvent, NotificationPayload, NotificationProvider

logger = logging.getLogger(__name__)


def _escape_markdown(text: str) -> str:
    """Escape Telegram Markdown special characters.

    Escapes characters that have special meaning in Telegram's Markdown
    mode to prevent formatting issues or injection.
    """
    # Characters that need escaping in Telegram Markdown
    special_chars = ["_", "*", "[", "]", "(", ")", "~", "`", ">", "#", "+", "-", "=", "|", "{", "}", ".", "!"]
    for char in special_chars:
        text = text.replace(char, f"\\{char}")
    return text


class TelegramProvider(NotificationProvider):
    """Telegram bot notification provider."""

    name = "telegram"
    display_name = "Telegram"

    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id

    def send(self, payload: NotificationPayload) -> bool:
        """Send notification via Telegram bot."""
        icon = "\u274c" if "failed" in payload.event.value else "\u2705"

        # Escape user-provided content to prevent Markdown injection
        safe_title = _escape_markdown(payload.title)
        safe_message = _escape_markdown(payload.message)
        safe_name = _escape_markdown(payload.pihole_name)
        safe_timestamp = _escape_markdown(payload.timestamp)

        text = f"{icon} *{safe_title}*\n\n{safe_message}\n\n"
        text += f"\U0001f4cd {_escape_markdown('Pi-hole')}: {safe_name}\n"
        text += f"\U0001f552 Time: {safe_timestamp}"

        if payload.details:
            text += "\n\n"
            for key, value in payload.details.items():
                safe_key = _escape_markdown(str(key))
                safe_value = _escape_markdown(str(value))
                text += f"*{safe_key}:* {safe_value}\n"

        try:
            response = requests.post(
                f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": "MarkdownV2",
                },
                timeout=10,
            )
            return response.status_code == 200
        except requests.RequestException as e:
            logger.error(f"Telegram notification failed: {e}")
            return False

    def validate_config(self) -> tuple[bool, str]:
        """Validate Telegram bot configuration."""
        if not self.bot_token:
            return False, "Bot token is required"
        if not self.chat_id:
            return False, "Chat ID is required"
        return True, ""

    def test_connection(self) -> tuple[bool, str]:
        """Send a test notification to Telegram."""
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
