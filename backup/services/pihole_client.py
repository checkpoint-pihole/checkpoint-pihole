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

    def test_connection(self) -> dict:
        """
        Test connection to Pi-hole by authenticating and fetching version info.

        Returns version info dict on success.
        Raises exception on failure.
        """
        self.authenticate()

        try:
            response = self._session.get(
                self._get_url("/api/info/version"), headers=self._get_headers(), verify=self.verify_ssl, timeout=30
            )
            response.raise_for_status()
            return response.json()

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                # Session expired, try re-auth
                self.session_id = None
                self.authenticate()
                response = self._session.get(
                    self._get_url("/api/info/version"), headers=self._get_headers(), verify=self.verify_ssl, timeout=30
                )
                response.raise_for_status()
                return response.json()
            raise

    @staticmethod
    def _validate_zip_content(content: bytes) -> None:
        """Ensure the downloaded body is a real ZIP (Teleporter export).

        Pi-hole returns a ZIP archive, but a reverse proxy or an error page can
        return HTML/JSON with a 200 status. Storing that as a "success" backup
        would silently corrupt the backup set, so reject anything that does not
        start with the ZIP local-file-header magic bytes.
        """
        if not content.startswith(b"PK\x03\x04"):
            raise ValueError(
                "Teleporter response was not a valid ZIP archive "
                "(missing ZIP signature); refusing to store corrupt backup"
            )

    def download_teleporter_backup(self) -> bytes:
        """
        Download a Teleporter backup from Pi-hole.

        Returns the ZIP file content as bytes.
        """
        self._ensure_authenticated()

        try:
            response = self._session.get(
                self._get_url("/api/teleporter"),
                headers=self._get_headers(),
                verify=self.verify_ssl,
                timeout=120,
                stream=True,
            )
            response.raise_for_status()

            # Verify we got a ZIP file
            content_type = response.headers.get("Content-Type", "")
            if "zip" not in content_type and "octet-stream" not in content_type:
                logger.warning(f"Unexpected content type: {content_type}")

            content = response.content
            self._validate_zip_content(content)
            logger.info(f"Downloaded backup: {len(content)} bytes")
            return content

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                # Session expired, try re-auth and retry
                logger.info("Session expired, re-authenticating...")
                self.session_id = None
                self.authenticate()
                response = self._session.get(
                    self._get_url("/api/teleporter"),
                    headers=self._get_headers(),
                    verify=self.verify_ssl,
                    timeout=120,
                    stream=True,
                )
                response.raise_for_status()
                content = response.content
                self._validate_zip_content(content)
                return content
            raise

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
        self._ensure_authenticated()

        try:
            files = {"file": ("backup.zip", backup_data, "application/zip")}
            response = self._session.post(
                self._get_url("/api/teleporter"),
                headers=self._get_headers(),
                files=files,
                verify=self.verify_ssl,
                timeout=120,
            )
            response.raise_for_status()
            return response.json()

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                # Session expired, try re-auth and retry
                logger.info("Session expired, re-authenticating...")
                self.session_id = None
                self.authenticate()
                files = {"file": ("backup.zip", backup_data, "application/zip")}
                response = self._session.post(
                    self._get_url("/api/teleporter"),
                    headers=self._get_headers(),
                    files=files,
                    verify=self.verify_ssl,
                    timeout=120,
                )
                response.raise_for_status()
                return response.json()
            raise
