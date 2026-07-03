"""Tests for the shared containment-checked backup deletion helper.

Both the interactive delete endpoint (BackupService.delete_backup) and the
unattended retention job (RetentionService._delete_backup) route through
delete_backup_file_and_record, so the "only unlink inside BACKUP_DIR" guard
must apply to both paths.
"""

import tempfile
from pathlib import Path

import pytest

from backup.models import BackupRecord
from backup.services.backup_service import delete_backup_file_and_record
from backup.services.retention_service import RetentionService


@pytest.mark.django_db
class TestDeleteContainmentGuard:
    def test_deletes_file_inside_backup_dir(self, backup_record, temp_backup_dir):
        """A normal in-dir backup file is unlinked and its record removed."""
        filepath = Path(backup_record.file_path)
        assert filepath.exists()

        assert delete_backup_file_and_record(backup_record) is True

        assert not filepath.exists()
        assert not BackupRecord.objects.filter(id=backup_record.id).exists()

    def test_does_not_unlink_file_outside_backup_dir(self, pihole_config, temp_backup_dir):
        """A record pointing outside BACKUP_DIR must not delete that file."""
        with tempfile.TemporaryDirectory() as outside:
            outside_file = Path(outside) / "important.txt"
            outside_file.write_text("do not delete me")

            record = BackupRecord.objects.create(
                config=pihole_config,
                filename="important.txt",
                file_path=str(outside_file),
                file_size=1,
                status="success",
            )

            assert delete_backup_file_and_record(record) is True

            # Record is still cleaned up, but the out-of-dir file survives.
            assert outside_file.exists()
            assert outside_file.read_text() == "do not delete me"
            assert not BackupRecord.objects.filter(id=record.id).exists()

    def test_retention_path_enforces_same_guard(self, pihole_config, temp_backup_dir):
        """The retention job's deletion must not escape BACKUP_DIR either."""
        with tempfile.TemporaryDirectory() as outside:
            outside_file = Path(outside) / "db.sqlite3"
            outside_file.write_text("database")

            record = BackupRecord.objects.create(
                config=pihole_config,
                filename="db.sqlite3",
                file_path=str(outside_file),
                file_size=1,
                status="success",
            )

            assert RetentionService()._delete_backup(record) is True

            assert outside_file.exists()
            assert not BackupRecord.objects.filter(id=record.id).exists()
