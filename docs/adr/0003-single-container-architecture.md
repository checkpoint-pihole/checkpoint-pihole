# ADR-0003: Single Container Architecture

**Status:** Implemented
**Date:** 2026-01-18
**Implemented:** 2026-01-18
**Deciders:** Project Owner

---

## Context

Prior to this ADR, the Checkpoint Pi-hole deployment used three Docker services:

| Service | Purpose | Command |
|---------|---------|---------|
| `migrate` | Run database migrations | `python manage.py makemigrations && migrate` |
| `web` | Serve Django via Gunicorn | `gunicorn config.wsgi:application` |
| `scheduler` | Run APScheduler for backups | `python manage.py runapscheduler` |

This creates operational complexity:
1. **Three separate containers** to manage, monitor, and troubleshoot
2. **Build redundancy** - same image built/pulled multiple times
3. **Orchestration complexity** - `depends_on` chains and health checks
4. **Resource overhead** - each container has its own Python runtime
5. **Log fragmentation** - logs split across multiple containers

For a single-user, self-hosted application like Checkpoint Pi-hole, this multi-container approach is over-engineered.

---

## Decision

Consolidate all functionality into a **single container** using one of the approaches below.

---

## Options Considered

### Option 1: Entrypoint Script with Sequential Startup (Recommended)

Run migrations, start the scheduler in the background, then start Gunicorn - all in a single entrypoint script.

**Implementation:**

```bash
#!/bin/bash
# entrypoint.sh

set -e

# Run migrations
echo "Running migrations..."
python manage.py migrate --noinput

# Start scheduler in background
echo "Starting scheduler..."
python manage.py runapscheduler &
SCHEDULER_PID=$!

# Start Gunicorn (foreground)
echo "Starting Gunicorn..."
exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 2 \
    --access-logfile - \
    --error-logfile -
```

**Pros:**
- Simplest implementation
- No code changes to scheduler
- All processes visible via `docker exec ps`
- Scheduler runs as separate process (no GIL concerns)

**Cons:**
- Background process not directly managed by init system
- If scheduler crashes, container continues (but backups stop)

**Mitigation:** Add health check that verifies scheduler process is running.

---

### Option 2: BackgroundScheduler in Gunicorn Worker

Replace `BlockingScheduler` with `BackgroundScheduler` and start it within the Django application.

**Implementation:**

```python
# backup/apps.py
from django.apps import AppConfig

class BackupConfig(AppConfig):
    name = 'backup'

    def ready(self):
        # Only run in main process, not in each worker
        import os
        if os.environ.get('RUN_MAIN') or os.environ.get('SCHEDULER_ENABLED'):
            from backup.scheduler import start_scheduler
            start_scheduler()
```

```python
# backup/scheduler.py
from apscheduler.schedulers.background import BackgroundScheduler

scheduler = None

def start_scheduler():
    global scheduler
    if scheduler is None:
        scheduler = BackgroundScheduler()
        # ... add jobs
        scheduler.start()
```

**Pros:**
- Single Python process
- Cleaner architecture
- No external process management

**Cons:**
- Complex Gunicorn worker coordination (avoid duplicate schedulers)
- GIL contention with web requests
- Requires `--preload` flag and careful worker management
- Scheduler restarts with every worker recycle

---

### Option 3: Supervisord Process Manager

Use supervisord to manage multiple processes within a single container.

**Implementation:**

```ini
# supervisord.conf
[supervisord]
nodaemon=true

[program:migrate]
command=python manage.py migrate --noinput
autorestart=false
startsecs=0
priority=1

[program:gunicorn]
command=gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 2
autorestart=true
priority=10

[program:scheduler]
command=python manage.py runapscheduler
autorestart=true
priority=10
```

**Pros:**
- Proper process management with automatic restarts
- Industry standard for multi-process containers
- Clean separation of concerns

**Cons:**
- Adds supervisord dependency (~5MB)
- Additional configuration file
- More complex Dockerfile
- Overkill for two long-running processes

---

### Option 4: S6-Overlay

Use s6-overlay as the init system and process supervisor.

**Pros:**
- Lightweight and Docker-native
- Proper signal handling
- Used by popular images (linuxserver.io)

**Cons:**
- Steeper learning curve
- More complex setup than entrypoint script
- Overkill for this use case

---

## Recommendation: Option 1 (Entrypoint Script)

Option 1 provides the best balance of simplicity and reliability for this application:

1. **Minimal changes** - Keep existing scheduler code unchanged
2. **Simple to understand** - Just a bash script
3. **Easy to debug** - `docker exec` shows both processes
4. **No new dependencies** - Uses standard shell features

The main risk (scheduler crashing silently) can be mitigated with a health check endpoint.

---

## Implementation Plan

### 1. Create Entrypoint Script

Create `entrypoint.sh`:

```bash
#!/bin/bash
set -e

echo "=== Checkpoint Pi-hole Starting ==="

# Run migrations
echo "[1/3] Running database migrations..."
python manage.py migrate --noinput

# Start scheduler in background
echo "[2/3] Starting backup scheduler..."
python manage.py runapscheduler &
SCHEDULER_PID=$!
echo "Scheduler started with PID: $SCHEDULER_PID"

# Trap signals to clean up scheduler
cleanup() {
    echo "Shutting down..."
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

### 2. Update Dockerfile

```dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data /app/backups /app/staticfiles

RUN python manage.py collectstatic --noinput

# Make entrypoint executable
RUN chmod +x /app/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
```

### 3. Simplify docker-compose.yml

```yaml
services:
  checkpoint-pihole:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data
      - ./backups:/app/backups
    environment:
      - SECRET_KEY=${SECRET_KEY:-change-me-in-production-use-long-random-string}
      - FIELD_ENCRYPTION_KEY=${FIELD_ENCRYPTION_KEY:-change-this-key-to-32-chars!}
      - TIME_ZONE=${TIME_ZONE:-UTC}
      - REQUIRE_AUTH=${REQUIRE_AUTH:-false}
      - APP_PASSWORD=${APP_PASSWORD:-}
      - DEBUG=${DEBUG:-false}
      - ALLOWED_HOSTS=${ALLOWED_HOSTS:-localhost,127.0.0.1}
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/"]
      interval: 30s
      timeout: 10s
      retries: 3
```

### 4. Optional: Add Scheduler Health Check

Add an endpoint to verify the scheduler is running:

```python
# backup/views.py
def health_check(request):
    """Health check endpoint for container orchestration."""
    import subprocess

    # Check if scheduler process is running
    result = subprocess.run(['pgrep', '-f', 'runapscheduler'], capture_output=True)
    scheduler_running = result.returncode == 0

    status = {
        'web': 'ok',
        'scheduler': 'ok' if scheduler_running else 'not running',
        'database': 'ok',  # Django handles DB connection
    }

    if not scheduler_running:
        return JsonResponse(status, status=503)

    return JsonResponse(status)
```

---

## Migration Path

1. Create `entrypoint.sh` in project root
2. Update `Dockerfile` to use entrypoint
3. Update `docker-compose.yml` to single service
4. Update `CLAUDE.md` documentation
5. Test: `docker compose down && docker compose up --build`
6. Verify:
   - Web UI accessible at http://localhost:8000
   - Scheduled backups execute
   - Manual backups work
   - Logs show both scheduler and gunicorn output

---

## Rollback Plan

If issues arise, revert to the three-service architecture by:
1. Restoring original `docker-compose.yml`
2. Restoring original `Dockerfile` CMD
3. Removing `entrypoint.sh`

---

## Consequences

### Positive

- **Simpler deployment**: Single container to manage
- **Faster startup**: No orchestration delays
- **Unified logs**: All output in one stream
- **Lower resource usage**: Single Python runtime overhead
- **Easier debugging**: One container to inspect

### Negative

- **Process coupling**: If Gunicorn dies, scheduler also stops (acceptable - container restarts anyway)
- **No independent scaling**: Can't scale web separately from scheduler (not needed for single-user app)

### Neutral

- Image size unchanged
- Memory usage similar (Python processes share libraries via copy-on-write)

---

## Verification Checklist

- [x] `docker compose up --build` starts single container
- [x] Logs show migrations, scheduler start, and gunicorn start
- [x] Web UI accessible at http://localhost:8000
- [x] `docker exec <container> ps aux` shows both gunicorn and runapscheduler
- [ ] Scheduled backup executes at configured time
- [ ] Manual "Backup Now" works from UI
- [x] `docker compose down` cleanly stops all processes
- [ ] Container restarts successfully after `docker restart`

---

## Implementation Notes

Option 1 (Entrypoint Script) was implemented with the following files:

| File | Changes |
|------|---------|
| `entrypoint.sh` | Created - runs migrations, starts scheduler in background, starts Gunicorn |
| `Dockerfile` | Added `curl` and `procps` packages, changed CMD to ENTRYPOINT |
| `docker-compose.yml` | Consolidated 3 services into single `checkpoint-pihole` service |
| `backup/views.py` | Added `health_check()` endpoint at `/health/` |
| `backup/urls.py` | Added route for health check |
| `backup/middleware/simple_auth.py` | Excluded `/health/` from authentication |
| `CLAUDE.md` | Updated to reflect single-container architecture |

The health check endpoint verifies the scheduler process is running via `pgrep` and returns HTTP 503 if not found, allowing Docker to detect and restart unhealthy containers.

---

## References

- [Docker Best Practices: Single vs Multi-Process](https://docs.docker.com/config/containers/multi-service_container/)
- [APScheduler Documentation](https://apscheduler.readthedocs.io/)
- [Gunicorn Deployment](https://docs.gunicorn.org/en/stable/deploy.html)
