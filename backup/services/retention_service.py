"""Backup retention management service."""

import logging
from datetime import timedelta

from django.utils import timezone

from ..models import BackupRecord, PiholeConfig
from .backup_service import delete_backup_file_and_record

logger = logging.getLogger(__name__)


class RetentionService:
    """Service for enforcing backup retention policies."""

    def enforce_retention(self, config: PiholeConfig) -> int:
        """
        Enforce retention policy for a Pi-hole config.

        Deletes backups that exceed:
        - max_backups count
        - max_age_days age

        Returns number of backups deleted.
        """
        deleted_count = 0

        # Get successful backups for this config, ordered by creation time
        backups = BackupRecord.objects.filter(config=config, status="success").order_by("-created_at")

        # Delete by count (keep only max_backups)
        if config.max_backups > 0:
            excess_backups = backups[config.max_backups :]
            for backup in excess_backups:
                logger.info(f"Deleting backup (exceeds max count): {backup.filename}")
                if self._delete_backup(backup):
                    deleted_count += 1
                # If deletion failed, it will be retried next run

        # Refresh queryset after deletions
        backups = BackupRecord.objects.filter(config=config, status="success").order_by("-created_at")

        # Delete by age
        if config.max_age_days > 0:
            cutoff = timezone.now() - timedelta(days=config.max_age_days)
            old_backups = backups.filter(created_at__lt=cutoff)
            for backup in old_backups:
                logger.info(f"Deleting backup (exceeds max age): {backup.filename}")
                if self._delete_backup(backup):
                    deleted_count += 1
                # If deletion failed, it will be retried next run

        # Clean up failed backup records older than 7 days
        failed_cutoff = timezone.now() - timedelta(days=7)
        old_failed = BackupRecord.objects.filter(config=config, status="failed", created_at__lt=failed_cutoff)
        failed_count = old_failed.count()
        old_failed.delete()
        if failed_count > 0:
            logger.info(f"Cleaned up {failed_count} old failed backup records")

        if deleted_count > 0:
            logger.info(f"Retention cleanup for {config.name}: deleted {deleted_count} backups")

        return deleted_count

    def _delete_backup(self, backup: BackupRecord) -> bool:
        """
        Delete a backup file and record.

        Delegates to the shared containment-checked helper so the unattended
        retention job enforces the same "inside BACKUP_DIR only" guard as the
        interactive delete endpoint. Returns True if successfully deleted.
        """
        return delete_backup_file_and_record(backup)

    def enforce_all(self) -> int:
        """
        Enforce retention for all active configs.

        Returns total number of backups deleted.
        """
        total_deleted = 0
        configs = PiholeConfig.objects.filter(is_active=True)

        for config in configs:
            try:
                deleted = self.enforce_retention(config)
                total_deleted += deleted
            except Exception as e:
                logger.error(f"Retention enforcement failed for {config.name}: {e}")

        return total_deleted
