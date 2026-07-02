"""APScheduler management command for running scheduled backups."""

import logging
import threading

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from django.conf import settings
from django.core.management.base import BaseCommand
from django_apscheduler.jobstores import DjangoJobStore

from backup.models import PiholeConfig
from backup.services.backup_service import BackupService
from backup.services.retention_service import RetentionService

logger = logging.getLogger(__name__)

# Module-level scheduler reference for refresh function
_scheduler = None

# Locks for preventing concurrent backup execution per config
_backup_locks: dict[int, threading.Lock] = {}
_locks_lock = threading.Lock()


def _get_config_lock(config_id: int) -> threading.Lock:
    """Get or create a lock for a specific config."""
    with _locks_lock:
        if config_id not in _backup_locks:
            _backup_locks[config_id] = threading.Lock()
        return _backup_locks[config_id]


def run_backup_job_for_config(config_id: int):
    """Execute backup for a specific config.

    Args:
        config_id: The ID of the PiholeConfig to back up
    """
    try:
        config = PiholeConfig.objects.get(id=config_id, is_active=True)
    except PiholeConfig.DoesNotExist:
        logger.warning(f"Config {config_id} not found or inactive, skipping backup")
        return

    lock = _get_config_lock(config_id)

    # Non-blocking acquire - skip if already running
    if not lock.acquire(blocking=False):
        logger.warning(f"Backup already in progress for {config.name}, skipping")
        return

    try:
        logger.info(f"Creating scheduled backup for: {config.name}")
        service = BackupService(config)
        record = service.create_backup(is_manual=False)
        logger.info(f"Backup created: {record.filename}")
    except Exception as e:
        logger.error(f"Backup failed for {config.name}: {e}")
    finally:
        lock.release()


def run_retention_job():
    """Execute retention cleanup for all configs."""
    logger.info("Running retention cleanup job")

    try:
        service = RetentionService()
        deleted = service.enforce_all()
        logger.info(f"Retention cleanup complete: {deleted} backups deleted")
    except Exception as e:
        logger.error(f"Retention cleanup failed: {e}")


def schedule_backup_jobs(scheduler):
    """Schedule backup jobs based on current config."""
    configs = PiholeConfig.objects.filter(is_active=True)

    for config in configs:
        job_id = f"backup_{config.id}"

        # Note: no explicit remove_job here — add_job(replace_existing=True)
        # atomically replaces any existing job, avoiding a remove/add race window.

        # Create trigger based on frequency
        if config.backup_frequency == "hourly":
            # Use CronTrigger for consistent hourly timing (top of each hour)
            minute = config.backup_time.minute if config.backup_time else 0
            trigger = CronTrigger(minute=minute)
            desc = f"every hour at :{minute:02d}"
        elif config.backup_frequency == "daily":
            trigger = CronTrigger(hour=config.backup_time.hour, minute=config.backup_time.minute)
            desc = f"daily at {config.backup_time}"
        elif config.backup_frequency == "weekly":
            trigger = CronTrigger(
                day_of_week=config.backup_day, hour=config.backup_time.hour, minute=config.backup_time.minute
            )
            day_name = config.get_backup_day_display()
            desc = f"weekly on {day_name} at {config.backup_time}"
        else:
            continue

        # Add job with concurrency controls
        # Use partial to pass config_id, so each job only backs up its own config
        scheduler.add_job(
            run_backup_job_for_config,
            trigger=trigger,
            args=[config.id],
            id=job_id,
            name=f"Backup {config.name}",
            replace_existing=True,
            max_instances=1,  # Prevent concurrent execution of same job
            coalesce=True,  # Combine missed executions into one
            misfire_grace_time=300,  # Allow 5 min grace for misfired jobs
        )
        logger.info(f"Scheduled backup for {config.name}: {desc}")


def refresh_backup_schedules():
    """Refresh backup schedules based on current config."""
    global _scheduler
    if _scheduler:
        schedule_backup_jobs(_scheduler)


class Command(BaseCommand):
    help = "Runs APScheduler for backup jobs"

    def handle(self, *args, **options):
        global _scheduler

        scheduler = BlockingScheduler(timezone=settings.TIME_ZONE)
        scheduler.add_jobstore(DjangoJobStore(), "default")

        # Store scheduler reference for refresh function
        _scheduler = scheduler

        # Clear existing jobs to avoid duplicates
        scheduler.remove_all_jobs()

        # Schedule backup jobs based on config
        schedule_backup_jobs(scheduler)

        # Schedule retention job to run daily at 4 AM
        scheduler.add_job(
            run_retention_job,
            trigger=CronTrigger(hour=4, minute=0),
            id="retention_cleanup",
            name="Daily retention cleanup",
            replace_existing=True,
        )
        logger.info("Scheduled retention job for daily at 4:00 AM")

        # Schedule a job to refresh backup schedules every 5 minutes
        # This picks up any config changes
        scheduler.add_job(
            refresh_backup_schedules,
            trigger=IntervalTrigger(minutes=5),
            id="refresh_schedules",
            name="Refresh backup schedules",
            replace_existing=True,
        )
        logger.info("Scheduled schedule refresh every 5 minutes")

        logger.info("Starting APScheduler...")
        self.stdout.write(self.style.SUCCESS("APScheduler started. Press Ctrl+C to exit."))

        try:
            scheduler.start()
        except KeyboardInterrupt:
            logger.info("Stopping APScheduler...")
            scheduler.shutdown()
            self.stdout.write(self.style.SUCCESS("APScheduler stopped."))
