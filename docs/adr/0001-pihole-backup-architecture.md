# ADR-0001: Pi-hole v6 Backup Application Architecture

**Status:** Implemented
**Date:** 2026-01-18
**Deciders:** Project Owner

---

## Context

We need a self-hosted backup solution for Pi-hole v6 instances that:
- Runs in Docker for easy local deployment
- Provides a web UI for configuration and management
- Supports scheduled and manual backups
- Enforces retention policies
- Optionally protects the UI with password authentication

Pi-hole v6 introduces a new REST API with session-based authentication, replacing the static API keys used in v5.

---

## Decision

Build a Django 5.x web application with the following architecture:

### Technology Stack

| Component | Technology | Rationale |
|-----------|------------|-----------|
| Backend Framework | Django 5.x | Mature, batteries-included, excellent ORM |
| Database | SQLite | Simple, no separate service needed, sufficient for single-user |
| Task Scheduler | APScheduler + django-apscheduler | Simpler than Celery, no Redis/RabbitMQ required |
| Frontend | Django Templates + Bootstrap 5 | Server-rendered, minimal JS, fast development |
| Secret Storage | django-encrypted-model-fields | Encrypt Pi-hole password at rest |
| Containerization | Docker + Docker Compose | Standard deployment, easy setup |
| Web Server | Gunicorn | Production-ready WSGI server |

### Key Architectural Decisions

#### 1. APScheduler over Celery

**Decision:** Use APScheduler with django-apscheduler instead of Celery.

**Rationale:**
- Single-user local deployment doesn't need distributed task queue
- Eliminates Redis/RabbitMQ dependency (fewer containers)
- Simpler configuration and debugging
- Built-in Django admin integration for job monitoring
- Sufficient for hourly/daily/weekly backup schedules

**Tradeoffs:**
- Less scalable than Celery (acceptable for single-user use case)
- BlockingScheduler requires dedicated container

#### 2. Pi-hole v6 Only (No v5 Support)

**Decision:** Support only Pi-hole v6 API, not v5.

**Rationale:**
- Pi-hole v6 is current/recommended version
- v6 API is completely different (session-based vs API keys)
- Reduces complexity and maintenance burden
- Users on v5 can upgrade to v6

**Tradeoffs:**
- Users with v5 cannot use this application

#### 3. Session-Based Authentication with Pi-hole

**Decision:** Implement proper session management with automatic re-authentication.

**Pi-hole v6 API Flow:**
```
1. POST /api/auth {"password": "..."}
   → Returns: {"session": {"sid": "base64...", "validity": 300}}

2. GET /api/teleporter
   Headers: X-FTL-SID: <sid>
   → Returns: application/zip
```

**Implementation Details:**
- Store session ID in client instance
- Sessions expire after ~300 seconds (configurable in Pi-hole)
- Re-authenticate automatically on 401 responses
- Handle self-signed SSL certificates (common in home setups)

#### 4. Two-Container Architecture

**Decision:** Separate web and scheduler into distinct containers.

```
┌─────────────────┐     ┌─────────────────┐
│   web           │     │   scheduler     │
│   (gunicorn)    │     │   (apscheduler) │
│   Port 8000     │     │                 │
└────────┬────────┘     └────────┬────────┘
         │                       │
         └───────────┬───────────┘
                     │
              ┌──────┴──────┐
              │   Volumes   │
              │  - data/    │
              │  - backups/ │
              └─────────────┘
```

**Rationale:**
- APScheduler's BlockingScheduler needs dedicated process
- Prevents duplicate job execution from multiple Gunicorn workers
- Clear separation of concerns
- Independent restart/scaling

#### 5. Single-Instance with Multi-Instance Ready Models

**Decision:** Design models to support multiple Pi-hole instances, but UI initially supports only one.

**Model Design:**
```python
class PiholeConfig(models.Model):
    name = models.CharField(...)  # For future multi-instance
    pihole_url = models.URLField(...)
    # ... other fields

class BackupRecord(models.Model):
    config = models.ForeignKey(PiholeConfig, ...)  # Ready for multi-instance
    filename = models.CharField(...)
    # ... other fields
```

**Rationale:**
- Minimal overhead for current use
- Easy migration path when multi-instance is needed
- Better data organization even for single instance

#### 6. Optional Password Authentication

**Decision:** Environment variable-controlled middleware for optional UI protection.

**Configuration:**
```bash
REQUIRE_AUTH=true
APP_PASSWORD=your-secure-password
```

**Rationale:**
- Many users run on trusted local networks
- Some want protection similar to Pi-hole itself
- Simple password (no user management) matches Pi-hole UX
- Easy to enable/disable without code changes

---

## Project Structure

```
checkpoint-pihole/
├── docker-compose.yml          # Container orchestration
├── Dockerfile                  # Application image
├── requirements.txt            # Python dependencies
├── .env.example               # Environment template
├── manage.py
│
├── config/                     # Django project settings
│   ├── __init__.py
│   ├── settings.py            # Main config with env vars
│   ├── urls.py                # Root URL routing
│   └── wsgi.py
│
├── backup/                     # Main Django app
│   ├── models.py              # PiholeConfig, BackupRecord
│   ├── views.py               # Dashboard, Settings, API views
│   ├── forms.py               # ConfigForm, LoginForm
│   ├── urls.py                # App URL patterns
│   ├── admin.py               # Admin registration
│   │
│   ├── services/              # Business logic layer
│   │   ├── pihole_client.py   # Pi-hole v6 API client
│   │   ├── backup_service.py  # Backup operations
│   │   └── retention_service.py # Cleanup logic
│   │
│   ├── middleware/
│   │   └── simple_auth.py     # Optional password protection
│   │
│   ├── management/commands/
│   │   └── runapscheduler.py  # Scheduler entry point
│   │
│   └── templates/backup/
│       ├── base.html          # Bootstrap 5 layout
│       ├── dashboard.html     # Main view
│       ├── settings.html      # Configuration form
│       └── login.html         # Auth page
│
├── docs/                       # Documentation
│   └── adr-001-*.md           # This document
│
├── data/                       # SQLite database (volume)
└── backups/                    # Backup files (volume)
```

---

## Data Models

### PiholeConfig

Stores Pi-hole connection and backup schedule configuration.

| Field | Type | Description |
|-------|------|-------------|
| `id` | AutoField | Primary key |
| `name` | CharField(100) | Instance name, default "Primary Pi-hole" |
| `pihole_url` | URLField | Base URL (e.g., https://192.168.1.100) |
| `password` | EncryptedCharField(255) | Pi-hole web password, encrypted at rest |
| `verify_ssl` | BooleanField | SSL verification, default False |
| `backup_frequency` | CharField(20) | Choices: hourly, daily, weekly |
| `backup_time` | TimeField | Time for daily/weekly backups, default 03:00 |
| `backup_day` | SmallIntegerField | Day of week (0=Mon, 6=Sun) for weekly |
| `max_backups` | PositiveIntegerField | Max backups to keep, default 10 |
| `max_age_days` | PositiveIntegerField | Max age in days, default 30 |
| `is_active` | BooleanField | Enable scheduled backups |
| `last_successful_backup` | DateTimeField | Timestamp of last success |
| `last_backup_error` | TextField | Last error message |
| `created_at` | DateTimeField | Auto-set on create |
| `updated_at` | DateTimeField | Auto-set on save |

### BackupRecord

Tracks individual backup files.

| Field | Type | Description |
|-------|------|-------------|
| `id` | AutoField | Primary key |
| `config` | ForeignKey(PiholeConfig) | Parent configuration |
| `filename` | CharField(255) | Generated filename |
| `file_path` | CharField(500) | Full path on disk |
| `file_size` | BigIntegerField | Size in bytes |
| `checksum` | CharField(64) | SHA256 hash |
| `status` | CharField(20) | Choices: success, failed |
| `is_manual` | BooleanField | True if UI-triggered |
| `error_message` | TextField | Error details if failed |
| `created_at` | DateTimeField | Backup timestamp |

---

## Service Layer Design

### PiholeV6Client

Handles all communication with Pi-hole v6 API.

```python
class PiholeV6Client:
    def __init__(self, base_url: str, password: str, verify_ssl: bool = False)

    def authenticate(self) -> Tuple[bool, str]
        """POST /api/auth, store session.sid"""

    def test_connection(self) -> Tuple[bool, str]
        """Auth + GET /api/info/version"""

    def download_teleporter_backup(self) -> Tuple[Optional[bytes], str]
        """GET /api/teleporter with X-FTL-SID header"""

    def logout(self) -> None
        """DELETE /api/auth"""
```

**Error Handling:**
- SSL errors → Suggest disabling verification
- Connection errors → Clear message with URL
- 401 Unauthorized → "Invalid password"
- Session expiry → Auto re-authenticate once

### BackupService

Orchestrates backup creation and deletion.

```python
class BackupService:
    def __init__(self, config: PiholeConfig)

    def create_backup(self, is_manual: bool = False) -> Tuple[Optional[BackupRecord], str]
        """
        1. Create PiholeV6Client
        2. Download teleporter backup
        3. Save to filesystem
        4. Calculate SHA256 checksum
        5. Create BackupRecord
        6. Update config.last_successful_backup
        7. Return record and message
        """

    @staticmethod
    def delete_backup(record: BackupRecord) -> Tuple[bool, str]
        """Delete file and database record"""
```

### RetentionService

Enforces backup retention policies.

```python
class RetentionService:
    @staticmethod
    def enforce_retention(config: PiholeConfig) -> dict
        """
        1. Get backups ordered by date (newest first)
        2. Delete backups exceeding max_backups count
        3. Delete backups exceeding max_age_days
        4. Return deletion counts
        """

    @staticmethod
    def enforce_all_retention() -> dict
        """Run retention for all active configs"""

    @staticmethod
    def cleanup_orphaned_files(backup_dir: str) -> int
        """Remove files without database records"""
```

---

## URL Structure

| URL | View | Method | Description |
|-----|------|--------|-------------|
| `/` | DashboardView | GET | Main dashboard |
| `/settings/` | SettingsView | GET/POST | Configuration form |
| `/settings/test-connection/` | test_connection | POST | AJAX connection test |
| `/backup/create/` | create_backup | POST | Trigger manual backup |
| `/backup/<id>/download/` | download_backup | GET | Download backup file |
| `/backup/<id>/delete/` | delete_backup | POST | Delete backup |
| `/login/` | LoginView | GET/POST | Authentication |
| `/logout/` | logout_view | POST | Clear session |
| `/api/status/` | api_status | GET | AJAX status refresh |
| `/api/backups/` | api_backup_list | GET | AJAX backup list |

---

## Scheduler Configuration

### Jobs

| Job ID | Schedule | Function |
|--------|----------|----------|
| `backup_job` | Based on config (hourly/daily/weekly) | `scheduled_backup_job()` |
| `retention_cleanup` | Daily at 04:00 | `retention_cleanup_job()` |

### Trigger Mapping

| Frequency | APScheduler Trigger |
|-----------|---------------------|
| hourly | `IntervalTrigger(hours=1)` |
| daily | `CronTrigger(hour=X, minute=Y)` |
| weekly | `CronTrigger(day_of_week=D, hour=X, minute=Y)` |

### Dynamic Rescheduling

When settings are saved via the UI, call `reschedule_backup_job()` to update the scheduler with new timing.

---

## Docker Configuration

### docker-compose.yml

```yaml
version: '3.8'

services:
  web:
    build: .
    container_name: checkpoint-pihole-web
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data
      - ./backups:/app/backups
    environment:
      - SECRET_KEY=${SECRET_KEY}
      - FIELD_ENCRYPTION_KEY=${FIELD_ENCRYPTION_KEY}
      - DEBUG=${DEBUG:-0}
      - ALLOWED_HOSTS=${ALLOWED_HOSTS:-localhost,127.0.0.1}
      - TIME_ZONE=${TIME_ZONE:-UTC}
      - APP_PASSWORD=${APP_PASSWORD:-}
      - REQUIRE_AUTH=${REQUIRE_AUTH:-false}
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/"]
      interval: 30s
      timeout: 10s
      retries: 3

  scheduler:
    build: .
    container_name: checkpoint-pihole-scheduler
    command: python manage.py runapscheduler
    volumes:
      - ./data:/app/data
      - ./backups:/app/backups
    environment:
      - SECRET_KEY=${SECRET_KEY}
      - FIELD_ENCRYPTION_KEY=${FIELD_ENCRYPTION_KEY}
      - TIME_ZONE=${TIME_ZONE:-UTC}
    depends_on:
      web:
        condition: service_healthy
    restart: unless-stopped
```

### Dockerfile

```dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends gcc curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd -m -u 1000 appuser \
    && mkdir -p /app/data /app/backups \
    && chown -R appuser:appuser /app

USER appuser

RUN python manage.py collectstatic --noinput

CMD ["sh", "-c", "python manage.py migrate && gunicorn config.wsgi:application --bind 0.0.0.0:8000"]

EXPOSE 8000
```

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SECRET_KEY` | Yes | - | Django secret key |
| `FIELD_ENCRYPTION_KEY` | Yes | - | 32-char encryption key for passwords |
| `DEBUG` | No | 0 | Enable debug mode |
| `ALLOWED_HOSTS` | No | localhost,127.0.0.1 | Allowed host headers |
| `TIME_ZONE` | No | UTC | Timezone for scheduler |
| `REQUIRE_AUTH` | No | false | Enable UI authentication |
| `APP_PASSWORD` | No | - | Password for UI auth |

---

## Security Considerations

### Password Storage
- Pi-hole password encrypted at rest using `django-encrypted-model-fields`
- Encryption key stored in environment variable, not in code
- Password never displayed in UI (masked input)

### Web Security
- CSRF protection on all forms
- Session-based authentication with secure cookies
- `SESSION_COOKIE_HTTPONLY = True`
- Container runs as non-root user (uid 1000)

### Network Security
- No default authentication (local network assumption)
- Optional password protection available
- HTTPS recommended for remote access (reverse proxy)

---

## Dependencies

```
# requirements.txt
Django>=5.0,<6.0
gunicorn>=21.0
requests>=2.31
django-encrypted-model-fields>=0.6
django-apscheduler>=0.6
APScheduler>=3.10,<4.0
python-dotenv>=1.0
```

---

## Implementation Phases

### Phase 1: Project Foundation
- Initialize Django project structure
- Configure settings with environment variables
- Create Dockerfile and docker-compose.yml
- Test container builds

### Phase 2: Models & Database
- Implement PiholeConfig with encrypted password
- Implement BackupRecord
- Create migrations
- Register in admin

### Phase 3: Service Layer
- Implement PiholeV6Client with session auth
- Implement BackupService
- Implement RetentionService

### Phase 4: Web UI
- Create Bootstrap 5 base template
- Build dashboard (status, backup table)
- Build settings page (config form)
- Add AJAX for backup/delete/test

### Phase 5: Scheduler
- Configure django-apscheduler
- Create runapscheduler command
- Implement backup and retention jobs
- Add scheduler to docker-compose

### Phase 6: Polish
- Implement optional authentication
- Add error handling and messages
- Create .env.example and README

---

## Verification Checklist

- [ ] `docker-compose up --build` starts both containers
- [ ] Web UI accessible at http://localhost:8000
- [ ] Settings form saves Pi-hole URL and password
- [ ] "Test Connection" returns Pi-hole version
- [ ] "Backup Now" creates ZIP file in ./backups/
- [ ] Backup table shows file with correct size
- [ ] Download button returns the ZIP file
- [ ] Delete button removes file and record
- [ ] Scheduled backup runs at configured time
- [ ] Retention deletes oldest when max_backups exceeded
- [ ] REQUIRE_AUTH=true requires login

---

## References

- [Pi-hole v6 API Documentation](https://docs.pi-hole.net/api/)
- [Pi-hole API Authentication](https://docs.pi-hole.net/api/auth/)
- [django-apscheduler](https://github.com/jcass77/django-apscheduler)
- [django-encrypted-model-fields](https://pypi.org/project/django-encrypted-model-fields/)
