"""Tests for backup API endpoints."""

from unittest.mock import MagicMock, patch

import pytest
from django.urls import reverse

from backup.tests.factories import BackupRecordFactory


@pytest.mark.django_db
class TestTestConnectionEndpoint:
    """Tests for test_connection API endpoint."""

    def test_success_returns_version(self, client, pihole_config, auth_disabled_settings):
        """Successful test connection should return version info."""
        url = reverse("test_connection", args=[pihole_config.id])

        with patch("backup.views.PiholeV6Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.test_connection.return_value = {"version": {"core": {"local": {"version": "v6.0"}}}}
            mock_client_class.return_value = mock_client

            response = client.post(url)

        assert response.status_code == 200
        response_data = response.json()
        assert response_data["success"] is True
        assert response_data["version"] == "v6.0"

        # Verify client was created with env credentials
        mock_client_class.assert_called_once_with(
            base_url="https://pihole.local",
            password="testpassword123",
            verify_ssl=False,
        )

    def test_requires_env_credentials(self, client, pihole_config, auth_disabled_settings, monkeypatch):
        """Should require env credentials for the config's prefix."""
        url = reverse("test_connection", args=[pihole_config.id])

        monkeypatch.delenv("PIHOLE_PRIMARY_PASSWORD", raising=False)

        response = client.post(url)
        assert response.json()["success"] is False
        assert "PIHOLE_PRIMARY_PASSWORD" in response.json()["error"]

    def test_returns_auth_error_on_401(self, client, pihole_config, auth_disabled_settings):
        """Should return auth error on 401 response."""
        url = reverse("test_connection", args=[pihole_config.id])

        with patch("backup.views.PiholeV6Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.test_connection.side_effect = ValueError("Invalid Pi-hole password")
            mock_client_class.return_value = mock_client

            response = client.post(url)

        assert response.status_code == 200
        response_data = response.json()
        assert response_data["success"] is False
        assert "Invalid" in response_data["error"] or "password" in response_data["error"].lower()

    def test_only_accepts_post(self, client, pihole_config, auth_disabled_settings):
        """Should only accept POST requests."""
        url = reverse("test_connection", args=[pihole_config.id])

        response = client.get(url)
        assert response.status_code == 405

    def test_handles_connection_error(self, client, pihole_config, auth_disabled_settings):
        """Should handle connection errors gracefully."""
        url = reverse("test_connection", args=[pihole_config.id])

        with patch("backup.views.PiholeV6Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.test_connection.side_effect = ConnectionError("Cannot connect")
            mock_client_class.return_value = mock_client

            response = client.post(url)

        assert response.status_code == 200
        response_data = response.json()
        assert response_data["success"] is False
        assert "connect" in response_data["error"].lower()

    def test_returns_404_for_nonexistent_config(self, client, auth_disabled_settings):
        """Should return 404 for non-existent config."""
        url = reverse("test_connection", args=[99999])
        response = client.post(url)
        assert response.status_code == 404


@pytest.mark.django_db
class TestCreateBackupEndpoint:
    """Tests for create_backup API endpoint."""

    def test_returns_404_for_nonexistent_config(self, client, auth_disabled_settings):
        """Should return 404 for non-existent config."""
        url = reverse("create_backup", args=[99999])
        response = client.post(url)
        assert response.status_code == 404

    def test_success_returns_record_info(
        self, client, pihole_config, temp_backup_dir, auth_disabled_settings, sample_backup_data
    ):
        """Successful backup should return record info."""
        url = reverse("create_backup", args=[pihole_config.id])

        with patch("backup.views.BackupService") as mock_service_class:
            mock_service = MagicMock()
            mock_record = MagicMock()
            mock_record.id = 1
            mock_record.filename = "test_backup.zip"
            mock_record.file_size = 1024
            mock_record.status = "success"
            mock_record.is_manual = True
            mock_record.created_at.isoformat.return_value = "2024-01-15T10:30:00"
            mock_record.created_at.strftime.return_value = "Jan 15, 2024 10:30"
            mock_service.create_backup.return_value = mock_record
            mock_service_class.return_value = mock_service

            response = client.post(url)

        assert response.status_code == 200
        response_data = response.json()
        assert response_data["success"] is True
        assert "backup" in response_data
        assert response_data["backup"]["filename"] == "test_backup.zip"

    def test_returns_error_on_failure(self, client, pihole_config, temp_backup_dir, auth_disabled_settings):
        """Should return error on backup failure."""
        url = reverse("create_backup", args=[pihole_config.id])

        with patch("backup.views.BackupService") as mock_service_class:
            mock_service = MagicMock()
            mock_service.create_backup.side_effect = ConnectionError("Pi-hole unreachable")
            mock_service_class.return_value = mock_service

            response = client.post(url)

        assert response.status_code == 200
        response_data = response.json()
        assert response_data["success"] is False
        assert "error" in response_data

    def test_only_accepts_post(self, client, pihole_config, auth_disabled_settings):
        """Should only accept POST requests."""
        url = reverse("create_backup", args=[pihole_config.id])

        response = client.get(url)
        assert response.status_code == 405


@pytest.mark.django_db
class TestDeleteBackupEndpoint:
    """Tests for delete_backup API endpoint."""

    def test_success_removes_backup(
        self, client, pihole_config, backup_record, temp_backup_dir, auth_disabled_settings
    ):
        """Successful delete should remove backup."""
        url = reverse("delete_backup", args=[backup_record.id])

        with patch("backup.views.BackupService") as mock_service_class:
            mock_service = MagicMock()
            mock_service.delete_backup.return_value = True
            mock_service_class.return_value = mock_service

            response = client.post(url)

        assert response.status_code == 200
        response_data = response.json()
        assert response_data["success"] is True

    def test_404_for_nonexistent(self, client, auth_disabled_settings):
        """Should return 404 for non-existent backup."""
        url = reverse("delete_backup", args=[99999])
        response = client.post(url)
        assert response.status_code == 404

    def test_404_is_json_not_html(self, client, auth_disabled_settings):
        """A not-found delete should return a JSON 404 (not Django's HTML page)."""
        url = reverse("delete_backup", args=[99999])
        response = client.post(url)
        assert response.status_code == 404
        assert response["Content-Type"] == "application/json"
        assert response.json()["success"] is False

    def test_only_accepts_post(self, client, backup_record, auth_disabled_settings):
        """Should only accept POST requests."""
        url = reverse("delete_backup", args=[backup_record.id])
        response = client.get(url)
        assert response.status_code == 405


@pytest.mark.django_db
class TestRestoreBackupEndpoint:
    """Tests for restore_backup API endpoint."""

    def test_success_returns_message(
        self, client, pihole_config, backup_record, temp_backup_dir, auth_disabled_settings
    ):
        """Successful restore should return success message."""
        url = reverse("restore_backup", args=[backup_record.id])

        with patch("backup.views.RestoreService") as mock_service_class:
            mock_service = MagicMock()
            mock_service.restore_backup.return_value = {"status": "success"}
            mock_service_class.return_value = mock_service

            response = client.post(url)

        assert response.status_code == 200
        response_data = response.json()
        assert response_data["success"] is True
        assert "message" in response_data

    def test_404_for_nonexistent(self, client, auth_disabled_settings):
        """Should return 404 for non-existent backup."""
        url = reverse("restore_backup", args=[99999])
        response = client.post(url)
        assert response.status_code == 404

    def test_404_is_json_not_html(self, client, auth_disabled_settings):
        """A not-found restore should return a JSON 404 (not Django's HTML page)."""
        url = reverse("restore_backup", args=[99999])
        response = client.post(url)
        assert response.status_code == 404
        assert response["Content-Type"] == "application/json"
        assert response.json()["success"] is False

    def test_only_accepts_post(self, client, backup_record, auth_disabled_settings):
        """Should only accept POST requests."""
        url = reverse("restore_backup", args=[backup_record.id])
        response = client.get(url)
        assert response.status_code == 405

    def test_returns_error_on_file_not_found(
        self, client, pihole_config, backup_record, temp_backup_dir, auth_disabled_settings
    ):
        """Should return error when backup file is missing."""
        url = reverse("restore_backup", args=[backup_record.id])

        with patch("backup.views.RestoreService") as mock_service_class:
            mock_service = MagicMock()
            mock_service.restore_backup.side_effect = FileNotFoundError("Backup file not found")
            mock_service_class.return_value = mock_service

            response = client.post(url)

        assert response.status_code == 200
        response_data = response.json()
        assert response_data["success"] is False
        assert "not found" in response_data["error"].lower()

    def test_returns_error_on_checksum_mismatch(
        self, client, pihole_config, backup_record, temp_backup_dir, auth_disabled_settings
    ):
        """Should return error when checksum doesn't match."""
        url = reverse("restore_backup", args=[backup_record.id])

        with patch("backup.views.RestoreService") as mock_service_class:
            mock_service = MagicMock()
            mock_service.restore_backup.side_effect = ValueError("Backup file corrupted (checksum mismatch)")
            mock_service_class.return_value = mock_service

            response = client.post(url)

        assert response.status_code == 200
        response_data = response.json()
        assert response_data["success"] is False
        assert "corrupted" in response_data["error"].lower() or "checksum" in response_data["error"].lower()

    def test_returns_error_on_api_failure(
        self, client, pihole_config, backup_record, temp_backup_dir, auth_disabled_settings
    ):
        """Should return error on Pi-hole API failure."""
        url = reverse("restore_backup", args=[backup_record.id])

        with patch("backup.views.RestoreService") as mock_service_class:
            mock_service = MagicMock()
            mock_service.restore_backup.side_effect = ConnectionError("Cannot connect to Pi-hole")
            mock_service_class.return_value = mock_service

            response = client.post(url)

        assert response.status_code == 200
        response_data = response.json()
        assert response_data["success"] is False
        assert "error" in response_data


@pytest.mark.django_db
class TestDownloadBackupEndpoint:
    """Tests for download_backup endpoint."""

    def test_success_returns_file(self, client, pihole_config, backup_record, temp_backup_dir, auth_disabled_settings):
        """Successful download should return file."""
        url = reverse("download_backup", args=[backup_record.id])
        response = client.get(url)

        assert response.status_code == 200
        assert response["Content-Disposition"] == f'attachment; filename="{backup_record.filename}"'

    def test_redirects_when_file_missing(self, client, pihole_config, temp_backup_dir, auth_disabled_settings):
        """Should redirect when file is missing."""
        # Create record with non-existent file
        record = BackupRecordFactory(
            config=pihole_config,
            filename="missing.zip",
            file_path="/nonexistent/missing.zip",
        )

        url = reverse("download_backup", args=[record.id])
        response = client.get(url)

        assert response.status_code == 302
        assert response.url == reverse("dashboard")

    def test_404_for_nonexistent(self, client, auth_disabled_settings):
        """Should return 404 for non-existent backup."""
        url = reverse("download_backup", args=[99999])
        response = client.get(url)
        assert response.status_code == 404


@pytest.mark.django_db
class TestHealthCheckEndpoint:
    """Tests for health_check endpoint."""

    def test_returns_ok_when_healthy(self, client):
        """Should return ok status when healthy."""
        url = reverse("health_check")

        with patch("backup.views.is_scheduler_running", return_value=True):
            response = client.get(url)

        assert response.status_code == 200
        response_data = response.json()
        assert response_data["web"] == "ok"
        assert response_data["scheduler"] == "ok"
        assert response_data["database"] == "ok"

    def test_returns_503_when_scheduler_not_running(self, client):
        """Should return 503 when scheduler not running."""
        url = reverse("health_check")

        with patch("backup.views.is_scheduler_running", return_value=False):
            response = client.get(url)

        assert response.status_code == 503
        response_data = response.json()
        assert response_data["scheduler"] == "not running"

    def test_accessible_without_auth(self, client, auth_enabled_settings):
        """Health check should be accessible without authentication."""
        url = reverse("health_check")

        with patch("backup.views.is_scheduler_running", return_value=True):
            response = client.get(url)

        # Should not redirect to login
        assert response.status_code == 200


@pytest.mark.django_db
class TestLoginView:
    """Tests for login view."""

    def test_get_returns_login_form(self, client):
        """GET should return login form."""
        url = reverse("login")
        response = client.get(url)

        assert response.status_code == 200
        templates_used = [t.name for t in response.templates]
        assert "backup/login.html" in templates_used

    def test_post_valid_password_redirects(self, client, auth_enabled_settings):
        """POST with valid password should redirect to dashboard."""
        url = reverse("login")
        response = client.post(url, {"password": "testpassword"})

        assert response.status_code == 302
        assert response.url == reverse("dashboard")

    def test_post_invalid_password_shows_error(self, client, auth_enabled_settings):
        """POST with invalid password should show error."""
        url = reverse("login")
        response = client.post(url, {"password": "wrongpassword"})

        assert response.status_code == 200
        assert "Invalid" in response.content.decode() or "error" in response.content.decode().lower()


@pytest.mark.django_db
class TestLogoutView:
    """Tests for logout view."""

    def test_logout_clears_session_and_redirects(self, authenticated_client):
        """POST logout should clear session and redirect to login."""
        url = reverse("logout")
        response = authenticated_client.post(url)

        assert response.status_code == 302
        assert response.url == reverse("login")

        # Session should be cleared
        assert "authenticated" not in authenticated_client.session

    def test_logout_rejects_get(self, authenticated_client):
        """GET logout should be rejected (405) and must not flush the session."""
        url = reverse("logout")
        response = authenticated_client.get(url)

        assert response.status_code == 405
        # Session must remain intact after a rejected GET
        assert authenticated_client.session["authenticated"] is True
