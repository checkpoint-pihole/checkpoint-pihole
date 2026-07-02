"""Unit tests for backup.services.metrics_service.build_registry().

These exercise the registry-building function directly (rather than through the
/metrics/ endpoint) to pin down the per-config gauge values for edge cases in
the "latest record" selection and empty-config handling.
"""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone as dj_timezone

from backup.models import BackupRecord
from backup.services.metrics_service import build_registry
from backup.tests.factories import (
    BackupRecordFactory,
    FailedBackupRecordFactory,
    PiholeConfigFactory,
)

LAST_STATUS = "pihole_backup_last_status"
LAST_SIZE = "pihole_backup_file_size_bytes"
TOTAL_SIZE = "pihole_backup_total_size_bytes"
LAST_SUCCESS_TS = "pihole_backup_last_success_timestamp_seconds"


@pytest.fixture(autouse=True)
def scheduler_running():
    """Keep the scheduler-up probe deterministic and side-effect free."""
    with patch("backup.services.metrics_service.is_scheduler_running", return_value=True) as m:
        yield m


def _labels(config):
    return {"config_id": str(config.id)}


@pytest.mark.django_db
def test_only_failed_records_report_zero_status_and_sizes():
    """A config with only FAILED records: last-status 0, file/total size 0."""
    config = PiholeConfigFactory(name="OnlyFailed", env_prefix="ONLYFAILED")
    FailedBackupRecordFactory(config=config)
    FailedBackupRecordFactory(config=config)

    registry = build_registry()
    labels = _labels(config)

    assert registry.get_sample_value(LAST_STATUS, labels) == 0
    assert registry.get_sample_value(LAST_SIZE, labels) == 0
    assert registry.get_sample_value(TOTAL_SIZE, labels) == 0


@pytest.mark.django_db
def test_no_records_report_none_status_and_zero_timestamp():
    """A config with NO records: last-status -1, last-success timestamp 0."""
    config = PiholeConfigFactory(name="NoRecords", env_prefix="NORECORDS")

    registry = build_registry()
    labels = _labels(config)

    assert registry.get_sample_value(LAST_STATUS, labels) == -1
    assert registry.get_sample_value(LAST_SUCCESS_TS, labels) == 0


@pytest.mark.django_db
def test_identical_created_at_breaks_tie_on_higher_pk():
    """Two records sharing created_at: the higher pk wins the tiebreak."""
    config = PiholeConfigFactory(name="Tie", env_prefix="TIE")
    lower_pk = BackupRecordFactory(config=config, file_size=999)
    higher_pk = BackupRecordFactory(config=config, file_size=222)
    assert higher_pk.pk > lower_pk.pk

    shared = dj_timezone.now() - timedelta(days=1)
    BackupRecord.objects.filter(pk__in=[lower_pk.pk, higher_pk.pk]).update(created_at=shared)

    registry = build_registry()

    # The higher-pk record (file_size=222) must win despite the lower-pk record
    # carrying a larger file_size.
    assert registry.get_sample_value(LAST_SIZE, _labels(config)) == 222


@pytest.mark.django_db
def test_later_failure_beats_older_success_for_last_status():
    """A success older than a later failure yields last-status 0."""
    config = PiholeConfigFactory(name="Mixed", env_prefix="MIXED")
    success = BackupRecordFactory(config=config, status="success", file_size=500)
    failure = FailedBackupRecordFactory(config=config)

    now = dj_timezone.now()
    BackupRecord.objects.filter(pk=success.pk).update(created_at=now - timedelta(days=2))
    BackupRecord.objects.filter(pk=failure.pk).update(created_at=now - timedelta(days=1))

    registry = build_registry()
    labels = _labels(config)

    # Most recent attempt is the failure -> last-status 0.
    assert registry.get_sample_value(LAST_STATUS, labels) == 0
    # But last successful size still reflects the older success.
    assert registry.get_sample_value(LAST_SIZE, labels) == 500
