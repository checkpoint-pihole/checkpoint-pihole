"""Unit tests for individual notification providers.

Covers Home Assistant (Finding 12) and the Discord / Slack / Pushbullet
providers (Finding 14). All HTTP calls are mocked at ``requests.post`` so we
assert the exact endpoint, payload shape, headers, and success status code each
provider treats as "sent".
"""

from unittest.mock import MagicMock, patch

import pytest
import requests

from backup.services.notifications.base import NotificationEvent, NotificationPayload
from backup.services.notifications.discord import DiscordProvider
from backup.services.notifications.homeassistant import HomeAssistantProvider
from backup.services.notifications.pushbullet import PushbulletProvider
from backup.services.notifications.slack import SlackProvider


def _payload(event=NotificationEvent.BACKUP_SUCCESS, details=None):
    return NotificationPayload(
        event=event,
        title="Test Title",
        message="Test message",
        pihole_name="Primary",
        timestamp="2026-07-02 10:00:00",
        details=details,
    )


def _mock_response(status_code):
    response = MagicMock()
    response.status_code = status_code
    return response


# ---------------------------------------------------------------------------
# Finding 12 — Home Assistant
# ---------------------------------------------------------------------------


class TestHomeAssistantSend:
    def test_webhook_posts_to_webhook_endpoint_without_auth(self):
        provider = HomeAssistantProvider(url="https://ha.local", webhook_id="hook123")
        with patch("requests.post", return_value=_mock_response(200)) as mock_post:
            result = provider.send(_payload())

        assert result is True
        args, kwargs = mock_post.call_args
        assert args[0] == "https://ha.local/api/webhook/hook123"
        # Webhook method uses no auth header.
        assert kwargs["headers"] == {}
        assert "Authorization" not in kwargs["headers"]

    def test_token_posts_to_events_endpoint_with_bearer_header(self):
        provider = HomeAssistantProvider(url="https://ha.local", token="tok-abc")
        with patch("requests.post", return_value=_mock_response(200)) as mock_post:
            result = provider.send(_payload())

        assert result is True
        args, kwargs = mock_post.call_args
        assert args[0] == "https://ha.local/api/events/checkpoint_pihole_notification"
        assert kwargs["headers"]["Authorization"] == "Bearer tok-abc"

    def test_payload_shape(self):
        provider = HomeAssistantProvider(url="https://ha.local", webhook_id="hook123")
        with patch("requests.post", return_value=_mock_response(200)) as mock_post:
            provider.send(_payload(details={"Error": "boom"}))

        data = mock_post.call_args.kwargs["json"]
        assert data["event"] == "backup_success"
        assert data["title"] == "Test Title"
        assert data["message"] == "Test message"
        assert data["pihole_name"] == "Primary"
        assert data["timestamp"] == "2026-07-02 10:00:00"
        assert data["details"] == {"Error": "boom"}

    def test_trailing_slash_stripped_from_url(self):
        provider = HomeAssistantProvider(url="https://ha.local/", webhook_id="hook123")
        with patch("requests.post", return_value=_mock_response(200)) as mock_post:
            provider.send(_payload())
        assert mock_post.call_args.args[0] == "https://ha.local/api/webhook/hook123"

    @pytest.mark.parametrize("status_code", [200, 201])
    def test_success_status_codes_return_true(self, status_code):
        provider = HomeAssistantProvider(url="https://ha.local", token="tok")
        with patch("requests.post", return_value=_mock_response(status_code)):
            assert provider.send(_payload()) is True

    @pytest.mark.parametrize("status_code", [400, 401, 404, 500])
    def test_error_status_codes_return_false(self, status_code):
        provider = HomeAssistantProvider(url="https://ha.local", token="tok")
        with patch("requests.post", return_value=_mock_response(status_code)):
            assert provider.send(_payload()) is False

    def test_request_exception_returns_false(self):
        provider = HomeAssistantProvider(url="https://ha.local", token="tok")
        with patch("requests.post", side_effect=requests.RequestException("boom")):
            assert provider.send(_payload()) is False


class TestHomeAssistantValidateConfig:
    def test_valid_with_token_only(self):
        provider = HomeAssistantProvider(url="https://ha.local", token="tok")
        assert provider.validate_config() == (True, "")

    def test_valid_with_webhook_only(self):
        provider = HomeAssistantProvider(url="https://ha.local", webhook_id="hook")
        assert provider.validate_config() == (True, "")

    def test_invalid_with_neither_token_nor_webhook(self):
        provider = HomeAssistantProvider(url="https://ha.local")
        valid, message = provider.validate_config()
        assert valid is False
        assert "webhook" in message.lower() or "token" in message.lower()

    def test_invalid_without_url(self):
        provider = HomeAssistantProvider(url="", token="tok")
        valid, message = provider.validate_config()
        assert valid is False
        assert "url" in message.lower()


# ---------------------------------------------------------------------------
# Finding 14 — Discord
# ---------------------------------------------------------------------------


class TestDiscordSend:
    def test_posts_embed_to_webhook_url(self):
        provider = DiscordProvider(webhook_url="https://discord.com/api/webhooks/1/abc")
        with patch("requests.post", return_value=_mock_response(204)) as mock_post:
            result = provider.send(_payload())

        assert result is True
        assert mock_post.call_args.args[0] == "https://discord.com/api/webhooks/1/abc"
        body = mock_post.call_args.kwargs["json"]
        assert "embeds" in body
        embed = body["embeds"][0]
        assert embed["title"] == "Test Title"
        assert embed["description"] == "Test message"
        assert embed["footer"]["text"] == "Checkpoint Pi-hole"
        field_names = {f["name"] for f in embed["fields"]}
        assert {"Pi-hole", "Time"} <= field_names

    def test_success_color_for_success_event(self):
        provider = DiscordProvider(webhook_url="https://discord.com/api/webhooks/1/abc")
        with patch("requests.post", return_value=_mock_response(204)) as mock_post:
            provider.send(_payload(event=NotificationEvent.BACKUP_SUCCESS))
        assert mock_post.call_args.kwargs["json"]["embeds"][0]["color"] == 0x00FF00

    def test_failure_color_for_failed_event(self):
        provider = DiscordProvider(webhook_url="https://discord.com/api/webhooks/1/abc")
        with patch("requests.post", return_value=_mock_response(204)) as mock_post:
            provider.send(_payload(event=NotificationEvent.BACKUP_FAILED))
        assert mock_post.call_args.kwargs["json"]["embeds"][0]["color"] == 0xFF0000

    def test_only_204_counts_as_success(self):
        provider = DiscordProvider(webhook_url="https://discord.com/api/webhooks/1/abc")
        with patch("requests.post", return_value=_mock_response(204)):
            assert provider.send(_payload()) is True
        # Discord returns 204 on success; 200 is treated as failure.
        with patch("requests.post", return_value=_mock_response(200)):
            assert provider.send(_payload()) is False

    def test_request_exception_returns_false(self):
        provider = DiscordProvider(webhook_url="https://discord.com/api/webhooks/1/abc")
        with patch("requests.post", side_effect=requests.RequestException("boom")):
            assert provider.send(_payload()) is False


class TestDiscordValidateConfig:
    def test_empty_url_invalid(self):
        valid, message = DiscordProvider(webhook_url="").validate_config()
        assert valid is False
        assert "required" in message.lower()

    def test_wrong_prefix_invalid(self):
        valid, message = DiscordProvider(webhook_url="https://example.com/hook").validate_config()
        assert valid is False
        assert "invalid" in message.lower()

    def test_valid_discord_url(self):
        provider = DiscordProvider(webhook_url="https://discord.com/api/webhooks/1/abc")
        assert provider.validate_config() == (True, "")


# ---------------------------------------------------------------------------
# Finding 14 — Slack
# ---------------------------------------------------------------------------


class TestSlackSend:
    def test_posts_attachment_blocks_to_webhook_url(self):
        provider = SlackProvider(webhook_url="https://hooks.slack.com/services/T/B/x")
        with patch("requests.post", return_value=_mock_response(200)) as mock_post:
            result = provider.send(_payload())

        assert result is True
        assert mock_post.call_args.args[0] == "https://hooks.slack.com/services/T/B/x"
        body = mock_post.call_args.kwargs["json"]
        attachment = body["attachments"][0]
        assert attachment["color"] == "good"
        header_block = attachment["blocks"][0]
        assert header_block["type"] == "header"
        assert header_block["text"]["text"] == "Test Title"

    def test_failure_uses_danger_color(self):
        provider = SlackProvider(webhook_url="https://hooks.slack.com/services/T/B/x")
        with patch("requests.post", return_value=_mock_response(200)) as mock_post:
            provider.send(_payload(event=NotificationEvent.BACKUP_FAILED))
        assert mock_post.call_args.kwargs["json"]["attachments"][0]["color"] == "danger"

    def test_only_200_counts_as_success(self):
        provider = SlackProvider(webhook_url="https://hooks.slack.com/services/T/B/x")
        with patch("requests.post", return_value=_mock_response(200)):
            assert provider.send(_payload()) is True
        with patch("requests.post", return_value=_mock_response(204)):
            assert provider.send(_payload()) is False

    def test_request_exception_returns_false(self):
        provider = SlackProvider(webhook_url="https://hooks.slack.com/services/T/B/x")
        with patch("requests.post", side_effect=requests.RequestException("boom")):
            assert provider.send(_payload()) is False


class TestSlackValidateConfig:
    def test_empty_url_invalid(self):
        valid, message = SlackProvider(webhook_url="").validate_config()
        assert valid is False
        assert "required" in message.lower()

    def test_wrong_prefix_invalid(self):
        valid, message = SlackProvider(webhook_url="https://example.com/hook").validate_config()
        assert valid is False
        assert "invalid" in message.lower()

    def test_valid_slack_url(self):
        provider = SlackProvider(webhook_url="https://hooks.slack.com/services/T/B/x")
        assert provider.validate_config() == (True, "")


# ---------------------------------------------------------------------------
# Finding 14 — Pushbullet
# ---------------------------------------------------------------------------


class TestPushbulletSend:
    def test_posts_note_to_pushes_endpoint_with_access_token(self):
        provider = PushbulletProvider(api_key="key-123")
        with patch("requests.post", return_value=_mock_response(200)) as mock_post:
            result = provider.send(_payload())

        assert result is True
        assert mock_post.call_args.args[0] == "https://api.pushbullet.com/v2/pushes"
        assert mock_post.call_args.kwargs["headers"] == {"Access-Token": "key-123"}
        body = mock_post.call_args.kwargs["json"]
        assert body["type"] == "note"
        assert body["title"] == "Test Title"
        assert "Test message" in body["body"]
        assert "Primary" in body["body"]

    def test_only_200_counts_as_success(self):
        provider = PushbulletProvider(api_key="key-123")
        with patch("requests.post", return_value=_mock_response(200)):
            assert provider.send(_payload()) is True
        with patch("requests.post", return_value=_mock_response(204)):
            assert provider.send(_payload()) is False

    def test_request_exception_returns_false(self):
        provider = PushbulletProvider(api_key="key-123")
        with patch("requests.post", side_effect=requests.RequestException("boom")):
            assert provider.send(_payload()) is False


class TestPushbulletValidateConfig:
    def test_empty_key_invalid(self):
        valid, message = PushbulletProvider(api_key="").validate_config()
        assert valid is False
        assert "required" in message.lower()

    def test_valid_key(self):
        assert PushbulletProvider(api_key="key-123").validate_config() == (True, "")
