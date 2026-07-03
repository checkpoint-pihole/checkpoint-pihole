"""Unit tests for notification service utilities."""

from unittest.mock import MagicMock, patch

from backup.services.notifications import NotificationEvent
from backup.services.notifications.base import NotificationPayload
from backup.services.notifications.service import (
    NotificationService,
    safe_send_notification,
)
from backup.services.notifications.telegram import TelegramProvider, _escape_markdown


class TestEscapeMarkdown:
    """Tests for _escape_markdown function."""

    def test_escapes_underscore(self):
        """Should escape underscore character."""
        assert _escape_markdown("hello_world") == r"hello\_world"

    def test_escapes_asterisk(self):
        """Should escape asterisk character."""
        assert _escape_markdown("*bold*") == r"\*bold\*"

    def test_escapes_brackets(self):
        """Should escape square brackets."""
        assert _escape_markdown("[link]") == r"\[link\]"

    def test_escapes_parentheses(self):
        """Should escape parentheses."""
        assert _escape_markdown("(text)") == r"\(text\)"

    def test_escapes_hyphen(self):
        """Should escape hyphen character."""
        assert _escape_markdown("Pi-hole") == r"Pi\-hole"

    def test_escapes_dot(self):
        """Should escape dot character."""
        assert _escape_markdown("file.txt") == r"file\.txt"

    def test_escapes_exclamation(self):
        """Should escape exclamation mark."""
        assert _escape_markdown("Hello!") == r"Hello\!"

    def test_normal_text_unchanged(self):
        """Should not modify text without special characters."""
        assert _escape_markdown("hello world") == "hello world"

    def test_empty_string(self):
        """Should handle empty string."""
        assert _escape_markdown("") == ""

    def test_multiple_special_characters(self):
        """Should escape multiple special characters in one string."""
        result = _escape_markdown("Error: [file.txt] failed!")
        assert result == r"Error: \[file\.txt\] failed\!"

    def test_all_special_characters(self):
        """Should escape all Telegram MarkdownV2 special characters."""
        special = "_*[]()~`>#+-=|{}.!"
        result = _escape_markdown(special)
        # Each character should be preceded by backslash
        for char in special:
            assert f"\\{char}" in result

    def test_consecutive_special_characters(self):
        """Should handle consecutive special characters."""
        assert _escape_markdown("***") == r"\*\*\*"


class TestTelegramProviderSend:
    """Tests for TelegramProvider.send()."""

    def _payload(self):
        """Payload with MarkdownV2 special characters in every field."""
        return NotificationPayload(
            event=NotificationEvent.BACKUP_FAILED,
            title="Backup_failed!",
            message="Error: [disk] full (100%).",
            pihole_name="pi-hole.local",
            timestamp="2026-07-02 10:30:00",
            details={"Reason": "out-of-space*"},
        )

    def test_send_escapes_markdownv2_and_posts(self):
        """send() should escape special chars, set MarkdownV2 + chat_id, and return True on 200."""
        provider = TelegramProvider(bot_token="BOT123", chat_id="CHAT456")

        with patch("backup.services.notifications.telegram.requests.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200)
            result = provider.send(self._payload())

        assert result is True
        mock_post.assert_called_once()

        body = mock_post.call_args.kwargs["json"]
        assert body["parse_mode"] == "MarkdownV2"
        assert body["chat_id"] == "CHAT456"

        text = body["text"]
        # Escaped forms are present...
        assert r"Backup\_failed\!" in text
        assert r"\[disk\]" in text
        assert r"\(100%\)" in text
        assert r"pi\-hole\.local" in text
        assert r"2026\-07\-02" in text
        assert r"out\-of\-space\*" in text
        # ...and the raw (unescaped) forms are NOT, proving escaping happened
        assert "Backup_failed!" not in text
        assert "[disk]" not in text
        assert "pi-hole.local" not in text

    def test_send_returns_false_on_non_200(self):
        """send() should return False when Telegram responds with a non-200 status."""
        provider = TelegramProvider(bot_token="BOT123", chat_id="CHAT456")

        with patch("backup.services.notifications.telegram.requests.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=500)
            result = provider.send(self._payload())

        assert result is False


class TestSafeSendNotification:
    """Tests for safe_send_notification function."""

    def test_sends_notification_successfully(self):
        """Should send notification when service works."""
        mock_service = MagicMock(spec=NotificationService)

        safe_send_notification(
            mock_service,
            "Test Pi-hole",
            NotificationEvent.BACKUP_SUCCESS,
            "Test Title",
            "Test message",
        )

        mock_service.send_notification.assert_called_once()
        payload = mock_service.send_notification.call_args[0][0]
        assert payload.title == "Test Title"
        assert payload.message == "Test message"
        assert payload.pihole_name == "Test Pi-hole"
        assert payload.event == NotificationEvent.BACKUP_SUCCESS

    def test_includes_details_when_provided(self):
        """Should include details in payload when provided."""
        mock_service = MagicMock(spec=NotificationService)

        safe_send_notification(
            mock_service,
            "Test Pi-hole",
            NotificationEvent.BACKUP_FAILED,
            "Backup Failed",
            "Error occurred",
            details={"Error": "Connection timeout"},
        )

        payload = mock_service.send_notification.call_args[0][0]
        assert payload.details == {"Error": "Connection timeout"}

    def test_catches_exception_without_propagating(self):
        """Should catch exceptions and not propagate them."""
        mock_service = MagicMock(spec=NotificationService)
        mock_service.send_notification.side_effect = Exception("Network error")

        # Should not raise
        safe_send_notification(
            mock_service,
            "Test Pi-hole",
            NotificationEvent.BACKUP_SUCCESS,
            "Test",
            "Test",
        )

    def test_logs_warning_on_failure(self):
        """Should log warning when notification fails."""
        mock_service = MagicMock(spec=NotificationService)
        mock_service.send_notification.side_effect = Exception("Network error")

        with patch("backup.services.notifications.service.logger") as mock_logger:
            safe_send_notification(
                mock_service,
                "Test Pi-hole",
                NotificationEvent.BACKUP_SUCCESS,
                "Test",
                "Test",
            )

            mock_logger.warning.assert_called_once()
            assert "Failed to send notification" in str(mock_logger.warning.call_args)

    def test_includes_timestamp(self):
        """Should include timestamp in payload."""
        mock_service = MagicMock(spec=NotificationService)

        safe_send_notification(
            mock_service,
            "Test Pi-hole",
            NotificationEvent.BACKUP_SUCCESS,
            "Test",
            "Test",
        )

        payload = mock_service.send_notification.call_args[0][0]
        assert payload.timestamp is not None
        # Timestamp should be in expected format (YYYY-MM-DD HH:MM:SS)
        assert len(payload.timestamp) == 19
