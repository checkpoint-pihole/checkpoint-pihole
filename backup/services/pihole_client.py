"""Pi-hole v6 API client with session-based authentication."""

import logging

import requests

logger = logging.getLogger(__name__)


class PiholeV6Client:
    """Client for interacting with Pi-hole v6 API."""

    def __init__(self, base_url: str, password: str, verify_ssl: bool = False):
        self.base_url = base_url.rstrip("/")
        self.password = password
        self.verify_ssl = verify_ssl
        self.session_id = None
        self._session = requests.Session()

    def close(self):
        """Close the underlying requests session."""
        self._session.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def _get_url(self, endpoint: str) -> str:
        """Build full URL for an endpoint.

        Uses simple string concatenation to preserve base URL path.
        This handles Pi-hole instances behind reverse proxies with path prefixes.
        """
        # self.base_url is already rstrip("/") in __init__
        return self.base_url + endpoint

    def authenticate(self) -> bool:
        """
        Authenticate with Pi-hole and obtain session ID.

        Returns True if authentication succeeded, False otherwise.
        """
        try:
            response = self._session.post(
                self._get_url("/api/auth"), json={"password": self.password}, verify=self.verify_ssl, timeout=30
            )
            response.raise_for_status()
            data = response.json()

            if "session" in data and "sid" in data["session"]:
                self.session_id = data["session"]["sid"]
                logger.info("Successfully authenticated with Pi-hole")
                return True

            logger.error("Authentication response missing session.sid")
            return False

        except requests.exceptions.SSLError as e:
            logger.error(f"SSL error during authentication: {e}")
            raise ConnectionError(f"SSL error: {e}. Try disabling SSL verification.")
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Connection error during authentication: {e}")
            raise ConnectionError(f"Cannot connect to Pi-hole at {self.base_url}")
        except requests.exceptions.Timeout:
            logger.error("Timeout during authentication")
            raise ConnectionError("Connection timed out")
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                raise ValueError("Invalid Pi-hole password")
            logger.error(f"HTTP error during authentication: {e}")
            raise

    def _ensure_authenticated(self):
        """Ensure we have a valid session, re-authenticating if needed."""
        if not self.session_id:
            self.authenticate()

    def _get_headers(self) -> dict:
        """Get headers with session ID."""
        return {"X-FTL-SID": self.session_id} if self.session_id else {}

    def _request_with_reauth(self, method: str, endpoint: str, **kwargs) -> requests.Response:
        """Make an authenticated request, re-authenticating once on a 401.

        Ensures a session exists, sends the request with the session header, and
        on a 401 (expired session) clears the session, re-authenticates, and
        retries exactly once. Raises for any remaining HTTP error status.

        Args:
            method: HTTP method (e.g. "GET", "POST").
            endpoint: API path appended to the base URL.
            **kwargs: Extra arguments forwarded to ``requests`` (e.g. timeout,
                stream, files).

        Returns:
            The successful ``requests.Response``.
        """
        self._ensure_authenticated()
        url = self._get_url(endpoint)

        response = self._session.request(method, url, headers=self._get_headers(), verify=self.verify_ssl, **kwargs)

        if response.status_code == 401:
            # Session expired, re-authenticate and retry once
            logger.info("Session expired, re-authenticating...")
            self.session_id = None
            self.authenticate()
            response = self._session.request(method, url, headers=self._get_headers(), verify=self.verify_ssl, **kwargs)

        response.raise_for_status()
        return response

    def test_connection(self) -> dict:
        """
        Test connection to Pi-hole by authenticating and fetching version info.

        Returns version info dict on success.
        Raises exception on failure.
        """
        # Authenticate up front so a bad password surfaces as the connection result
        self.authenticate()
        response = self._request_with_reauth("GET", "/api/info/version", timeout=30)
        return response.json()

    def download_teleporter_backup(self) -> bytes:
        """
        Download a Teleporter backup from Pi-hole.

        Returns the ZIP file content as bytes.
        """
        response = self._request_with_reauth("GET", "/api/teleporter", timeout=120, stream=True)

        # Verify we got a ZIP file (applies to the retried request too)
        content_type = response.headers.get("Content-Type", "")
        if "zip" not in content_type and "octet-stream" not in content_type:
            logger.warning(f"Unexpected content type: {content_type}")

        content = response.content
        logger.info(f"Downloaded backup: {len(content)} bytes")
        return content

    def upload_teleporter_backup(self, backup_data: bytes) -> dict:
        """
        Upload a Teleporter backup to Pi-hole.

        Args:
            backup_data: ZIP file content as bytes

        Returns:
            API response dict

        Raises:
            Exception on failure
        """
        files = {"file": ("backup.zip", backup_data, "application/zip")}
        response = self._request_with_reauth("POST", "/api/teleporter", files=files, timeout=120)
        return response.json()
