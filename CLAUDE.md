# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Checkpoint Pi-hole is a Django 5.x web application for backing up Pi-hole v6 instances via the Teleporter API. It runs as a single Docker container with both the web UI (Gunicorn) and scheduler (APScheduler).

**Pi-hole v6 only** - Uses session-based authentication (not v5 API keys).

## Development Commands

```bash
# Build and start
docker compose up --build

# Start in detached mode
docker compose up -d

# View logs
docker compose logs -f checkpoint-pihole

# Run Django management commands
docker compose exec checkpoint-pihole python manage.py <command>

# Run migrations manually
docker compose exec checkpoint-pihole python manage.py migrate

# Create a Django shell
docker compose exec checkpoint-pihole python manage.py shell

# Stop services
docker compose down
```

Web UI available at http://localhost:8000 after startup.

## Local Development with uv

This project uses [uv](https://docs.astral.sh/uv/) for Python virtual environment management, testing, and linting.

```bash
# Run tests
uv run pytest

# Run linting
uv run ruff check .

# Run formatter check
uv run ruff format --check .

# Fix linting issues
uv run ruff check --fix .

# Format code
uv run ruff format .
```

## Architecture

### Single-Container Design
The application runs in a single container via `entrypoint.sh`:
1. Runs database migrations
2. Starts APScheduler in background (`python manage.py runapscheduler`)
3. Starts Gunicorn in foreground (port 8000)

Data is persisted via volumes: SQLite database (`./data/db.sqlite3`) and backup storage (`./backups/`).

### Service Layer (`backup/services/`)
Business logic is separated from views:
- `pihole_client.py`: Pi-hole v6 API client with session management. Authenticates via `POST /api/auth`, downloads backups via `GET /api/teleporter` with `X-FTL-SID` header.
- `backup_service.py`: Orchestrates backup creation/deletion. Saves ZIP files to `/app/backups/`, creates `BackupRecord` entries.
- `retention_service.py`: Enforces `max_backups` count and `max_age_days` policies.

### Models (`backup/models.py`)
- `PiholeConfig`: Stores backup schedule settings and `env_prefix` for credential lookup. Supports multiple Pi-hole instances. Credentials are read from environment variables (`PIHOLE_{PREFIX}_URL`, `PIHOLE_{PREFIX}_PASSWORD`).
- `BackupRecord`: Tracks backup files with checksum, status, and relationship to config.

### Scheduler (`backup/management/commands/runapscheduler.py`)
- Uses `BlockingScheduler` with `DjangoJobStore`
- Schedules backup jobs based on `PiholeConfig.backup_frequency` (hourly/daily/weekly)
- Retention cleanup runs daily at 4:00 AM
- Refreshes schedules every 5 minutes to pick up config changes

## Environment Variables

Pi-hole credentials use the env prefix pattern (see `.env.example`):
- `PIHOLE_{PREFIX}_URL`: Pi-hole URL (e.g., `PIHOLE_PRIMARY_URL`)
- `PIHOLE_{PREFIX}_PASSWORD`: Pi-hole admin password (e.g., `PIHOLE_PRIMARY_PASSWORD`)
- `PIHOLE_{PREFIX}_VERIFY_SSL`: SSL verification (default: false)

Optional:
- `SECRET_KEY`: Django secret key (auto-generated if not set)
- `TIME_ZONE`: Scheduler timezone (default: UTC)
- `REQUIRE_AUTH`/`APP_PASSWORD`: Enable simple password auth for web UI
- `DEBUG`, `ALLOWED_HOSTS`

## Key Files

| File | Purpose |
|------|---------|
| `entrypoint.sh` | Container entrypoint: migrations, scheduler, gunicorn |
| `backup/views.py` | Dashboard, settings form, AJAX endpoints for backup/delete/test |
| `backup/forms.py` | `PiholeConfigForm`, `LoginForm` |
| `backup/middleware/simple_auth.py` | Optional password protection middleware |
| `config/settings.py` | Django settings with env var configuration |

## Documentation

- [Feature Ideas](docs/IDEAS.md) - Potential features and improvements for the project
