"""Unit tests for BackupService."""

import hashlib
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backup.models import BackupRecord
from backup.services.backup_service import BackupService


@pytest.mark.django_db
class TestBackupServiceInit:
    """Tests for BackupService initialization."""

    def test_init_stores_config(self, pihole_config, temp_backup_dir):
        """BackupService should store the config."""
        service = BackupService(pihole_config)
        assert service.config == pihole_config

    def test_init_sets_backup_dir_from_settings(self, pihole_config, temp_backup_dir):
        """BackupService should use BACKUP_DIR from settings."""
        service = BackupService(pihole_config)
        assert service.backup_dir == temp_backup_dir

    def test_init_creates_backup_dir_if_missing(self, pihole_config, settings):
        """BackupService should create backup directory if it doesn't exist."""
        new_backup_path = settings.BACKUP_DIR / "new_subdir"
        settings.BACKUP_DIR = new_backup_path

        BackupService(pihole_config)

        assert new_backup_path.exists()


@pytest.mark.django_db
class TestBackupServiceCreateBackup:
    """Tests for BackupService.create_backup()."""

    def test_create_backup_returns_backup_record(self, pihole_config, temp_backup_dir, sample_backup_data):
        """create_backup should return a BackupRecord on success."""
        with patch.object(BackupService, "_get_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.download_teleporter_backup.return_value = sample_backup_data
            mock_get_client.return_value = mock_client

            service = BackupService(pihole_config)
            record = service.create_backup()

            assert isinstance(record, BackupRecord)
            assert record.status == "success"
            assert record.config == pihole_config

    def test_create_backup_saves_file_to_disk(self, pihole_config, temp_backup_dir, sample_backup_data):
        """create_backup should save backup file to disk."""
        with patch.object(BackupService, "_get_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.download_teleporter_backup.return_value = sample_backup_data
            mock_get_client.return_value = mock_client

            service = BackupService(pihole_config)
            record = service.create_backup()

            filepath = Path(record.file_path)
            assert filepath.exists()
            assert filepath.read_bytes() == sample_backup_data

    def test_create_backup_calculates_sha256_checksum(self, pihole_config, temp_backup_dir, sample_backup_data):
        """create_backup should calculate SHA256 checksum."""
        with patch.object(BackupService, "_get_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.download_teleporter_backup.return_value = sample_backup_data
            mock_get_client.return_value = mock_client

            service = BackupService(pihole_config)
            record = service.create_backup()

            expected_checksum = hashlib.sha256(sample_backup_data).hexdigest()
            assert record.checksum == expected_checksum

    def test_create_backup_records_file_size(self, pihole_config, temp_backup_dir, sample_backup_data):
        """create_backup should record file size."""
        with patch.object(BackupService, "_get_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.download_teleporter_backup.return_value = sample_backup_data
            mock_get_client.return_value = mock_client

            service = BackupService(pihole_config)
            record = service.create_backup()

            assert record.file_size == len(sample_backup_data)

    def test_create_backup_updates_last_successful_backup(self, pihole_config, temp_backup_dir, sample_backup_data):
        """create_backup should update config.last_successful_backup."""
        assert pihole_config.last_successful_backup is None

        with patch.object(BackupService, "_get_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.download_teleporter_backup.return_value = sample_backup_data
            mock_get_client.return_value = mock_client

            service = BackupService(pihole_config)
            service.create_backup()

            pihole_config.refresh_from_db()
            assert pihole_config.last_successful_backup is not None

    def test_create_backup_clears_last_error_on_success(self, pihole_config, temp_backup_dir, sample_backup_data):
        """create_backup should clear last_backup_error on success."""
        pihole_config.last_backup_error = "Previous error"
        pihole_config.save()

        with patch.object(BackupService, "_get_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.download_teleporter_backup.return_value = sample_backup_data
            mock_get_client.return_value = mock_client

            service = BackupService(pihole_config)
            service.create_backup()

            pihole_config.refresh_from_db()
            assert pihole_config.last_backup_error == ""

    def test_create_backup_sets_is_manual_true(self, pihole_config, temp_backup_dir, sample_backup_data):
        """create_backup should set is_manual=True when called with is_manual=True."""
        with patch.object(BackupService, "_get_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.download_teleporter_backup.return_value = sample_backup_data
            mock_get_client.return_value = mock_client

            service = BackupService(pihole_config)
            record = service.create_backup(is_manual=True)

            assert record.is_manual is True

    def test_create_backup_sets_is_manual_false(self, pihole_config, temp_backup_dir, sample_backup_data):
        """create_backup should set is_manual=False by default."""
        with patch.object(BackupService, "_get_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.download_teleporter_backup.return_value = sample_backup_data
            mock_get_client.return_value = mock_client

            service = BackupService(pihole_config)
            record = service.create_backup()

            assert record.is_manual is False

    def test_create_backup_failure_creates_failed_record(self, pihole_config, temp_backup_dir):
        """create_backup failure should create a failed BackupRecord."""
        with patch.object(BackupService, "_get_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.download_teleporter_backup.side_effect = ConnectionError("Connection failed")
            mock_get_client.return_value = mock_client

            service = BackupService(pihole_config)

            with pytest.raises(ConnectionError):
                service.create_backup()

            # Should have created a failed record
            failed_record = BackupRecord.objects.filter(config=pihole_config, status="failed").first()
            assert failed_record is not None
            assert "Connection failed" in failed_record.error_message

    def test_create_backup_failure_cleans_partial_file(self, pihole_config, temp_backup_dir, sample_backup_data):
        """create_backup failure should clean up partial file."""
        created_file = None

        def write_then_fail():
            nonlocal created_file
            # First create a partial file
            service = BackupService(pihole_config)
            created_file = service.backup_dir / service._generate_filename()
            created_file.write_bytes(b"partial data")
            raise ConnectionError("Connection failed after write")

        with patch.object(BackupService, "_get_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.download_teleporter_backup.side_effect = ConnectionError("Connection failed")
            mock_get_client.return_value = mock_client

            service = BackupService(pihole_config)

            with pytest.raises(ConnectionError):
                service.create_backup()

            # Any partial files should be cleaned up (none should exist in backup dir with status=success)
            successful_records = BackupRecord.objects.filter(config=pihole_config, status="success")
            for record in successful_records:
                if record.file_path:
                    assert not Path(record.file_path).exists() or Path(record.file_path).stat().st_size > 0

    def test_create_backup_failure_updates_config_error(self, pihole_config, temp_backup_dir):
        """create_backup failure should update config.last_backup_error."""
        with patch.object(BackupService, "_get_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.download_teleporter_backup.side_effect = ValueError("Auth failed")
            mock_get_client.return_value = mock_client

            service = BackupService(pihole_config)

            with pytest.raises(ValueError):
                service.create_backup()

            pihole_config.refresh_from_db()
            assert "Auth failed" in pihole_config.last_backup_error


@pytest.mark.django_db
class TestBackupServiceDeleteBackup:
    """Tests for BackupService.delete_backup()."""

    def test_delete_backup_removes_file_from_disk(self, pihole_config, backup_record, temp_backup_dir):
        """delete_backup should remove file from disk."""
        filepath = Path(backup_record.file_path)
        assert filepath.exists()

        service = BackupService(pihole_config)
        result = service.delete_backup(backup_record)

        assert result is True
        assert not filepath.exists()

    def test_delete_backup_removes_db_record(self, pihole_config, backup_record, temp_backup_dir):
        """delete_backup should remove database record."""
        record_id = backup_record.id

        service = BackupService(pihole_config)
        service.delete_backup(backup_record)

        assert not BackupRecord.objects.filter(id=record_id).exists()

    def test_delete_backup_handles_missing_file(self, pihole_config, temp_backup_dir):
        """delete_backup should handle missing file gracefully."""
        record = BackupRecord.objects.create(
            config=pihole_config,
            filename="nonexistent.zip",
            file_path="/nonexistent/path/file.zip",
            status="success",
        )
        record_id = record.id

        service = BackupService(pihole_config)
        result = service.delete_backup(record)

        assert result is True
        assert not BackupRecord.objects.filter(id=record_id).exists()

    def test_delete_backup_handles_empty_file_path(self, pihole_config, failed_backup_record, temp_backup_dir):
        """delete_backup should handle empty file_path (failed backups)."""
        record_id = failed_backup_record.id

        service = BackupService(pihole_config)
        result = service.delete_backup(failed_backup_record)

        assert result is True
        assert not BackupRecord.objects.filter(id=record_id).exists()


@pytest.mark.django_db
class TestBackupServiceGetBackupFile:
    """Tests for BackupService.get_backup_file()."""

    def test_get_backup_file_returns_path_when_exists(self, pihole_config, backup_record, temp_backup_dir):
        """get_backup_file should return Path when file exists."""
        service = BackupService(pihole_config)
        result = service.get_backup_file(backup_record)

        assert result is not None
        assert isinstance(result, Path)
        assert result.exists()

    def test_get_backup_file_returns_none_when_missing(self, pihole_config, temp_backup_dir):
        """get_backup_file should return None when file doesn't exist."""
        record = BackupRecord.objects.create(
            config=pihole_config,
            filename="nonexistent.zip",
            file_path="/nonexistent/path/file.zip",
            status="success",
        )

        service = BackupService(pihole_config)
        result = service.get_backup_file(record)

        assert result is None

    def test_get_backup_file_returns_none_when_empty_path(self, pihole_config, failed_backup_record, temp_backup_dir):
        """get_backup_file should return None when file_path is empty."""
        service = BackupService(pihole_config)
        result = service.get_backup_file(failed_backup_record)

        assert result is None

    def test_get_backup_file_refuses_path_outside_backup_dir(self, pihole_config, temp_backup_dir, tmp_path):
        """get_backup_file must refuse (return None) a file_path outside BACKUP_DIR.

        tmp_path is a separate tree from temp_backup_dir (which sets
        settings.BACKUP_DIR), so a real, existing file there is still refused.
        """
        outside_file = tmp_path / "outside.zip"
        outside_file.write_bytes(b"PK\x03\x04outside")

        record = BackupRecord.objects.create(
            config=pihole_config,
            filename="outside.zip",
            file_path=str(outside_file),
            status="success",
        )

        service = BackupService(pihole_config)
        # Refused even though the file exists on disk.
        assert outside_file.exists()
        assert service.get_backup_file(record) is None


@pytest.mark.django_db
class TestBackupServiceGetClient:
    """Tests for BackupService._get_client()."""

    def test_get_client_creates_pihole_client_with_env_credentials(self, pihole_config, temp_backup_dir):
        """_get_client should create PiholeV6Client with credentials from config's env prefix."""
        service = BackupService(pihole_config)

        with patch("backup.services.backup_service.PiholeV6Client") as mock_client_class:
            service._get_client()

            mock_client_class.assert_called_once_with(
                base_url="https://pihole.local",
                password="testpassword123",
                verify_ssl=False,
            )


@pytest.mark.django_db
class TestBackupServiceGenerateFilename:
    """Tests for BackupService._generate_filename()."""

    def test_generate_filename_includes_timestamp(self, pihole_config, temp_backup_dir):
        """_generate_filename should include timestamp."""
        service = BackupService(pihole_config)

        with patch("backup.services.backup_service.timezone") as mock_tz:
            mock_tz.now.return_value = datetime(2024, 1, 15, 10, 30, 45)
            filename = service._generate_filename()

            assert "20240115_103045" in filename

    def test_generate_filename_includes_config_name(self, pihole_config, temp_backup_dir):
        """_generate_filename should include sanitized config name."""
        pihole_config.name = "My Pi-hole"
        pihole_config.save()

        service = BackupService(pihole_config)
        filename = service._generate_filename()

        assert "my_pi-hole" in filename.lower()

    def test_generate_filename_ends_with_zip(self, pihole_config, temp_backup_dir):
        """_generate_filename should end with .zip."""
        service = BackupService(pihole_config)
        filename = service._generate_filename()

        assert filename.endswith(".zip")


@pytest.mark.django_db
class TestBackupServiceCalculateChecksum:
    """Tests for BackupService._calculate_checksum()."""

    def test_calculate_checksum_returns_sha256(self, pihole_config, temp_backup_dir):
        """_calculate_checksum should return SHA256 hex digest."""
        test_data = b"test file content"
        test_file = temp_backup_dir / "test_checksum.txt"
        test_file.write_bytes(test_data)

        service = BackupService(pihole_config)
        checksum = service._calculate_checksum(test_file)

        expected = hashlib.sha256(test_data).hexdigest()
        assert checksum == expected
        assert len(checksum) == 64  # SHA256 hex digest length
