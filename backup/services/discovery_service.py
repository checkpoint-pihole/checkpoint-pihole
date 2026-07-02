"""Auto-discover Pi-hole instances from PIHOLE_* environment variables."""

import logging
import os
import re

import requests
from django.core.exceptions import ValidationError

from backup.models import PiholeConfig
from backup.services.credential_service import CredentialService
from backup.services.notifications import NotificationEvent
from backup.services.notifications.service import get_notification_service, safe_send_notification
from backup.services.pihole_client import PiholeV6Client

logger = logging.getLogger(__name__)

# Fields recognized after PIHOLE_{PREFIX}_
_KNOWN_FIELDS = {"URL", "PASSWORD", "VERIFY_SSL", "NAME", "SCHEDULE", "TIME", "DAY", "MAX_BACKUPS", "MAX_AGE_DAYS"}

# Non-greedy prefix with exact field match ensures correct split for
# multi-word prefixes like HOME_OFFICE (regex backtracks until the
# suffix matches a known field name).
_ENV_PATTERN = re.compile(r"^PIHOLE_([A-Z][A-Z0-9_]*?)_(" + "|".join(_KNOWN_FIELDS) + r")$")


def _extract_prefixes():
    """Scan os.environ for PIHOLE_*_URL variables.

    Returns a set of discovered prefixes.
    """
    prefixes = set()
    for key in os.environ:
        match = _ENV_PATTERN.match(key)
        if match and match.group(2) == "URL":
            prefixes.add(match.group(1))
    return prefixes


_VALID_FREQUENCIES = {"hourly", "daily", "weekly"}
_VALID_DAYS = set(range(7))  # 0=Monday .. 6=Sunday


def _build_config_kwargs(prefix):
    """Build kwargs dict for PiholeConfig creation from env vars."""
    kwargs = {
        "env_prefix": prefix,
        "name": os.environ.get(
            f"PIHOLE_{prefix}_NAME",
            prefix.replace("_", " ").title(),
        ),
    }

    env_map = {
        "SCHEDULE": ("backup_frequency", str),
        "TIME": ("backup_time", str),
        "DAY": ("backup_day", int),
        "MAX_BACKUPS": ("max_backups", int),
        "MAX_AGE_DAYS": ("max_age_days", int),
    }
    for env_suffix, (field_name, converter) in env_map.items():
        value = os.environ.get(f"PIHOLE_{prefix}_{env_suffix}")
        if value is not None:
            try:
                kwargs[field_name] = converter(value)
            except (ValueError, TypeError):
                logger.warning(
                    "Invalid value for PIHOLE_%s_%s=%r, skipping",
                    prefix,
                    env_suffix,
                    value,
                )
                continue

    # Validate enum fields
    freq = kwargs.get("backup_frequency")
    if freq is not None and freq not in _VALID_FREQUENCIES:
        logger.warning("Invalid PIHOLE_%s_SCHEDULE=%r, using default 'daily'", prefix, freq)
        del kwargs["backup_frequency"]

    day = kwargs.get("backup_day")
    if day is not None and day not in _VALID_DAYS:
        logger.warning("Invalid PIHOLE_%s_DAY=%r, using default 0", prefix, day)
        del kwargs["backup_day"]

    return kwargs


def discover_instances_from_env(force=False):
    """Scan environment for PIHOLE_*_URL vars, create/update/remove PiholeConfig rows.

    Instances whose PIHOLE_{PREFIX}_URL env var is no longer present are
    marked as ``removed`` and deactivated. Their backup records and files
    are retained as orphaned backups.

    Args:
        force: If True, re-apply env var values to existing instances
               (except credentials, which are always runtime).

    Returns:
        dict with "created", "skipped", "updated", and "removed" lists of prefixes.
    """
    prefixes = _extract_prefixes()
    created, skipped, updated, removed = [], [], [], []

    # Mark instances whose env vars are gone as removed (backups are retained)
    for config in PiholeConfig.objects.all():
        if config.env_prefix not in prefixes:
            if config.connection_status != "removed":
                logger.warning(
                    "Instance %s (pk=%d) marked as removed — PIHOLE_%s_URL no longer set. "
                    "Backups are retained as orphaned.",
                    config.name,
                    config.pk,
                    config.env_prefix,
                )
                config.connection_status = "removed"
                config.connection_error = f"PIHOLE_{config.env_prefix}_URL environment variable no longer set"
                config.is_active = False
                config.save(update_fields=["connection_status", "connection_error", "is_active"])
            removed.append(config.env_prefix)

    for prefix in sorted(prefixes):
        existing = PiholeConfig.objects.filter(env_prefix=prefix).first()

        if existing and not force:
            logger.debug(
                "Instance with env_prefix=%s already exists (pk=%d), skipping",
                prefix,
                existing.pk,
            )
            skipped.append(prefix)
            continue

        try:
            kwargs = _build_config_kwargs(prefix)
        except (ValueError, TypeError):
            logger.exception("Invalid env var value for prefix %s, skipping", prefix)
            continue

        if existing and force:
            for field, value in kwargs.items():
                if field != "env_prefix":
                    setattr(existing, field, value)
            try:
                existing.full_clean()
                existing.save()
            except (ValidationError, ValueError) as exc:
                logger.warning(
                    "Invalid config for prefix %s, skipping update: %s",
                    prefix,
                    exc,
                )
                continue
            logger.info("Updated instance %s (pk=%d) from env vars", prefix, existing.pk)
            updated.append(prefix)
        else:
            config = PiholeConfig(**kwargs)
            try:
                config.full_clean()
                config.save()
            except (ValidationError, ValueError) as exc:
                logger.warning(
                    "Invalid config for prefix %s, skipping creation: %s",
                    prefix,
                    exc,
                )
                continue
            logger.info("Created instance %s (pk=%d) from env vars", prefix, config.pk)
            created.append(prefix)

    return {"created": created, "skipped": skipped, "updated": updated, "removed": removed}


def check_connections():
    """Test connection to all configured Pi-hole instances and update status.

    Returns:
        dict mapping env_prefix to connection_status string.
    """
    results = {}
    for config in PiholeConfig.objects.all():
        # Skip removed instances — they have no env vars to check
        if config.connection_status == "removed":
            results[config.env_prefix] = "removed"
            continue

        # Remember the status before this check so we can detect transitions
        previous_status = config.connection_status

        if not CredentialService.is_configured(config):
            config.connection_status = "not_configured"
            config.connection_error = ""
            config.save(update_fields=["connection_status", "connection_error"])
            results[config.env_prefix] = "not_configured"
            continue

        try:
            creds = CredentialService.get_credentials(config)
            with PiholeV6Client(creds["url"], creds["password"], creds["verify_ssl"]) as client:
                client.test_connection()
            config.connection_status = "ok"
            config.connection_error = ""
            logger.info("Connection OK for %s (%s)", config.name, creds["url"])
        except (ConnectionError, OSError) as exc:
            config.connection_status = "unreachable"
            config.connection_error = str(exc)
            logger.warning("Unreachable: %s — %s", config.name, exc)
        except (ValueError, requests.exceptions.HTTPError) as exc:
            config.connection_status = "auth_error"
            config.connection_error = str(exc)
            logger.warning("Auth error: %s — %s", config.name, exc)
        except Exception as exc:
            config.connection_status = "unreachable"
            config.connection_error = str(exc)
            logger.exception("Connection failed: %s — %s", config.name, exc)

        config.save(update_fields=["connection_status", "connection_error"])
        results[config.env_prefix] = config.connection_status

        # Emit CONNECTION_LOST only on a healthy -> unreachable transition, so it
        # fires once when connectivity drops rather than every check while down.
        if previous_status == "ok" and config.connection_status == "unreachable":
            safe_send_notification(
                get_notification_service(),
                config.name,
                NotificationEvent.CONNECTION_LOST,
                "Pi-hole Unreachable",
                f"Lost connection to {config.name}.",
                details={"Error": config.connection_error} if config.connection_error else None,
            )

    return results
