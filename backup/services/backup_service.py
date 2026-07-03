"""Backup creation and management service."""

import logging
import re
import uuid
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from ..models import BackupRecord, PiholeConfig
from .checksum import calculate_checksum
from .credential_service import CredentialService
from .notifications import NotificationEvent
from .notifications.service import get_notification_service, safe_send_notification
from .pihole_client import PiholeV6Client

logger = logging.getLogger(__name__)


def resolve_backup_path(record: BackupRecord) -> Path | None:
    """Resolve a record's file_path, refusing anything outside BACKUP_DIR.

    Guards against a tampered ``file_path`` (e.g. ``../../etc/passwd``) pointing
    outside the backup directory. Returns the resolved ``Path`` only when
    ``file_path`` is set and stays within ``settings.BACKUP_DIR``; returns
    ``None`` for an empty path or one that resolves outside the backup dir.
    Existence is intentionally NOT checked here — callers decide how to handle a
    contained-but-missing file.
    """
    if not record.file_path:
        return None

    backup_dir = Path(settings.BACKUP_DIR).resolve()
    filepath = Path(record.file_path).resolve()
    try:
        filepath.relative_to(backup_dir)
    except ValueError:
        logger.warning("Refusing backup path outside backup dir: %s", filepath)
        return None
    return filepath


def delete_backup_file_and_record(record: BackupRecord) -> bool:
    """Delete a backup's file and its DB record.

    The file is only unlinked when it resolves to a path inside BACKUP_DIR, so
    a record whose file_path was tampered with (edited via the admin, or an
    imported/legacy database) cannot make an unattended caller delete an
    arbitrary file. Returns True when the record is deleted; returns False
    without deleting the record if the file exists but could not be removed, so
    it is retried on the next run.
    """
    filepath = resolve_backup_path(record)
    if filepath is not None and filepath.exists():
        try:
            filepath.unlink()
        except OSError as e:
            logger.error("Failed to delete file %s: %s", filepath, e)
            return False

    record.delete()
    return True


class BackupService:
    """Service for creating and managing Pi-hole backups."""

    def __init__(self, config: PiholeConfig):
        self.config = config
        self.backup_dir = Path(settings.BACKUP_DIR)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.notification_service = get_notification_service()

    def _get_client(self) -> PiholeV6Client:
        """Create a Pi-hole client using environment credentials."""
        creds = CredentialService.get_credentials(self.config)
        return PiholeV6Client(
            base_url=creds["url"],
            password=creds["password"],
            verify_ssl=creds["verify_ssl"],
        )

    def _generate_filename(self) -> str:
        """Generate a unique filename for the backup."""
        timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
        # Add short UUID suffix for uniqueness (prevents collision within same second)
        unique_suffix = uuid.uuid4().hex[:8]

        # Sanitize name: keep only alphanumeric, dash, underscore
        safe_name = re.sub(r"[^\w\-]", "_", self.config.name.lower())
        # Collapse multiple underscores
        safe_name = re.sub(r"_+", "_", safe_name)
        # Trim underscores from ends
        safe_name = safe_name.strip("_")
        # Fallback if name becomes empty
        safe_name = safe_name or "pihole"

        return f"checkpoint_pihole_{safe_name}_{timestamp}_{unique_suffix}.zip"

    def create_backup(self, is_manual: bool = False) -> BackupRecord:
        """
        Create a new backup from Pi-hole.

        Args:
            is_manual: Whether this backup was triggered manually

        Returns:
            BackupRecord on success

        Raises:
            Exception on failure
        """
        logger.info(f"Creating backup for {self.config.name} (manual={is_manual})")

        filename = self._generate_filename()
        filepath = self.backup_dir / filename

        try:
            # Download backup from Pi-hole
            client = self._get_client()
            try:
                backup_data = client.download_teleporter_backup()
            finally:
                client.close()

            # Save to file
            with open(filepath, "wb") as f:
                f.write(backup_data)

            # Calculate checksum
            checksum = calculate_checksum(filepath)

            # Create record
            record = BackupRecord.objects.create(
                config=self.config,
                filename=filename,
                file_path=str(filepath),
                file_size=len(backup_data),
                checksum=checksum,
                status="success",
                is_manual=is_manual,
            )

            # Update config status
            self.config.last_successful_backup = timezone.now()
            self.config.last_backup_error = ""
            self.config.save(update_fields=["last_successful_backup", "last_backup_error"])

            logger.info(f"Backup created successfully: {filename}")

            # Send success notification (isolated from backup success)
            safe_send_notification(
                self.notification_service,
                self.config.name,
                NotificationEvent.BACKUP_SUCCESS,
                "Backup Completed",
                f"Successfully created backup: {record.filename}",
                details={"File size": f"{record.file_size:,} bytes"},
            )

            return record

        except Exception as e:
            logger.error(f"Backup failed for {self.config.name}: {e}")

            # Clean up partial file - don't let cleanup errors mask original
            self._safe_cleanup(filepath)

            # Create failed record
            record = BackupRecord.objects.create(
                config=self.config,
                filename=filename,
                file_path="",
                file_size=0,
                status="failed",
                error_message=str(e),
                is_manual=is_manual,
            )

            # Update config with error
            self.config.last_backup_error = str(e)
            self.config.save(update_fields=["last_backup_error"])

            # Send failure notification (isolated)
            safe_send_notification(
                self.notification_service,
                self.config.name,
                NotificationEvent.BACKUP_FAILED,
                "Backup Failed",
                f"Failed to create backup: {e}",
                details={"Error": str(e)},
            )

            raise

    def delete_backup(self, record: BackupRecord) -> bool:
        """
        Delete a backup file and its record.

        Returns True if deleted successfully.
        """
        logger.info(f"Deleting backup: {record.filename}")
        return delete_backup_file_and_record(record)

    def get_backup_file(self, record: BackupRecord) -> Path | None:
        """Get the path to a backup file if it exists within the backup dir."""
        filepath = resolve_backup_path(record)
        if filepath is None:
            return None
        return filepath if filepath.exists() else None

    def _safe_cleanup(self, filepath: Path) -> None:
        """Clean up partial file, catching any errors."""
        try:
            if filepath.exists():
                filepath.unlink()
        except OSError as e:
            logger.warning(f"Failed to clean up partial file {filepath}: {e}")
