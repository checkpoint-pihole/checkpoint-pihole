import logging
import os

from django.core.validators import RegexValidator
from django.db import models

from config.env import get_bool_env

logger = logging.getLogger(__name__)


class PiholeConfig(models.Model):
    """Configuration for a Pi-hole instance.

    Credentials are read from environment variables using the env_prefix pattern:
    PIHOLE_{PREFIX}_URL, PIHOLE_{PREFIX}_PASSWORD, PIHOLE_{PREFIX}_VERIFY_SSL.
    See ADR-0014 for details.
    """

    FREQUENCY_CHOICES = [
        ("hourly", "Hourly"),
        ("daily", "Daily"),
        ("weekly", "Weekly"),
    ]

    DAY_CHOICES = [
        (0, "Monday"),
        (1, "Tuesday"),
        (2, "Wednesday"),
        (3, "Thursday"),
        (4, "Friday"),
        (5, "Saturday"),
        (6, "Sunday"),
    ]

    name = models.CharField(max_length=100, default="Primary Pi-hole")
    env_prefix = models.CharField(
        max_length=50,
        default="PRIMARY",
        unique=True,
        help_text="Environment variable prefix (e.g., PRIMARY reads PIHOLE_PRIMARY_URL)",
        validators=[
            RegexValidator(
                regex=r"^[A-Z][A-Z0-9_]*$",
                message="Prefix must start with a letter and contain only uppercase letters, numbers, and underscores.",
            ),
        ],
    )

    backup_frequency = models.CharField(max_length=10, choices=FREQUENCY_CHOICES, default="daily")
    backup_time = models.TimeField(default="03:00", help_text="Time for daily/weekly backups")
    backup_day = models.SmallIntegerField(choices=DAY_CHOICES, default=0, help_text="Day for weekly backups")

    max_backups = models.PositiveIntegerField(default=10, help_text="Maximum number of backups to keep")
    max_age_days = models.PositiveIntegerField(default=30, help_text="Delete backups older than this")

    is_active = models.BooleanField(default=True, help_text="Enable scheduled backups")

    CONNECTION_STATUS_CHOICES = [
        ("unknown", "Unknown"),
        ("ok", "Connected"),
        ("auth_error", "Authentication Error"),
        ("unreachable", "Unreachable"),
        ("not_configured", "Not Configured"),
        ("removed", "Removed"),
    ]

    last_successful_backup = models.DateTimeField(null=True, blank=True)
    last_backup_error = models.TextField(blank=True)

    connection_status = models.CharField(
        max_length=20,
        choices=CONNECTION_STATUS_CHOICES,
        default="unknown",
    )
    connection_error = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Pi-hole Configuration"
        verbose_name_plural = "Pi-hole Configurations"

    def __str__(self):
        return self.name

    def get_pihole_credentials(self):
        """Read Pi-hole credentials from environment variables using configured prefix.

        Env var pattern: PIHOLE_{PREFIX}_URL, PIHOLE_{PREFIX}_PASSWORD, PIHOLE_{PREFIX}_VERIFY_SSL
        """
        prefix = self.env_prefix.upper()
        url = os.environ.get(f"PIHOLE_{prefix}_URL", "")
        password = os.environ.get(f"PIHOLE_{prefix}_PASSWORD", "")
        verify_ssl = get_bool_env(f"PIHOLE_{prefix}_VERIFY_SSL", False)

        return {
            "url": url,
            "password": password,
            "verify_ssl": verify_ssl,
        }

    def is_credentials_configured(self):
        """Check if Pi-hole credentials are available in the environment."""
        creds = self.get_pihole_credentials()
        return bool(creds["url"] and creds["password"])


class BackupRecord(models.Model):
    """Record of a backup file."""

    STATUS_CHOICES = [
        ("success", "Success"),
        ("failed", "Failed"),
    ]

    config = models.ForeignKey(PiholeConfig, on_delete=models.CASCADE, related_name="backups")
    filename = models.CharField(max_length=255)
    file_path = models.CharField(max_length=500)
    file_size = models.BigIntegerField(default=0)
    checksum = models.CharField(max_length=64, blank=True)  # SHA256

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="success")
    error_message = models.TextField(blank=True)
    is_manual = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Backup Record"
        verbose_name_plural = "Backup Records"

    def __str__(self):
        return f"{self.filename} ({self.created_at.strftime('%Y-%m-%d %H:%M')})"
