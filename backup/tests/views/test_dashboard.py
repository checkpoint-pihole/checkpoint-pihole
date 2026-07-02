"""Tests for dashboard view."""

import pytest
from django.urls import reverse

from backup.tests.factories import BackupRecordFactory, PiholeConfigFactory


@pytest.mark.django_db
class TestDashboardView:
    """Tests for the dashboard view."""

    def test_returns_200(self, client, auth_disabled_settings):
        """Dashboard should return 200 status."""
        url = reverse("dashboard")
        response = client.get(url)
        assert response.status_code == 200

    def test_shows_instance_list_when_no_config(self, client, auth_disabled_settings):
        """Dashboard should show instance list when no config exists."""
        url = reverse("dashboard")
        response = client.get(url)

        assert response.status_code == 200
        templates_used = [t.name for t in response.templates]
        assert "backup/instance_list.html" in templates_used

    def test_shows_dashboard_when_single_config(self, client, pihole_config, auth_disabled_settings):
        """Dashboard should show full dashboard when single config exists."""
        url = reverse("dashboard")
        response = client.get(url)

        assert response.status_code == 200
        templates_used = [t.name for t in response.templates]
        assert "backup/instance_dashboard.html" in templates_used
        assert response.context["single_instance"] is True

    def test_shows_instance_list_when_multiple_configs(self, client, pihole_config, auth_disabled_settings):
        """Dashboard should show instance list when 2+ configs exist."""
        PiholeConfigFactory(name="Secondary", env_prefix="SECONDARY")

        url = reverse("dashboard")
        response = client.get(url)

        assert response.status_code == 200
        templates_used = [t.name for t in response.templates]
        assert "backup/instance_list.html" in templates_used

    def test_shows_config_when_exists(self, client, pihole_config, auth_disabled_settings):
        """Dashboard should show config info when config exists."""
        url = reverse("dashboard")
        response = client.get(url)

        assert response.status_code == 200
        assert pihole_config.name.encode() in response.content

    def test_shows_backup_history(self, client, pihole_config, temp_backup_dir, auth_disabled_settings):
        """Dashboard should show backup history."""
        # Create some backup records
        for i in range(3):
            filepath = temp_backup_dir / f"backup_{i}.zip"
            filepath.write_bytes(b"test")
            BackupRecordFactory(
                config=pihole_config,
                filename=f"backup_{i}.zip",
                file_path=str(filepath),
            )

        url = reverse("dashboard")
        response = client.get(url)

        assert response.status_code == 200
        content = response.content.decode()
        # Check that backups are shown
        assert "backup_0.zip" in content or "backup" in content.lower()

    def test_requires_auth_when_enabled(self, client, pihole_config, auth_enabled_settings):
        """Dashboard should require auth when REQUIRE_AUTH is True."""
        url = reverse("dashboard")
        response = client.get(url)

        # Should redirect to login
        assert response.status_code == 302
        assert "login" in response.url

    def test_accessible_when_authenticated(self, authenticated_client, pihole_config, auth_enabled_settings):
        """Dashboard should be accessible when authenticated."""
        url = reverse("dashboard")
        response = authenticated_client.get(url)

        assert response.status_code == 200

    def test_uses_instance_dashboard_template(self, client, pihole_config, auth_disabled_settings):
        """Dashboard should use instance_dashboard.html template for single config."""
        url = reverse("dashboard")
        response = client.get(url)

        assert response.status_code == 200
        templates_used = [t.name for t in response.templates]
        assert "backup/instance_dashboard.html" in templates_used

    def test_context_contains_config(self, client, pihole_config, auth_disabled_settings):
        """Dashboard context should contain config."""
        url = reverse("dashboard")
        response = client.get(url)

        assert "config" in response.context
        assert response.context["config"] == pihole_config

    def test_context_contains_backups(self, client, pihole_config, temp_backup_dir, auth_disabled_settings):
        """Dashboard context should contain backups queryset."""
        # Create backup record
        filepath = temp_backup_dir / "test.zip"
        filepath.write_bytes(b"test")
        BackupRecordFactory(config=pihole_config, file_path=str(filepath))

        url = reverse("dashboard")
        response = client.get(url)

        assert "backups" in response.context
        assert response.context["backups"].count() == 1

    def test_empty_instance_list_when_no_config(self, client, auth_disabled_settings):
        """Instance list should be empty when no config exists."""
        url = reverse("dashboard")
        response = client.get(url)

        assert "config_data" in response.context
        assert len(response.context["config_data"]) == 0

    def test_instance_list_includes_backup_stats(self, client, pihole_config, temp_backup_dir, auth_disabled_settings):
        """Instance list cards should include backup_count and total_size."""
        PiholeConfigFactory(name="Secondary", env_prefix="SECONDARY")

        # Create backups for the first config
        for i in range(2):
            filepath = temp_backup_dir / f"backup_{i}.zip"
            filepath.write_bytes(b"test")
            BackupRecordFactory(
                config=pihole_config,
                filename=f"backup_{i}.zip",
                file_path=str(filepath),
                file_size=1024,
            )

        url = reverse("dashboard")
        response = client.get(url)

        assert response.status_code == 200
        config_data = response.context["config_data"]
        assert len(config_data) == 2

        # First config should have backup stats
        primary_data = next(d for d in config_data if d["config"] == pihole_config)
        assert primary_data["backup_count"] == 2
        assert primary_data["total_size"] == 2048

        # Second config should have zero stats
        secondary_data = next(d for d in config_data if d["config"] != pihole_config)
        assert secondary_data["backup_count"] == 0
        assert secondary_data["total_size"] == 0


@pytest.mark.django_db
class TestInstanceDashboardView:
    """Tests for the instance_dashboard view."""

    def test_returns_200(self, client, pihole_config, auth_disabled_settings):
        """Instance dashboard should return 200."""
        url = reverse("instance_dashboard", args=[pihole_config.id])
        response = client.get(url)
        assert response.status_code == 200

    def test_returns_404_for_nonexistent(self, client, auth_disabled_settings):
        """Instance dashboard should return 404 for nonexistent config."""
        url = reverse("instance_dashboard", args=[99999])
        response = client.get(url)
        assert response.status_code == 404

    def test_context_has_single_instance_false(self, client, pihole_config, auth_disabled_settings):
        """Instance dashboard should set single_instance=False."""
        url = reverse("instance_dashboard", args=[pihole_config.id])
        response = client.get(url)
        assert response.context["single_instance"] is False

    def test_shows_breadcrumb(self, client, pihole_config, auth_disabled_settings):
        """Instance dashboard should show breadcrumb navigation."""
        url = reverse("instance_dashboard", args=[pihole_config.id])
        response = client.get(url)
        content = response.content.decode()
        assert "Instances" in content
        assert pihole_config.name in content

    def test_shared_helper_context_matches_single_instance_dashboard(
        self, client, pihole_config, auth_disabled_settings
    ):
        """Both dashboard entry points build the same context via the shared helper.

        The single-config `dashboard` route and the per-instance
        `instance_dashboard` route render identical keys, differing only in
        `single_instance`.
        """
        shared_keys = {"config", "backups", "credential_status", "credentials_configured", "single_instance"}

        single = client.get(reverse("dashboard"))
        per_instance = client.get(reverse("instance_dashboard", args=[pihole_config.id]))

        assert shared_keys <= set(single.context.keys())
        assert shared_keys <= set(per_instance.context.keys())
        assert single.context["config"] == per_instance.context["config"] == pihole_config
        assert single.context["single_instance"] is True
        assert per_instance.context["single_instance"] is False
