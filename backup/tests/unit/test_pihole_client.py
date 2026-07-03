"""Unit tests for PiholeV6Client."""

import pytest
import responses
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import SSLError, Timeout

from backup.services.pihole_client import PiholeV6Client


class TestPiholeV6ClientInit:
    """Tests for PiholeV6Client initialization."""

    def test_url_normalization_removes_trailing_slash(self):
        """URL trailing slash should be removed."""
        client = PiholeV6Client("https://pihole.local/", "password")
        assert client.base_url == "https://pihole.local"

    def test_url_normalization_preserves_path(self):
        """URL path should be preserved."""
        client = PiholeV6Client("https://pihole.local/admin", "password")
        assert client.base_url == "https://pihole.local/admin"

    def test_verify_ssl_default_false(self):
        """verify_ssl should default to False."""
        client = PiholeV6Client("https://pihole.local", "password")
        assert client.verify_ssl is False

    def test_verify_ssl_can_be_enabled(self):
        """verify_ssl can be set to True."""
        client = PiholeV6Client("https://pihole.local", "password", verify_ssl=True)
        assert client.verify_ssl is True

    def test_session_id_starts_none(self):
        """session_id should start as None."""
        client = PiholeV6Client("https://pihole.local", "password")
        assert client.session_id is None

    def test_password_is_stored(self):
        """Password should be stored."""
        client = PiholeV6Client("https://pihole.local", "mypassword")
        assert client.password == "mypassword"


class TestPiholeV6ClientAuthenticate:
    """Tests for PiholeV6Client.authenticate()."""

    @responses.activate
    def test_authenticate_success_extracts_session_id(self):
        """Successful auth should extract session_id."""
        responses.add(
            responses.POST,
            "https://pihole.local/api/auth",
            json={"session": {"sid": "test-session-123", "validity": 300}},
            status=200,
        )

        client = PiholeV6Client("https://pihole.local", "password")
        result = client.authenticate()

        assert result is True
        assert client.session_id == "test-session-123"

    @responses.activate
    def test_authenticate_missing_session_returns_false(self):
        """Missing session in response should return False."""
        responses.add(
            responses.POST,
            "https://pihole.local/api/auth",
            json={"error": "something else"},
            status=200,
        )

        client = PiholeV6Client("https://pihole.local", "password")
        result = client.authenticate()

        assert result is False
        assert client.session_id is None

    @responses.activate
    def test_authenticate_missing_sid_returns_false(self):
        """Missing sid in session should return False."""
        responses.add(
            responses.POST,
            "https://pihole.local/api/auth",
            json={"session": {"validity": 300}},
            status=200,
        )

        client = PiholeV6Client("https://pihole.local", "password")
        result = client.authenticate()

        assert result is False
        assert client.session_id is None

    @responses.activate
    def test_authenticate_401_raises_value_error(self):
        """401 response should raise ValueError with message about invalid password."""
        responses.add(
            responses.POST,
            "https://pihole.local/api/auth",
            json={"error": "unauthorized"},
            status=401,
        )

        client = PiholeV6Client("https://pihole.local", "password")

        with pytest.raises(ValueError, match="Invalid Pi-hole password"):
            client.authenticate()

    @responses.activate
    def test_authenticate_connection_error_raises_connection_error(self):
        """Connection error should raise ConnectionError."""
        responses.add(
            responses.POST,
            "https://pihole.local/api/auth",
            body=RequestsConnectionError("Connection refused"),
        )

        client = PiholeV6Client("https://pihole.local", "password")

        with pytest.raises(ConnectionError, match="Cannot connect to Pi-hole"):
            client.authenticate()

    @responses.activate
    def test_authenticate_timeout_raises_connection_error(self):
        """Timeout should raise ConnectionError."""
        responses.add(
            responses.POST,
            "https://pihole.local/api/auth",
            body=Timeout("Connection timed out"),
        )

        client = PiholeV6Client("https://pihole.local", "password")

        with pytest.raises(ConnectionError, match="Connection timed out"):
            client.authenticate()

    @responses.activate
    def test_authenticate_ssl_error_raises_connection_error(self):
        """SSL error should raise ConnectionError with helpful message."""
        responses.add(
            responses.POST,
            "https://pihole.local/api/auth",
            body=SSLError("SSL certificate verify failed"),
        )

        client = PiholeV6Client("https://pihole.local", "password")

        with pytest.raises(ConnectionError, match="SSL error"):
            client.authenticate()


class TestPiholeV6ClientTestConnection:
    """Tests for PiholeV6Client.test_connection()."""

    @responses.activate
    def test_test_connection_returns_version_info(self):
        """test_connection should return version info."""
        # Mock auth
        responses.add(
            responses.POST,
            "https://pihole.local/api/auth",
            json={"session": {"sid": "test-session-123", "validity": 300}},
            status=200,
        )
        # Mock version endpoint
        responses.add(
            responses.GET,
            "https://pihole.local/api/info/version",
            json={"version": {"core": {"local": {"version": "v6.0"}}}},
            status=200,
        )

        client = PiholeV6Client("https://pihole.local", "password")
        result = client.test_connection()

        assert result["version"]["core"]["local"]["version"] == "v6.0"

    @responses.activate
    def test_test_connection_retries_on_401(self):
        """test_connection should retry on 401 (session expired)."""
        # Mock initial auth
        responses.add(
            responses.POST,
            "https://pihole.local/api/auth",
            json={"session": {"sid": "session-1", "validity": 300}},
            status=200,
        )
        # Mock version endpoint returning 401 first
        responses.add(
            responses.GET,
            "https://pihole.local/api/info/version",
            status=401,
        )
        # Mock re-auth
        responses.add(
            responses.POST,
            "https://pihole.local/api/auth",
            json={"session": {"sid": "session-2", "validity": 300}},
            status=200,
        )
        # Mock successful version endpoint after re-auth
        responses.add(
            responses.GET,
            "https://pihole.local/api/info/version",
            json={"version": {"core": {"local": {"version": "v6.0"}}}},
            status=200,
        )

        client = PiholeV6Client("https://pihole.local", "password")
        result = client.test_connection()

        assert result["version"]["core"]["local"]["version"] == "v6.0"
        assert client.session_id == "session-2"


class TestPiholeV6ClientDownloadTeleporterBackup:
    """Tests for PiholeV6Client.download_teleporter_backup()."""

    @responses.activate
    def test_download_returns_bytes(self):
        """download_teleporter_backup should return backup bytes."""
        backup_data = b"PK\x03\x04test backup content"

        # Mock auth
        responses.add(
            responses.POST,
            "https://pihole.local/api/auth",
            json={"session": {"sid": "test-session-123", "validity": 300}},
            status=200,
        )
        # Mock teleporter endpoint
        responses.add(
            responses.GET,
            "https://pihole.local/api/teleporter",
            body=backup_data,
            status=200,
            content_type="application/zip",
        )

        client = PiholeV6Client("https://pihole.local", "password")
        result = client.download_teleporter_backup()

        assert result == backup_data

    @responses.activate
    def test_download_includes_session_header(self):
        """download_teleporter_backup should include X-FTL-SID header."""
        # Mock auth
        responses.add(
            responses.POST,
            "https://pihole.local/api/auth",
            json={"session": {"sid": "my-session-id", "validity": 300}},
            status=200,
        )
        # Mock teleporter endpoint (body must be a valid ZIP to pass validation)
        responses.add(
            responses.GET,
            "https://pihole.local/api/teleporter",
            body=b"PK\x03\x04backup",
            status=200,
        )

        client = PiholeV6Client("https://pihole.local", "password")
        client.download_teleporter_backup()

        # Check that request had the session header
        assert responses.calls[1].request.headers.get("X-FTL-SID") == "my-session-id"

    @responses.activate
    def test_download_retries_on_session_expiry(self):
        """download_teleporter_backup should retry on 401."""
        backup_data = b"PK\x03\x04backup data"

        # Mock initial auth
        responses.add(
            responses.POST,
            "https://pihole.local/api/auth",
            json={"session": {"sid": "session-1", "validity": 300}},
            status=200,
        )
        # Mock teleporter endpoint returning 401 first
        responses.add(
            responses.GET,
            "https://pihole.local/api/teleporter",
            status=401,
        )
        # Mock re-auth
        responses.add(
            responses.POST,
            "https://pihole.local/api/auth",
            json={"session": {"sid": "session-2", "validity": 300}},
            status=200,
        )
        # Mock successful teleporter endpoint after re-auth
        responses.add(
            responses.GET,
            "https://pihole.local/api/teleporter",
            body=backup_data,
            status=200,
        )

        client = PiholeV6Client("https://pihole.local", "password")
        result = client.download_teleporter_backup()

        assert result == backup_data
        assert client.session_id == "session-2"

    @responses.activate
    def test_download_handles_octet_stream_content_type(self):
        """download_teleporter_backup should handle octet-stream content type."""
        backup_data = b"PK\x03\x04backup data"

        # Mock auth
        responses.add(
            responses.POST,
            "https://pihole.local/api/auth",
            json={"session": {"sid": "test-session", "validity": 300}},
            status=200,
        )
        # Mock teleporter endpoint with octet-stream
        responses.add(
            responses.GET,
            "https://pihole.local/api/teleporter",
            body=backup_data,
            status=200,
            content_type="application/octet-stream",
        )

        client = PiholeV6Client("https://pihole.local", "password")
        result = client.download_teleporter_backup()

        assert result == backup_data

    @responses.activate
    def test_download_rejects_non_zip_body(self):
        """A 200 response whose body is not a ZIP should raise instead of returning garbage."""
        # Mock auth
        responses.add(
            responses.POST,
            "https://pihole.local/api/auth",
            json={"session": {"sid": "test-session", "validity": 300}},
            status=200,
        )
        # Teleporter returns an HTML error page with a 200 status
        responses.add(
            responses.GET,
            "https://pihole.local/api/teleporter",
            body=b"<html><body>Bad Gateway</body></html>",
            status=200,
            content_type="text/html",
        )

        client = PiholeV6Client("https://pihole.local", "password")
        with pytest.raises(ValueError, match="ZIP"):
            client.download_teleporter_backup()

    @responses.activate
    def test_download_rejects_non_zip_body_on_retry(self):
        """The 401-reauth retry path must also validate the ZIP signature."""
        # Mock initial auth
        responses.add(
            responses.POST,
            "https://pihole.local/api/auth",
            json={"session": {"sid": "session-1", "validity": 300}},
            status=200,
        )
        # First teleporter call 401s
        responses.add(
            responses.GET,
            "https://pihole.local/api/teleporter",
            status=401,
        )
        # Re-auth
        responses.add(
            responses.POST,
            "https://pihole.local/api/auth",
            json={"session": {"sid": "session-2", "validity": 300}},
            status=200,
        )
        # Retried teleporter call returns a non-ZIP 200 body
        responses.add(
            responses.GET,
            "https://pihole.local/api/teleporter",
            body=b"not a zip at all",
            status=200,
        )

        client = PiholeV6Client("https://pihole.local", "password")
        with pytest.raises(ValueError, match="ZIP"):
            client.download_teleporter_backup()


class TestPiholeV6ClientUploadTeleporterBackup:
    """Tests for PiholeV6Client.upload_teleporter_backup()."""

    @responses.activate
    def test_upload_returns_response_dict(self):
        """upload_teleporter_backup should return API response dict."""
        backup_data = b"PK\x03\x04test backup content"

        # Mock auth
        responses.add(
            responses.POST,
            "https://pihole.local/api/auth",
            json={"session": {"sid": "test-session-123", "validity": 300}},
            status=200,
        )
        # Mock teleporter upload endpoint
        responses.add(
            responses.POST,
            "https://pihole.local/api/teleporter",
            json={"status": "success", "imported": {"settings": True, "lists": True}},
            status=200,
        )

        client = PiholeV6Client("https://pihole.local", "password")
        result = client.upload_teleporter_backup(backup_data)

        assert result["status"] == "success"
        assert result["imported"]["settings"] is True

    @responses.activate
    def test_upload_includes_session_header(self):
        """upload_teleporter_backup should include X-FTL-SID header."""
        backup_data = b"PK\x03\x04backup"

        # Mock auth
        responses.add(
            responses.POST,
            "https://pihole.local/api/auth",
            json={"session": {"sid": "my-session-id", "validity": 300}},
            status=200,
        )
        # Mock teleporter upload endpoint
        responses.add(
            responses.POST,
            "https://pihole.local/api/teleporter",
            json={"status": "success"},
            status=200,
        )

        client = PiholeV6Client("https://pihole.local", "password")
        client.upload_teleporter_backup(backup_data)

        # Check that POST request (index 1) had the session header
        assert responses.calls[1].request.headers.get("X-FTL-SID") == "my-session-id"

    @responses.activate
    def test_upload_sends_multipart_form(self):
        """upload_teleporter_backup should send file as multipart form."""
        backup_data = b"PK\x03\x04backup content"

        # Mock auth
        responses.add(
            responses.POST,
            "https://pihole.local/api/auth",
            json={"session": {"sid": "test-session", "validity": 300}},
            status=200,
        )
        # Mock teleporter upload endpoint
        responses.add(
            responses.POST,
            "https://pihole.local/api/teleporter",
            json={"status": "success"},
            status=200,
        )

        client = PiholeV6Client("https://pihole.local", "password")
        client.upload_teleporter_backup(backup_data)

        # Check that the request was multipart
        content_type = responses.calls[1].request.headers.get("Content-Type")
        assert "multipart/form-data" in content_type

    @responses.activate
    def test_upload_retries_on_session_expiry(self):
        """upload_teleporter_backup should retry on 401."""
        backup_data = b"PK\x03\x04backup data"

        # Mock initial auth
        responses.add(
            responses.POST,
            "https://pihole.local/api/auth",
            json={"session": {"sid": "session-1", "validity": 300}},
            status=200,
        )
        # Mock teleporter endpoint returning 401 first
        responses.add(
            responses.POST,
            "https://pihole.local/api/teleporter",
            status=401,
        )
        # Mock re-auth
        responses.add(
            responses.POST,
            "https://pihole.local/api/auth",
            json={"session": {"sid": "session-2", "validity": 300}},
            status=200,
        )
        # Mock successful teleporter endpoint after re-auth
        responses.add(
            responses.POST,
            "https://pihole.local/api/teleporter",
            json={"status": "success"},
            status=200,
        )

        client = PiholeV6Client("https://pihole.local", "password")
        result = client.upload_teleporter_backup(backup_data)

        assert result["status"] == "success"
        assert client.session_id == "session-2"


class TestPiholeV6ClientGetUrl:
    """Tests for PiholeV6Client._get_url()."""

    def test_get_url_joins_endpoint(self):
        """_get_url should properly join base URL and endpoint."""
        client = PiholeV6Client("https://pihole.local", "password")
        url = client._get_url("/api/auth")
        assert url == "https://pihole.local/api/auth"

    def test_get_url_handles_base_with_path(self):
        """_get_url should handle base URL with existing path."""
        client = PiholeV6Client("https://pihole.local/admin", "password")
        url = client._get_url("/api/auth")
        # urljoin replaces the path when endpoint starts with /
        assert "/api/auth" in url


class TestPiholeV6ClientGetHeaders:
    """Tests for PiholeV6Client._get_headers()."""

    def test_get_headers_empty_when_no_session(self):
        """_get_headers should return empty dict when no session."""
        client = PiholeV6Client("https://pihole.local", "password")
        headers = client._get_headers()
        assert headers == {}

    def test_get_headers_includes_session_id(self):
        """_get_headers should include X-FTL-SID when session exists."""
        client = PiholeV6Client("https://pihole.local", "password")
        client.session_id = "my-session-id"
        headers = client._get_headers()
        assert headers == {"X-FTL-SID": "my-session-id"}
