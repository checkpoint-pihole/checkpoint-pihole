"""Prometheus metrics collector.

Builds a fresh CollectorRegistry on each scrape by querying the Django ORM.
The database is the authoritative source of backup state (ADR-0016), so
reading from it keeps the scheduler and web processes decoupled.
"""

from importlib.metadata import PackageNotFoundError, version

from django.db.models import Count, OuterRef, Subquery, Sum
from prometheus_client import CollectorRegistry, Gauge

from backup.models import BackupRecord, PiholeConfig
from backup.services.system_service import is_scheduler_running

try:
    _APP_VERSION = version("checkpoint-pihole")
except PackageNotFoundError:
    _APP_VERSION = "unknown"

CONFIG_LABELS = ("config_id",)


def build_registry() -> CollectorRegistry:
    """Return a CollectorRegistry populated with current metric values."""
    registry = CollectorRegistry()

    info = Gauge(
        "pihole_info",
        "Checkpoint Pi-hole build information.",
        ("version",),
        registry=registry,
    )
    info.labels(version=_APP_VERSION).set(1)

    scheduler_up = Gauge(
        "pihole_scheduler_up",
        "1 if the APScheduler process is running, 0 otherwise.",
        registry=registry,
    )
    scheduler_up.set(1 if is_scheduler_running() else 0)

    # config_name is mutable; isolate it on an info gauge so rename doesn't stale-duplicate data series.
    config_info = Gauge(
        "pihole_config_info",
        "Pi-hole config metadata; join on config_id for friendly names.",
        (*CONFIG_LABELS, "config_name"),
        registry=registry,
    )
    config_active = Gauge(
        "pihole_config_active",
        "1 if the Pi-hole configuration has scheduled backups enabled.",
        CONFIG_LABELS,
        registry=registry,
    )
    connection_status = Gauge(
        "pihole_connection_status",
        "1 for the current connection_status of each config (one-hot encoded).",
        (*CONFIG_LABELS, "status"),
        registry=registry,
    )
    last_success_ts = Gauge(
        "pihole_backup_last_success_timestamp_seconds",
        "Unix timestamp of the last successful backup (0 if none).",
        CONFIG_LABELS,
        registry=registry,
    )
    last_status = Gauge(
        "pihole_backup_last_status",
        "Status of the most recent backup attempt (1=success, 0=failed, -1=none).",
        CONFIG_LABELS,
        registry=registry,
    )
    backup_records = Gauge(
        "pihole_backup_records",
        "Current number of backup records per config and status.",
        (*CONFIG_LABELS, "status"),
        registry=registry,
    )
    last_size = Gauge(
        "pihole_backup_file_size_bytes",
        "Size in bytes of the most recent successful backup.",
        CONFIG_LABELS,
        registry=registry,
    )
    total_size = Gauge(
        "pihole_backup_total_size_bytes",
        "Sum of file sizes across all successful backups for a config.",
        CONFIG_LABELS,
        registry=registry,
    )

    status_choices = [c[0] for c in PiholeConfig.CONNECTION_STATUS_CHOICES]
    backup_status_choices = [c[0] for c in BackupRecord.STATUS_CHOICES]

    per_config_counts = {
        (row["config_id"], row["status"]): row["n"]
        for row in BackupRecord.objects.values("config_id", "status").annotate(n=Count("id"))
    }
    total_by_config = {
        row["config_id"]: row["total"]
        for row in BackupRecord.objects.filter(status="success").values("config_id").annotate(total=Sum("file_size"))
    }
    # Pick "latest" by created_at to match BackupRecord.Meta.ordering; id is the deterministic tiebreaker.
    latest_success_by_config = {
        row["id"]: row["latest_pk"]
        for row in PiholeConfig.objects.annotate(
            latest_pk=Subquery(
                BackupRecord.objects.filter(config=OuterRef("pk"), status="success")
                .order_by("-created_at", "-id")
                .values("pk")[:1]
            )
        ).values("id", "latest_pk")
        if row["latest_pk"]
    }
    latest_any_by_config = {
        row["id"]: row["latest_pk"]
        for row in PiholeConfig.objects.annotate(
            latest_pk=Subquery(
                BackupRecord.objects.filter(config=OuterRef("pk")).order_by("-created_at", "-id").values("pk")[:1]
            )
        ).values("id", "latest_pk")
        if row["latest_pk"]
    }
    hydrate_ids = set(latest_success_by_config.values()) | set(latest_any_by_config.values())
    hydrated = {r.id: r for r in BackupRecord.objects.filter(id__in=hydrate_ids)}

    for config in PiholeConfig.objects.all():
        labels = {"config_id": str(config.id)}

        config_info.labels(**labels, config_name=config.name).set(1)
        config_active.labels(**labels).set(1 if config.is_active else 0)

        for status in status_choices:
            connection_status.labels(**labels, status=status).set(1 if config.connection_status == status else 0)

        last_success_ts.labels(**labels).set(
            config.last_successful_backup.timestamp() if config.last_successful_backup else 0
        )

        latest = hydrated.get(latest_any_by_config.get(config.id))
        if latest is None:
            last_status.labels(**labels).set(-1)
        else:
            last_status.labels(**labels).set(1 if latest.status == "success" else 0)

        for status in backup_status_choices:
            backup_records.labels(**labels, status=status).set(per_config_counts.get((config.id, status), 0))

        total_size.labels(**labels).set(total_by_config.get(config.id, 0) or 0)
        latest_success = hydrated.get(latest_success_by_config.get(config.id))
        last_size.labels(**labels).set(latest_success.file_size if latest_success else 0)

    return registry
