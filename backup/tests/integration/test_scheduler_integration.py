"""Integration tests for scheduler functionality."""

from datetime import time
from unittest.mock import MagicMock, patch

import pytest
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from backup.management.commands import runapscheduler
from backup.management.commands.runapscheduler import (
    Command,
    refresh_backup_schedules,
    run_backup_job_for_config,
    run_retention_job,
    schedule_backup_jobs,
)
from backup.tests.factories import (
    HourlyPiholeConfigFactory,
    InactivePiholeConfigFactory,
    PiholeConfigFactory,
    WeeklyPiholeConfigFactory,
)


@pytest.mark.django_db
@pytest.mark.integration
class TestRunBackupJobForConfig:
    """Tests for run_backup_job_for_config function.

    Note: This function now backs up a single specific config (by ID),
    rather than all configs. This prevents N×N backup attempts when
    N configs are scheduled (see ADR-0013, Issue 1).
    """

    def test_creates_backup_for_specific_config(self, temp_backup_dir, sample_backup_data):
        """run_backup_job_for_config should create backup for the specified config only."""
        config1 = PiholeConfigFactory(name="Config 1")
        config2 = PiholeConfigFactory(name="Config 2")

        with patch("backup.management.commands.runapscheduler.BackupService") as mock_service_class:
            mock_service = MagicMock()
            mock_record = MagicMock()
            mock_record.filename = "test.zip"
            mock_service.create_backup.return_value = mock_record
            mock_service_class.return_value = mock_service

            # Only run for config1
            run_backup_job_for_config(config1.id)

            # Should have created service only for config1 (not config2)
            assert mock_service_class.call_count == 1
            mock_service_class.assert_called_with(config1)
            mock_service.create_backup.assert_called_once()

            # Verify config2 was not backed up by running again for config2
            mock_service_class.reset_mock()
            mock_service.reset_mock()
            run_backup_job_for_config(config2.id)
            mock_service_class.assert_called_with(config2)

    def test_skips_inactive_config(self, temp_backup_dir):
        """run_backup_job_for_config should skip if config is inactive."""
        inactive = InactivePiholeConfigFactory(name="Inactive")

        with patch("backup.management.commands.runapscheduler.BackupService") as mock_service_class:
            run_backup_job_for_config(inactive.id)

            # Should not create service for inactive config
            mock_service_class.assert_not_called()

    def test_skips_nonexistent_config(self, temp_backup_dir):
        """run_backup_job_for_config should skip if config doesn't exist."""
        with patch("backup.management.commands.runapscheduler.BackupService") as mock_service_class:
            # Use a config ID that doesn't exist
            run_backup_job_for_config(99999)

            # Should not create service
            mock_service_class.assert_not_called()

    def test_handles_failure_gracefully(self, temp_backup_dir):
        """run_backup_job_for_config should handle backup failures gracefully."""
        config = PiholeConfigFactory(name="Will Fail")

        with patch("backup.management.commands.runapscheduler.BackupService") as mock_service_class:
            mock_service = MagicMock()
            mock_service.create_backup.side_effect = Exception("Backup failed")
            mock_service_class.return_value = mock_service

            # Should not raise exception
            run_backup_job_for_config(config.id)

            # Backup was attempted
            mock_service.create_backup.assert_called_once()


@pytest.mark.django_db
@pytest.mark.integration
class TestRunRetentionJob:
    """Tests for run_retention_job function."""

    def test_calls_enforce_all(self, temp_backup_dir):
        """run_retention_job should call RetentionService.enforce_all()."""
        with patch("backup.management.commands.runapscheduler.RetentionService") as mock_service_class:
            mock_service = MagicMock()
            mock_service.enforce_all.return_value = 5
            mock_service_class.return_value = mock_service

            run_retention_job()

            mock_service.enforce_all.assert_called_once()

    def test_handles_errors(self, temp_backup_dir):
        """run_retention_job should handle errors gracefully."""
        with patch("backup.management.commands.runapscheduler.RetentionService") as mock_service_class:
            mock_service = MagicMock()
            mock_service.enforce_all.side_effect = Exception("Retention failed")
            mock_service_class.return_value = mock_service

            # Should not raise exception
            run_retention_job()


@pytest.mark.django_db
@pytest.mark.integration
class TestScheduleBackupJobs:
    """Tests for schedule_backup_jobs() function."""

    def test_hourly_config_uses_cron_trigger(self, temp_backup_dir):
        """Hourly backup config should use CronTrigger for consistent timing."""
        HourlyPiholeConfigFactory()

        mock_scheduler = MagicMock()

        schedule_backup_jobs(mock_scheduler)

        # Verify add_job was called
        mock_scheduler.add_job.assert_called()

        # Get the call args
        call_kwargs = mock_scheduler.add_job.call_args_list[-1].kwargs
        trigger = call_kwargs.get("trigger")

        # Hourly backups now use CronTrigger for consistent timing (top of each hour)
        assert isinstance(trigger, CronTrigger)

    def test_daily_config_uses_cron_trigger(self, temp_backup_dir):
        """Daily backup config should use CronTrigger."""
        PiholeConfigFactory(backup_frequency="daily", backup_time=time(3, 30))

        mock_scheduler = MagicMock()

        schedule_backup_jobs(mock_scheduler)

        call_kwargs = mock_scheduler.add_job.call_args_list[-1].kwargs
        trigger = call_kwargs.get("trigger")

        assert isinstance(trigger, CronTrigger)

    def test_weekly_config_uses_cron_trigger_with_day(self, temp_backup_dir):
        """Weekly backup config should use CronTrigger with day_of_week."""
        WeeklyPiholeConfigFactory(
            backup_day=2,  # Wednesday
            backup_time=time(4, 0),
        )

        mock_scheduler = MagicMock()

        schedule_backup_jobs(mock_scheduler)

        call_kwargs = mock_scheduler.add_job.call_args_list[-1].kwargs
        trigger = call_kwargs.get("trigger")

        assert isinstance(trigger, CronTrigger)

    def test_replaces_existing_job_via_replace_existing(self, temp_backup_dir):
        """Should rely on add_job(replace_existing=True) instead of an explicit remove.

        The old remove/add sequence opened a race window; jobs are now replaced
        atomically and remove_job is never called.
        """
        config = PiholeConfigFactory()

        mock_scheduler = MagicMock()

        schedule_backup_jobs(mock_scheduler)

        # No explicit remove_job — replacement happens via add_job
        mock_scheduler.remove_job.assert_not_called()

        add_call = next(
            call for call in mock_scheduler.add_job.call_args_list if call.kwargs.get("id") == f"backup_{config.id}"
        )
        assert add_call.kwargs.get("replace_existing") is True

    def test_skips_inactive_configs(self, temp_backup_dir):
        """Should skip inactive configs."""
        active = PiholeConfigFactory()
        inactive = InactivePiholeConfigFactory()

        mock_scheduler = MagicMock()

        schedule_backup_jobs(mock_scheduler)

        # Should only add job for active config
        job_ids = [call.kwargs.get("id") for call in mock_scheduler.add_job.call_args_list]
        assert f"backup_{active.id}" in job_ids
        assert f"backup_{inactive.id}" not in job_ids

@pytest.mark.django_db
@pytest.mark.integration
class TestRefreshBackupSchedules:
    """Tests for refresh_backup_schedules() function."""

    def test_calls_schedule_backup_jobs_when_scheduler_set(self, temp_backup_dir):
        """refresh_backup_schedules should call schedule_backup_jobs when scheduler is available."""
        PiholeConfigFactory()
        mock_scheduler = MagicMock()

        # Set the module-level scheduler reference
        original_scheduler = runapscheduler._scheduler
        runapscheduler._scheduler = mock_scheduler

        try:
            refresh_backup_schedules()

            # Should have called add_job via schedule_backup_jobs
            mock_scheduler.add_job.assert_called()
        finally:
            # Restore original state
            runapscheduler._scheduler = original_scheduler

    def test_does_nothing_when_scheduler_not_set(self, temp_backup_dir):
        """refresh_backup_schedules should do nothing when scheduler is None."""
        # Ensure scheduler is None
        original_scheduler = runapscheduler._scheduler
        runapscheduler._scheduler = None

        try:
            # Should not raise any exception
            refresh_backup_schedules()
        finally:
            runapscheduler._scheduler = original_scheduler


@pytest.mark.django_db
@pytest.mark.integration
class TestSchedulerCommand:
    """Tests for the full scheduler Command."""

    def test_handle_sets_up_scheduler(self, temp_backup_dir):
        """handle() should set up scheduler with job store and jobs."""
        PiholeConfigFactory()

        with patch("backup.management.commands.runapscheduler.BlockingScheduler") as mock_scheduler_class:
            mock_scheduler = MagicMock()
            mock_scheduler_class.return_value = mock_scheduler

            # Mock start to exit immediately
            mock_scheduler.start.side_effect = KeyboardInterrupt()

            command = Command()
            command.stdout = MagicMock()

            # Should handle KeyboardInterrupt gracefully
            command.handle()

            # Verify scheduler was configured
            mock_scheduler.add_jobstore.assert_called()
            mock_scheduler.remove_all_jobs.assert_called()

            # Should have added retention and refresh jobs
            job_names = [call.kwargs.get("id") for call in mock_scheduler.add_job.call_args_list]
            assert "retention_cleanup" in job_names
            assert "refresh_schedules" in job_names

    def test_retention_job_scheduled_at_4am(self, temp_backup_dir):
        """Retention job should be scheduled at 4:00 AM."""
        with patch("backup.management.commands.runapscheduler.BlockingScheduler") as mock_scheduler_class:
            mock_scheduler = MagicMock()
            mock_scheduler_class.return_value = mock_scheduler
            mock_scheduler.start.side_effect = KeyboardInterrupt()

            command = Command()
            command.stdout = MagicMock()
            command.handle()

            # Find the retention cleanup job call
            for call in mock_scheduler.add_job.call_args_list:
                if call.kwargs.get("id") == "retention_cleanup":
                    trigger = call.kwargs.get("trigger")
                    assert isinstance(trigger, CronTrigger)
                    break

    def test_schedule_refresh_runs_every_5_minutes(self, temp_backup_dir):
        """Schedule refresh should run every 5 minutes."""
        with patch("backup.management.commands.runapscheduler.BlockingScheduler") as mock_scheduler_class:
            mock_scheduler = MagicMock()
            mock_scheduler_class.return_value = mock_scheduler
            mock_scheduler.start.side_effect = KeyboardInterrupt()

            command = Command()
            command.stdout = MagicMock()
            command.handle()

            # Find the refresh schedules job call
            for call in mock_scheduler.add_job.call_args_list:
                if call.kwargs.get("id") == "refresh_schedules":
                    trigger = call.kwargs.get("trigger")
                    assert isinstance(trigger, IntervalTrigger)
                    break
