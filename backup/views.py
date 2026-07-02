import logging
import os

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.hashers import check_password
from django.db import models
from django.db.models import Count, Sum
from django.http import FileResponse, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from .forms import LoginForm
from .models import BackupRecord, PiholeConfig
from .services.backup_service import BackupService
from .services.credential_service import CredentialService
from .services.metrics_service import build_registry
from .services.pihole_client import PiholeV6Client
from .services.restore_service import RestoreService
from .services.system_service import is_scheduler_running

logger = logging.getLogger(__name__)


def dashboard(request):
    """Main dashboard view with smart routing based on config count.

    - 0 configs: show instance list with add prompt
    - 1 config: show full dashboard directly (backward compat)
    - 2+ configs: show instance card grid
    """
    configs = PiholeConfig.objects.all()
    count = configs.count()

    if count == 1:
        config = configs.first()
        backups = BackupRecord.objects.filter(config=config)
        credential_status = CredentialService.get_status(config)
        credentials_configured = CredentialService.is_configured(config)
        return render(
            request,
            "backup/instance_dashboard.html",
            {
                "config": config,
                "backups": backups,
                "credential_status": credential_status,
                "credentials_configured": credentials_configured,
                "single_instance": True,
            },
        )

    # 0 or 2+ configs: show instance list with backup stats
    configs_annotated = configs.annotate(
        backup_count=Count("backups", filter=models.Q(backups__status="success")),
        total_size=Sum("backups__file_size", filter=models.Q(backups__status="success"), default=0),
    )
    config_data = []
    for config in configs_annotated:
        config_data.append(
            {
                "config": config,
                "credential_status": CredentialService.get_status(config),
                "credentials_configured": CredentialService.is_configured(config),
                "backup_count": config.backup_count,
                "total_size": config.total_size,
            }
        )
    return render(
        request,
        "backup/instance_list.html",
        {
            "configs": configs,
            "config_data": config_data,
        },
    )


def instance_dashboard(request, config_id):
    """Per-instance dashboard showing backup status and history."""
    config = get_object_or_404(PiholeConfig, id=config_id)
    backups = BackupRecord.objects.filter(config=config)
    credential_status = CredentialService.get_status(config)
    credentials_configured = CredentialService.is_configured(config)

    return render(
        request,
        "backup/instance_dashboard.html",
        {
            "config": config,
            "backups": backups,
            "credential_status": credential_status,
            "credentials_configured": credentials_configured,
            "single_instance": False,
        },
    )


def instance_settings(request, config_id):
    """Per-instance settings view (read-only)."""
    config = get_object_or_404(PiholeConfig, id=config_id)
    credential_status = CredentialService.get_status(config)

    return render(
        request,
        "backup/settings.html",
        {
            "config": config,
            "credential_status": credential_status,
        },
    )


def settings_redirect(request):
    """Legacy /settings/ redirect to instance settings."""
    config = PiholeConfig.objects.first()
    if config:
        return redirect("instance_settings", config_id=config.id)
    return redirect("dashboard")


@require_POST
def test_connection(request, config_id):
    """AJAX endpoint to test Pi-hole connection using environment credentials."""
    config = PiholeConfig.objects.filter(id=config_id).first()
    if config is None:
        return JsonResponse({"success": False, "error": "Configuration not found."}, status=404)

    try:
        creds = CredentialService.get_credentials(config)

        client = PiholeV6Client(
            base_url=creds["url"],
            password=creds["password"],
            verify_ssl=creds["verify_ssl"],
        )
        try:
            version_info = client.test_connection()
        finally:
            client.close()

        version = version_info.get("version", {}).get("core", {}).get("local", {}).get("version", "unknown")

        return JsonResponse({"success": True, "version": version})

    except ValueError as e:
        return JsonResponse({"success": False, "error": str(e)})
    except ConnectionError as e:
        return JsonResponse({"success": False, "error": str(e)})
    except Exception as e:
        logger.exception("Test connection error")
        return JsonResponse({"success": False, "error": str(e)})


@require_POST
def create_backup(request, config_id):
    """AJAX endpoint to create a manual backup."""
    config = PiholeConfig.objects.filter(id=config_id).first()
    if config is None:
        return JsonResponse({"success": False, "error": "Configuration not found."}, status=404)

    try:
        service = BackupService(config)
        record = service.create_backup(is_manual=True)
        return JsonResponse(
            {
                "success": True,
                "backup": {
                    "id": record.id,
                    "filename": record.filename,
                    "file_size": record.file_size,
                    "status": record.status,
                    "is_manual": record.is_manual,
                    "created_at": record.created_at.isoformat(),
                    "created_at_display": record.created_at.strftime("%b %d, %Y %H:%M"),
                },
            }
        )
    except Exception as e:
        logger.exception("Backup creation error")
        return JsonResponse({"success": False, "error": str(e)})


@require_POST
def delete_backup(request, backup_id):
    """AJAX endpoint to delete a backup."""
    record = get_object_or_404(BackupRecord, id=backup_id)
    config = record.config

    try:
        service = BackupService(config)
        deleted = service.delete_backup(record)
        if not deleted:
            return JsonResponse(
                {"success": False, "error": "Backup file could not be deleted; it will be retried"},
                status=500,
            )
        return JsonResponse({"success": True})
    except Exception as e:
        logger.exception("Backup deletion error")
        return JsonResponse({"success": False, "error": str(e)})


@require_POST
def restore_backup(request, backup_id):
    """AJAX endpoint to restore a backup to Pi-hole."""
    record = get_object_or_404(BackupRecord, id=backup_id)
    config = record.config

    if not config:
        return JsonResponse({"success": False, "error": "Cannot restore: Pi-hole configuration no longer exists"})

    try:
        service = RestoreService(config)
        service.restore_backup(record)
        return JsonResponse(
            {
                "success": True,
                "message": "Backup restored successfully",
            }
        )
    except FileNotFoundError as e:
        return JsonResponse({"success": False, "error": str(e)})
    except ValueError as e:
        return JsonResponse({"success": False, "error": str(e)})
    except Exception as e:
        logger.exception("Restore error")
        return JsonResponse({"success": False, "error": str(e)})


def download_backup(request, backup_id):
    """Download a backup file."""
    record = get_object_or_404(BackupRecord, id=backup_id)
    config = record.config

    if not config:
        messages.error(request, "Pi-hole configuration no longer exists")
        return redirect("dashboard")

    service = BackupService(config)
    filepath = service.get_backup_file(record)

    if not filepath:
        messages.error(request, "Backup file not found")
        return redirect("dashboard")

    # Use Path.open() which FileResponse will properly close
    # FileResponse takes ownership of the file object and closes it when done
    f = filepath.open("rb")
    response = FileResponse(
        f,
        as_attachment=True,
        filename=record.filename,
    )
    # Set content length from open fd to avoid TOCTOU race with retention cleanup
    response["Content-Length"] = os.fstat(f.fileno()).st_size
    return response


def _get_client_ip(request):
    """Get client IP from request."""
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def login_view(request):
    """Login view for optional authentication with rate limiting."""
    from django.core.cache import cache

    if request.method == "POST":
        client_ip = _get_client_ip(request)
        cache_key = f"login_attempts_{client_ip}"

        # Check rate limit: 5 attempts per minute
        attempts = cache.get(cache_key, 0)
        if attempts >= 5:
            return HttpResponse(
                "Too many login attempts. Please wait a minute.",
                status=429,
                content_type="text/plain",
            )

        form = LoginForm(request.POST)
        if form.is_valid():
            if check_password(form.cleaned_data["password"], settings.APP_PASSWORD_HASH):
                # Clear attempts on success
                cache.delete(cache_key)
                request.session["authenticated"] = True
                return redirect("dashboard")
            else:
                # Increment failed attempts
                cache.set(cache_key, attempts + 1, timeout=60)
                return render(request, "backup/login.html", {"error": "Invalid password"})
    else:
        form = LoginForm()

    return render(request, "backup/login.html", {"form": form})


def logout_view(request):
    """Logout view."""
    request.session.flush()
    return redirect("login")


def health_check(request):
    """Health check endpoint for container orchestration."""
    scheduler_running = is_scheduler_running()

    status = {
        "web": "ok",
        "scheduler": "ok" if scheduler_running else "not running",
        "database": "ok",
    }

    if not scheduler_running:
        return JsonResponse(status, status=503)

    return JsonResponse(status)


@require_GET
def metrics_view(request):
    """Prometheus scrape endpoint (text exposition format). See ADR-0016."""
    registry = build_registry()
    return HttpResponse(generate_latest(registry), content_type=CONTENT_TYPE_LATEST)
