# ADR-0011: Bug Review Findings and Remediation Plan

**Status:** Implemented
**Date:** 2026-01-18
**Deciders:** Project Owner

---

## Context

A comprehensive bug review was conducted on the Checkpoint Pi-hole codebase to identify logical errors, race conditions, unhandled edge cases, security vulnerabilities, and other issues. This ADR documents all findings and serves as a tracking mechanism for remediation efforts.

The review covered:
- Service layer (`pihole_client.py`, `backup_service.py`, `retention_service.py`)
- Notification system (`notifications/service.py`, `notifications/config.py`)
- Views and endpoints (`views.py`)
- Models and forms
- Scheduler (`runapscheduler.py`)
- Middleware (`simple_auth.py`)
- Configuration (`settings.py`)
- Container entrypoint (`entrypoint.sh`)

---

## Findings

### Critical Issues

These issues could cause data loss, security breaches, or application failures.

---

#### Bug 1: File Handle Leak in download_backup View

| | |
|---|---|
| **Location** | `backup/views.py:160-172` |
| **Status** | [x] Fixed |
| **Priority** | Critical |

**Description:**
The file is opened with `open()` but never explicitly closed. If `FileResponse` fails to close it properly (e.g., on client disconnect), the file descriptor will leak.

**Current Code:**
```python
def download_backup(request, backup_id):
    """Download a backup file."""
    record = get_object_or_404(BackupRecord, id=backup_id)
    config = record.config

    service = BackupService(config)
    filepath = service.get_backup_file(record)

    if not filepath:
        messages.error(request, "Backup file not found")
        return redirect("dashboard")

    return FileResponse(open(filepath, "rb"), as_attachment=True, filename=record.filename)
```

**Impact:**
Resource exhaustion over time in long-running server. Each leaked file handle consumes system resources and counts against ulimits.

**Fix Implementation:**

```python
from pathlib import Path

def download_backup(request, backup_id):
    """Download a backup file."""
    record = get_object_or_404(BackupRecord, id=backup_id)
    config = record.config

    service = BackupService(config)
    filepath = service.get_backup_file(record)

    if not filepath:
        messages.error(request, "Backup file not found")
        return redirect("dashboard")

    # Use Path.open() which FileResponse will properly close
    # FileResponse takes ownership of the file object and closes it when done
    response = FileResponse(
        filepath.open("rb"),
        as_attachment=True,
        filename=record.filename
    )
    # Set content length for proper download progress
    response["Content-Length"] = filepath.stat().st_size
    return response
```

**Alternative Fix (using streaming):**
```python
def download_backup(request, backup_id):
    """Download a backup file."""
    record = get_object_or_404(BackupRecord, id=backup_id)
    config = record.config

    service = BackupService(config)
    filepath = service.get_backup_file(record)

    if not filepath:
        messages.error(request, "Backup file not found")
        return redirect("dashboard")

    # Let Django handle the file directly using the path
    return FileResponse(
        open(filepath, "rb"),
        as_attachment=True,
        filename=record.filename,
        # Ensure proper cleanup on disconnect
        headers={"Content-Length": str(filepath.stat().st_size)}
    )
```

**Testing:**
- Verify downloads complete successfully
- Test client disconnect mid-download (use browser dev tools to cancel)
- Monitor file descriptors with `lsof -p <pid> | wc -l` during stress test

---

#### Bug 2: urljoin URL Path Stripping

| | |
|---|---|
| **Location** | `backup/services/pihole_client.py:21-23` |
| **Status** | [x] Fixed |
| **Priority** | Critical |

**Description:**
Using `urljoin` with an endpoint starting with `/` replaces the entire path of the base URL, losing any path prefix like `/admin`.

**Current Code:**
```python
def _get_url(self, endpoint: str) -> str:
    """Build full URL for an endpoint."""
    return urljoin(self.base_url, endpoint)
```

**Impact:**
Breaks Pi-hole instances behind reverse proxies with path prefixes. Users configured with `https://pihole.local/admin` will have API calls go to `https://pihole.local/api/auth` instead of `https://pihole.local/admin/api/auth`.

**Demonstration of Bug:**
```python
>>> from urllib.parse import urljoin
>>> urljoin("https://pihole.local/admin", "/api/auth")
'https://pihole.local/api/auth'  # WRONG - lost /admin prefix!
>>> urljoin("https://pihole.local/admin/", "api/auth")
'https://pihole.local/admin/api/auth'  # Only works without leading /
```

**Fix Implementation:**

```python
def _get_url(self, endpoint: str) -> str:
    """Build full URL for an endpoint."""
    # Simple string concatenation preserves the base URL path
    # self.base_url is already rstrip("/") in __init__
    return self.base_url + endpoint
```

**Alternative Fix (more robust):**
```python
from urllib.parse import urlparse, urlunparse

def _get_url(self, endpoint: str) -> str:
    """Build full URL for an endpoint."""
    parsed = urlparse(self.base_url)
    # Combine base path with endpoint path
    new_path = parsed.path.rstrip("/") + endpoint
    return urlunparse(parsed._replace(path=new_path))
```

**Testing:**
- Test with base URL `https://pihole.local` (no path)
- Test with base URL `https://pihole.local/admin` (path prefix)
- Test with base URL `https://pihole.local/pi/hole/admin` (nested path)
- Verify all API endpoints work correctly in each scenario

---

#### Bug 3: Race Condition in Concurrent Backup Jobs

| | |
|---|---|
| **Location** | `backup/management/commands/runapscheduler.py:19-32, 120-127` |
| **Status** | [x] Fixed |
| **Priority** | Critical |

**Description:**
The `run_backup_job()` function iterates over all active configs without locking. If scheduled jobs overlap or duplicate jobs are created, multiple backups for the same config could run concurrently.

**Current Code:**
```python
# Job scheduling without concurrency controls
scheduler.add_job(
    run_backup_job,
    trigger=trigger,
    id=job_id,
    name=f"Backup {config.name}",
    replace_existing=True,
)
```

**Impact:**
- Duplicate backup files with identical timestamps
- Database record conflicts
- Excessive load on Pi-hole
- Potential data corruption

**Fix Implementation:**

```python
# In _schedule_backup_jobs method
scheduler.add_job(
    run_backup_job,
    trigger=trigger,
    id=job_id,
    name=f"Backup {config.name}",
    replace_existing=True,
    max_instances=1,      # Prevent concurrent execution of same job
    coalesce=True,        # Combine missed executions into one
    misfire_grace_time=300,  # Allow 5 min grace for misfired jobs
)
```

**Additional Protection with Locking:**

```python
import threading
from contextlib import contextmanager

# Module-level lock dictionary
_backup_locks: dict[int, threading.Lock] = {}
_locks_lock = threading.Lock()

def _get_config_lock(config_id: int) -> threading.Lock:
    """Get or create a lock for a specific config."""
    with _locks_lock:
        if config_id not in _backup_locks:
            _backup_locks[config_id] = threading.Lock()
        return _backup_locks[config_id]

def run_backup_job():
    """Execute backup for all active configs."""
    logger.info("Running scheduled backup job")

    configs = PiholeConfig.objects.filter(is_active=True)

    for config in configs:
        lock = _get_config_lock(config.id)

        # Non-blocking acquire - skip if already running
        if not lock.acquire(blocking=False):
            logger.warning(f"Backup already in progress for {config.name}, skipping")
            continue

        try:
            logger.info(f"Creating backup for: {config.name}")
            service = BackupService(config)
            record = service.create_backup(is_manual=False)
            logger.info(f"Backup created: {record.filename}")
        except Exception as e:
            logger.error(f"Backup failed for {config.name}: {e}")
        finally:
            lock.release()
```

**Testing:**
- Trigger multiple backup jobs simultaneously
- Verify only one backup runs per config
- Check logs for "already in progress" messages when overlapping

---

### Warning-Level Issues

These issues could cause unexpected behavior or minor security concerns.

---

#### Bug 4: Silent Exception Swallowing in Scheduler

| | |
|---|---|
| **Location** | `backup/management/commands/runapscheduler.py:99-102` |
| **Status** | [x] Fixed |
| **Priority** | Warning |

**Description:**
All exceptions are silently swallowed when removing existing jobs with `except Exception: pass`.

**Current Code:**
```python
# Remove existing job for this config
try:
    scheduler.remove_job(job_id)
except Exception:
    pass
```

**Impact:**
Hides unexpected errors like database connection issues or corruption, making debugging difficult.

**Fix Implementation:**

```python
from apscheduler.jobstores.base import JobLookupError

# Remove existing job for this config
try:
    scheduler.remove_job(job_id)
except JobLookupError:
    # Job doesn't exist, which is fine - we're about to create it
    pass
except Exception as e:
    # Log unexpected errors but continue
    logger.warning(f"Unexpected error removing job {job_id}: {e}")
```

**Testing:**
- Verify job removal works when job exists
- Verify no error when job doesn't exist
- Verify other exceptions are logged

---

#### Bug 5: ThreadPoolExecutor Never Shut Down

| | |
|---|---|
| **Location** | `backup/services/notifications/service.py:28-29` |
| **Status** | [x] Fixed |
| **Priority** | Warning |

**Description:**
The `ThreadPoolExecutor` is created but never explicitly shut down.

**Current Code:**
```python
class NotificationService:
    """Manages sending notifications across multiple providers."""

    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=5)
        self.settings = get_notification_settings()
```

**Impact:**
Pending notification tasks may be abandoned mid-execution on shutdown, and the process may hang.

**Fix Implementation:**

```python
import atexit
from concurrent.futures import ThreadPoolExecutor

class NotificationService:
    """Manages sending notifications across multiple providers."""

    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=5)
        self.settings = get_notification_settings()
        # Register cleanup on interpreter shutdown
        atexit.register(self._shutdown)

    def _shutdown(self):
        """Gracefully shutdown the executor."""
        self.executor.shutdown(wait=True, cancel_futures=False)

    # ... rest of class
```

**Alternative Fix (using context manager pattern):**
```python
class NotificationService:
    """Manages sending notifications across multiple providers."""

    def __init__(self):
        self._executor: ThreadPoolExecutor | None = None
        self.settings = get_notification_settings()

    @property
    def executor(self) -> ThreadPoolExecutor:
        """Lazily create executor on first use."""
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=5)
            atexit.register(self._shutdown)
        return self._executor

    def _shutdown(self):
        """Gracefully shutdown the executor."""
        if self._executor is not None:
            self._executor.shutdown(wait=True, cancel_futures=False)
            self._executor = None
```

**Testing:**
- Verify notifications still send correctly
- Test container stop/restart for clean shutdown
- Monitor for hung processes during shutdown

---

#### Bug 6: Insecure Default SECRET_KEY

| | |
|---|---|
| **Location** | `config/settings.py:14` |
| **Status** | [x] Fixed |
| **Priority** | Warning |

**Description:**
A fallback insecure `SECRET_KEY` is used when the environment variable is not set.

**Current Code:**
```python
SECRET_KEY = os.environ.get("SECRET_KEY", "django-insecure-change-me-in-production")
```

**Impact:**
Compromises session security, CSRF protection, and signed data if deployed without setting the variable.

**Fix Implementation:**

```python
# Option 1: Fail fast in production
SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    if DEBUG:
        # Only allow insecure key in debug mode
        SECRET_KEY = "django-insecure-dev-only-key-not-for-production"
    else:
        raise ValueError(
            "SECRET_KEY environment variable must be set in production. "
            "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(50))\""
        )
```

```python
# Option 2: Auto-generate and persist (for simpler deployments)
import secrets
from pathlib import Path

def get_or_create_secret_key() -> str:
    """Get secret key from env or generate and persist one."""
    key = os.environ.get("SECRET_KEY")
    if key:
        return key

    # Check for persisted key
    key_file = BASE_DIR / "data" / ".secret_key"
    if key_file.exists():
        return key_file.read_text().strip()

    # Generate new key
    key = secrets.token_urlsafe(50)
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_text(key)
    key_file.chmod(0o600)  # Restrict permissions
    return key

SECRET_KEY = get_or_create_secret_key()
```

**Testing:**
- Verify app starts with SECRET_KEY set
- Verify app fails with clear error when SECRET_KEY missing (prod mode)
- Verify app works in debug mode without SECRET_KEY

---

#### Bug 7: ALLOWED_HOSTS Defaults to Wildcard

| | |
|---|---|
| **Location** | `config/settings.py:18` |
| **Status** | [x] Fixed |
| **Priority** | Warning |

**Description:**
`ALLOWED_HOSTS` defaults to `*`, allowing requests from any host.

**Current Code:**
```python
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "*").split(",")
```

**Impact:**
Vulnerable to host header attacks in production.

**Fix Implementation:**

```python
# Parse ALLOWED_HOSTS with sensible defaults
_allowed_hosts_env = os.environ.get("ALLOWED_HOSTS", "")
if _allowed_hosts_env:
    ALLOWED_HOSTS = [h.strip() for h in _allowed_hosts_env.split(",") if h.strip()]
elif DEBUG:
    # Allow all hosts only in debug mode
    ALLOWED_HOSTS = ["*"]
else:
    # Default to localhost only in production
    ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]
```

**Documentation Update (.env.example):**
```bash
# Allowed hosts (comma-separated). Required in production.
# Examples: pihole.local,192.168.1.100
ALLOWED_HOSTS=
```

**Testing:**
- Verify app works with ALLOWED_HOSTS set
- Verify requests from unlisted hosts are rejected (403)
- Verify localhost works by default

---

#### Bug 8: Missing Null Check on Config in delete_backup

| | |
|---|---|
| **Location** | `backup/views.py:121-133` |
| **Status** | [x] Fixed |
| **Priority** | Warning |

**Description:**
The `delete_backup` endpoint does not verify that `record.config` exists before passing it to `BackupService`.

**Current Code:**
```python
@require_POST
def delete_backup(request, backup_id):
    """AJAX endpoint to delete a backup."""
    record = get_object_or_404(BackupRecord, id=backup_id)
    config = record.config  # Could be None!

    try:
        service = BackupService(config)  # Will fail with unclear error
        service.delete_backup(record)
        return JsonResponse({"success": True})
    except Exception as e:
        logger.exception("Backup deletion error")
        return JsonResponse({"success": False, "error": str(e)})
```

**Impact:**
Unclear error if `PiholeConfig` was deleted but `BackupRecord` orphaned (e.g., due to database issues or cascading delete failure).

**Fix Implementation:**

```python
@require_POST
def delete_backup(request, backup_id):
    """AJAX endpoint to delete a backup."""
    record = get_object_or_404(BackupRecord, id=backup_id)
    config = record.config

    # Handle orphaned backup records
    if not config:
        # Config was deleted but backup record remains - just delete the record
        logger.warning(f"Deleting orphaned backup record: {record.filename}")
        if record.file_path:
            filepath = Path(record.file_path)
            if filepath.exists():
                try:
                    filepath.unlink()
                except OSError as e:
                    logger.error(f"Failed to delete orphaned file: {e}")
        record.delete()
        return JsonResponse({"success": True})

    try:
        service = BackupService(config)
        service.delete_backup(record)
        return JsonResponse({"success": True})
    except Exception as e:
        logger.exception("Backup deletion error")
        return JsonResponse({"success": False, "error": str(e)})
```

**Also apply same fix to restore_backup:**
```python
@require_POST
def restore_backup(request, backup_id):
    """AJAX endpoint to restore a backup to Pi-hole."""
    record = get_object_or_404(BackupRecord, id=backup_id)
    config = record.config

    if not config:
        return JsonResponse({
            "success": False,
            "error": "Cannot restore: Pi-hole configuration no longer exists"
        })

    # ... rest of function
```

**Testing:**
- Delete a PiholeConfig and verify backup deletion still works
- Verify restore shows proper error for orphaned backups

---

#### Bug 9: Timestamp Collision in Filename Generation

| | |
|---|---|
| **Location** | `backup/services/backup_service.py:38-42` |
| **Status** | [x] Fixed |
| **Priority** | Warning |

**Description:**
Backup filenames use timestamps with only second precision.

**Current Code:**
```python
def _generate_filename(self) -> str:
    """Generate a unique filename for the backup."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = self.config.name.replace(" ", "_").lower()
    return f"checkpoint_pihole_{safe_name}_{timestamp}.zip"
```

**Impact:**
Two backups created within the same second would have the same filename, causing overwrites and data loss.

**Fix Implementation:**

```python
import uuid

def _generate_filename(self) -> str:
    """Generate a unique filename for the backup."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # Add short UUID suffix for uniqueness
    unique_suffix = uuid.uuid4().hex[:8]
    safe_name = self.config.name.replace(" ", "_").lower()
    return f"checkpoint_pihole_{safe_name}_{timestamp}_{unique_suffix}.zip"
```

**Alternative Fix (microseconds):**
```python
def _generate_filename(self) -> str:
    """Generate a unique filename for the backup."""
    # Include microseconds for higher precision
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    safe_name = self.config.name.replace(" ", "_").lower()
    return f"checkpoint_pihole_{safe_name}_{timestamp}.zip"
```

**Testing:**
- Create multiple backups in rapid succession
- Verify each has a unique filename
- Verify old backup naming pattern still parseable for existing backups

---

#### Bug 10: DB Record Deleted Despite File Deletion Failure

| | |
|---|---|
| **Location** | `backup/services/retention_service.py:65-74` |
| **Status** | [x] Fixed |
| **Priority** | Warning |

**Description:**
When file deletion fails, the database record is still deleted.

**Current Code:**
```python
def _delete_backup(self, backup: BackupRecord):
    """Delete a backup file and record."""
    if backup.file_path:
        filepath = Path(backup.file_path)
        if filepath.exists():
            try:
                filepath.unlink()
            except OSError as e:
                logger.error(f"Failed to delete file {filepath}: {e}")
    backup.delete()  # Always deletes, even if file deletion failed!
```

**Impact:**
Orphaned files on disk, inconsistent backup history, storage consumption that can't be recovered.

**Fix Implementation:**

```python
def _delete_backup(self, backup: BackupRecord) -> bool:
    """
    Delete a backup file and record.

    Returns True if successfully deleted, False otherwise.
    """
    if backup.file_path:
        filepath = Path(backup.file_path)
        if filepath.exists():
            try:
                filepath.unlink()
            except OSError as e:
                logger.error(f"Failed to delete file {filepath}: {e}")
                # Don't delete DB record if file deletion failed
                return False

    # File deleted (or didn't exist), safe to delete record
    backup.delete()
    return True
```

**Update callers in enforce_retention:**
```python
def enforce_retention(self, config: PiholeConfig) -> int:
    """..."""
    deleted_count = 0

    # Delete by count (keep only max_backups)
    if config.max_backups > 0:
        excess_backups = backups[config.max_backups:]
        for backup in excess_backups:
            logger.info(f"Deleting backup (exceeds max count): {backup.filename}")
            if self._delete_backup(backup):
                deleted_count += 1
            # If deletion failed, it will be retried next run

    # ... similar for age-based deletion
```

**Testing:**
- Make backup file read-only and attempt deletion
- Verify DB record remains if file deletion fails
- Verify next retention run retries deletion

---

#### Bug 11: Non-Thread-Safe Singleton in Notification Settings

| | |
|---|---|
| **Location** | `backup/services/notifications/config.py:104-109` |
| **Status** | [x] Fixed |
| **Priority** | Warning |

**Description:**
The singleton pattern for `NotificationSettings` lacks thread safety.

**Current Code:**
```python
_settings: NotificationSettings | None = None

def get_notification_settings() -> NotificationSettings:
    """Get notification settings (cached singleton)."""
    global _settings
    if _settings is None:
        _settings = NotificationSettings()
    return _settings
```

**Impact:**
Multiple instances could be created in multi-threaded environment (Gunicorn with threads), wasting memory and potentially causing inconsistencies.

**Fix Implementation:**

```python
import threading

_settings: NotificationSettings | None = None
_settings_lock = threading.Lock()

def get_notification_settings() -> NotificationSettings:
    """Get notification settings (cached singleton, thread-safe)."""
    global _settings

    # Fast path: already initialized
    if _settings is not None:
        return _settings

    # Slow path: need to initialize with lock
    with _settings_lock:
        # Double-check after acquiring lock
        if _settings is None:
            _settings = NotificationSettings()
        return _settings


def reload_notification_settings() -> NotificationSettings:
    """Reload notification settings from environment (useful for testing)."""
    global _settings
    with _settings_lock:
        _settings = NotificationSettings()
        return _settings
```

**Testing:**
- Run app with multiple Gunicorn workers/threads
- Verify only one settings instance exists per process

---

#### Bug 12: Insufficient Filename Sanitization

| | |
|---|---|
| **Location** | `backup/services/backup_service.py:40-41` |
| **Status** | [x] Fixed |
| **Priority** | Warning |

**Description:**
Config name is used in filename with only space replacement, allowing path characters.

**Current Code:**
```python
safe_name = self.config.name.replace(" ", "_").lower()
return f"checkpoint_pihole_{safe_name}_{timestamp}.zip"
```

**Impact:**
Names like `../../etc/config` or `name/with/slashes` could cause issues on various filesystems or potentially path traversal.

**Fix Implementation:**

```python
import re

def _generate_filename(self) -> str:
    """Generate a unique filename for the backup."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    unique_suffix = uuid.uuid4().hex[:8]

    # Sanitize name: keep only alphanumeric, dash, underscore
    safe_name = re.sub(r'[^\w\-]', '_', self.config.name.lower())
    # Collapse multiple underscores
    safe_name = re.sub(r'_+', '_', safe_name)
    # Trim underscores from ends
    safe_name = safe_name.strip('_')
    # Fallback if name becomes empty
    safe_name = safe_name or 'pihole'

    return f"checkpoint_pihole_{safe_name}_{timestamp}_{unique_suffix}.zip"
```

**Alternative using Django's slugify:**
```python
from django.utils.text import slugify

def _generate_filename(self) -> str:
    """Generate a unique filename for the backup."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    unique_suffix = uuid.uuid4().hex[:8]

    # slugify handles unicode, special chars, etc.
    safe_name = slugify(self.config.name) or 'pihole'

    return f"checkpoint_pihole_{safe_name}_{timestamp}_{unique_suffix}.zip"
```

**Testing:**
- Create config with name `../../etc/passwd`
- Create config with name `Test / Pi-hole #1`
- Create config with name containing unicode: `Pi-hole 日本語`
- Verify all produce safe filenames

---

### Suggestions

Lower priority improvements for robustness.

---

#### Bug 13: Hourly Backups Use IntervalTrigger

| | |
|---|---|
| **Location** | `backup/management/commands/runapscheduler.py:105-107` |
| **Status** | [x] Fixed |
| **Priority** | Suggestion |

**Description:**
Hourly backups use `IntervalTrigger` which drifts based on server start time.

**Current Code:**
```python
if config.backup_frequency == "hourly":
    trigger = IntervalTrigger(hours=1)
    desc = "every hour"
```

**Impact:**
If server starts at 3:47, backups run at 3:47, 4:47, 5:47 instead of at the top of every hour. After container restarts, the hourly schedule shifts unpredictably.

**Fix Implementation:**

```python
if config.backup_frequency == "hourly":
    # Run at the top of every hour for consistent timing
    trigger = CronTrigger(minute=0)
    desc = "every hour at :00"
```

**Alternative (configurable minute):**
```python
if config.backup_frequency == "hourly":
    # Use the minute from backup_time for consistency
    minute = config.backup_time.minute if config.backup_time else 0
    trigger = CronTrigger(minute=minute)
    desc = f"every hour at :{minute:02d}"
```

**Testing:**
- Set hourly backup, restart container at random times
- Verify backups always run at consistent minute

---

#### Bug 14: Missing Timeout on Health Check Subprocess

| | |
|---|---|
| **Location** | `backup/views.py:197-202` |
| **Status** | [x] Fixed |
| **Priority** | Suggestion |

**Description:**
The `subprocess.run()` call to `pgrep` has no timeout specified.

**Current Code:**
```python
def health_check(request):
    """Health check endpoint for container orchestration."""
    import subprocess

    # Check if scheduler process is running
    result = subprocess.run(["pgrep", "-f", "runapscheduler"], capture_output=True)
    scheduler_running = result.returncode == 0
```

**Impact:**
Health checks could hang indefinitely under system load, causing orchestration issues.

**Fix Implementation:**

```python
import subprocess

def health_check(request):
    """Health check endpoint for container orchestration."""

    # Check if scheduler process is running
    try:
        result = subprocess.run(
            ["pgrep", "-f", "runapscheduler"],
            capture_output=True,
            timeout=5  # 5 second timeout
        )
        scheduler_running = result.returncode == 0
    except subprocess.TimeoutExpired:
        # If pgrep hangs, assume scheduler is having issues
        scheduler_running = False

    status = {
        "web": "ok",
        "scheduler": "ok" if scheduler_running else "not running",
        "database": "ok",
    }

    if not scheduler_running:
        return JsonResponse(status, status=503)

    return JsonResponse(status)
```

**Testing:**
- Verify health check returns quickly under normal conditions
- Verify health check doesn't hang when system is loaded

---

#### Bug 15: No Login Rate Limiting

| | |
|---|---|
| **Location** | `backup/views.py:175-188` |
| **Status** | [x] Fixed |
| **Priority** | Suggestion |

**Description:**
The login endpoint has no rate limiting.

**Current Code:**
```python
def login_view(request):
    """Login view for optional authentication."""
    if request.method == "POST":
        form = LoginForm(request.POST)
        if form.is_valid():
            if form.cleaned_data["password"] == settings.APP_PASSWORD:
                request.session["authenticated"] = True
                return redirect("dashboard")
            else:
                return render(request, "backup/login.html", {"error": "Invalid password"})
```

**Impact:**
Vulnerable to brute force password attacks.

**Fix Implementation (using Django cache):**

```python
from django.core.cache import cache
from django.http import HttpResponseTooManyRequests

def get_client_ip(request):
    """Get client IP from request."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')

def login_view(request):
    """Login view for optional authentication."""
    if request.method == "POST":
        client_ip = get_client_ip(request)
        cache_key = f"login_attempts_{client_ip}"

        # Check rate limit: 5 attempts per minute
        attempts = cache.get(cache_key, 0)
        if attempts >= 5:
            return HttpResponseTooManyRequests(
                "Too many login attempts. Please wait a minute."
            )

        form = LoginForm(request.POST)
        if form.is_valid():
            if form.cleaned_data["password"] == settings.APP_PASSWORD:
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
```

**Alternative (using django-ratelimit package):**
```python
# Add to requirements.txt: django-ratelimit

from django_ratelimit.decorators import ratelimit

@ratelimit(key='ip', rate='5/m', block=True)
def login_view(request):
    """Login view for optional authentication."""
    # ... existing code
```

**Testing:**
- Attempt 6+ failed logins within a minute
- Verify rate limit message appears
- Verify rate limit resets after timeout

---

#### Bug 16: Scheduler Process Not Auto-Restarted

| | |
|---|---|
| **Location** | `entrypoint.sh:12-14` |
| **Status** | [x] Fixed |
| **Priority** | Suggestion |

**Description:**
The scheduler runs in background but is not monitored or restarted if it crashes.

**Current Code:**
```bash
python manage.py runapscheduler &
SCHEDULER_PID=$!
echo "Scheduler started with PID: $SCHEDULER_PID"
```

**Impact:**
Scheduled backups silently stop working until container restart.

**Fix Implementation (simple monitoring loop):**

```bash
#!/bin/bash
set -e

echo "=== Checkpoint Pi-hole Starting ==="

# Run migrations
echo "[1/3] Running database migrations..."
python manage.py migrate --noinput

# Function to start scheduler
start_scheduler() {
    python manage.py runapscheduler &
    SCHEDULER_PID=$!
    echo "Scheduler started with PID: $SCHEDULER_PID"
}

# Start scheduler
echo "[2/3] Starting backup scheduler..."
start_scheduler

# Monitor and restart scheduler if it dies
monitor_scheduler() {
    while true; do
        sleep 30
        if ! kill -0 $SCHEDULER_PID 2>/dev/null; then
            echo "WARNING: Scheduler process died, restarting..."
            start_scheduler
        fi
    done
}

# Start monitor in background
monitor_scheduler &
MONITOR_PID=$!

# Trap signals to clean up
cleanup() {
    echo "Shutting down..."
    kill $MONITOR_PID 2>/dev/null || true
    kill $SCHEDULER_PID 2>/dev/null || true
    wait $SCHEDULER_PID 2>/dev/null || true
    exit 0
}
trap cleanup SIGTERM SIGINT

# Start Gunicorn (foreground)
echo "[3/3] Starting web server..."
exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 2 \
    --access-logfile - \
    --error-logfile -
```

**Alternative (using supervisord):**

Create `supervisord.conf`:
```ini
[supervisord]
nodaemon=true
logfile=/dev/stdout
logfile_maxbytes=0

[program:scheduler]
command=python manage.py runapscheduler
autorestart=true
startsecs=5
startretries=3
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0

[program:gunicorn]
command=gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 2 --access-logfile - --error-logfile -
autorestart=true
startsecs=5
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
```

Update `entrypoint.sh`:
```bash
#!/bin/bash
set -e
echo "=== Checkpoint Pi-hole Starting ==="
python manage.py migrate --noinput
exec supervisord -c /app/supervisord.conf
```

Update `Dockerfile`:
```dockerfile
RUN pip install supervisor
COPY supervisord.conf /app/
```

**Testing:**
- Kill scheduler process manually: `kill <scheduler_pid>`
- Verify it restarts automatically
- Check logs for restart messages

---

## Decision

Track all identified bugs in this ADR. Prioritize fixes in the following order:

### Phase 1: Critical Fixes (Immediate)
1. Bug 2: URL path stripping (breaks reverse proxy users)
2. Bug 3: Race condition (data integrity)
3. Bug 1: File handle leak (resource exhaustion)

### Phase 2: Security Hardening
4. Bug 6: Insecure default SECRET_KEY
5. Bug 7: ALLOWED_HOSTS wildcard default
6. Bug 15: Login rate limiting

### Phase 3: Data Integrity
7. Bug 10: File/DB deletion consistency
8. Bug 9: Timestamp collision prevention
9. Bug 12: Filename sanitization

### Phase 4: Robustness Improvements
10. Bug 4: Silent exception swallowing
11. Bug 5: ThreadPoolExecutor cleanup
12. Bug 8: Null check on config
13. Bug 11: Thread-safe singleton
14. Bug 13: Hourly backup timing
15. Bug 14: Health check timeout
16. Bug 16: Scheduler monitoring

---

## Consequences

### Positive
- Documented list of known issues for tracking
- Prioritized remediation plan
- Improved code quality and reliability after fixes
- Reduced risk of data loss and security issues

### Negative
- Development effort required to fix all issues
- Some fixes may require database migrations or breaking changes
- Testing effort to validate fixes

### Mitigations
- Implement fixes incrementally with tests
- Add regression tests for each bug fixed
- Review fixes in PRs before merging

---

## Progress Tracking

| Bug | Priority | Status | Fixed In |
|-----|----------|--------|----------|
| 1 | Critical | Fixed | fix/adr-11-bug-remediation |
| 2 | Critical | Fixed | fix/adr-11-bug-remediation |
| 3 | Critical | Fixed | fix/adr-11-bug-remediation |
| 4 | Warning | Fixed | fix/adr-11-bug-remediation |
| 5 | Warning | Fixed | fix/adr-11-bug-remediation |
| 6 | Warning | Fixed | fix/adr-11-bug-remediation |
| 7 | Warning | Fixed | fix/adr-11-bug-remediation |
| 8 | Warning | Fixed | fix/adr-11-bug-remediation |
| 9 | Warning | Fixed | fix/adr-11-bug-remediation |
| 10 | Warning | Fixed | fix/adr-11-bug-remediation |
| 11 | Warning | Fixed | fix/adr-11-bug-remediation |
| 12 | Warning | Fixed | fix/adr-11-bug-remediation |
| 13 | Suggestion | Fixed | fix/adr-11-bug-remediation |
| 14 | Suggestion | Fixed | fix/adr-11-bug-remediation |
| 15 | Suggestion | Fixed | fix/adr-11-bug-remediation |
| 16 | Suggestion | Fixed | fix/adr-11-bug-remediation |

---

## References

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [Django Security Best Practices](https://docs.djangoproject.com/en/5.0/topics/security/)
- [APScheduler Documentation](https://apscheduler.readthedocs.io/)
- [Django FileResponse](https://docs.djangoproject.com/en/5.0/ref/request-response/#fileresponse-objects)
- [Python threading](https://docs.python.org/3/library/threading.html)
