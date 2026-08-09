<p align="center">
  <img width="896" height="467" alt="Checkpoint Pi-hole logo" src="https://github.com/user-attachments/assets/ad0caaa2-e052-438e-89f1-d6fcccfc2bf6" />
</p>

# Checkpoint Pi-hole

<p align="center">
<img src="https://img.shields.io/github/stars/checkpoint-pihole/checkpoint-pihole?style=for-the-badge&label=Stars&color=orange" alt="Stars">
<a href="https://github.com/checkpoint-pihole/checkpoint-pihole/releases/latest"><img src="https://img.shields.io/github/v/release/checkpoint-pihole/checkpoint-pihole?style=for-the-badge&color=purple" alt="Version"></a>
<a href="https://github.com/checkpoint-pihole/checkpoint-pihole/actions/workflows/build-and-push.yml"><img src="https://img.shields.io/github/actions/workflow/status/checkpoint-pihole/checkpoint-pihole/build-and-push.yml?style=for-the-badge&label=Build" alt="Build"></a>
<a href="https://github.com/checkpoint-pihole/checkpoint-pihole/blob/main/LICENSE"><img src="https://img.shields.io/github/license/checkpoint-pihole/checkpoint-pihole?style=for-the-badge&label=License&color=green" alt="License"></a>
</p>

<p align="center">
<a href="https://www.buymeacoffee.com/JMISm06AD"><img src="https://img.shields.io/badge/Buy%20Me%20A%20Coffee-FFDD00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black" alt="Buy Me A Coffee"></a>
</p>

A web application for backing up Pi-hole v6 instances via the Teleporter API. Runs as a single Docker container with a web UI and automated scheduler.

**Requires Pi-hole v6** - Uses session-based authentication (not compatible with v5 API keys).

## Features

- Automated scheduled backups (hourly, daily, or weekly)
- Manual backup on demand
- One-click restore to Pi-hole
- Backup retention policies (by count and age)
- Failure notifications (Discord, Slack, Telegram, Pushbullet, Home Assistant)
- Optional web UI authentication

## Quick Start

1. Create a `docker-compose.yml`:
   ```yaml
   services:
     checkpoint-pihole:
       image: ghcr.io/checkpoint-pihole/checkpoint-pihole:latest
       ports:
         - "8000:8000"
       volumes:
         - ./data:/app/data
         - ./backups:/app/backups
       environment:
         - PIHOLE_PRIMARY_URL=http://192.168.1.100
         - PIHOLE_PRIMARY_PASSWORD=your-pihole-admin-password
       restart: unless-stopped
   ```

2. Start the container:
   ```bash
   docker compose up -d
   ```

3. Open http://localhost:8000 to view the dashboard and manage backups.

## Multi-Instance Support

Instances are auto-discovered from environment variables on startup. Set `PIHOLE_{PREFIX}_URL` and `PIHOLE_{PREFIX}_PASSWORD` for each Pi-hole — the prefix can be anything you choose (e.g., `GYM`, `BONUS`, `HOME_OFFICE`).

```yaml
environment:
  - PIHOLE_GYM_URL=https://192.168.1.186
  - PIHOLE_GYM_PASSWORD=${PIHOLE_PASSWORD}
  - PIHOLE_GYM_VERIFY_SSL=false
  - PIHOLE_BONUS_URL=https://192.168.1.189
  - PIHOLE_BONUS_PASSWORD=${PIHOLE_PASSWORD}
  - PIHOLE_BONUS_VERIFY_SSL=false
```

On first startup, a `PiholeConfig` record is automatically created for each discovered prefix (e.g., "Gym", "Bonus"). Existing configs are not overwritten on subsequent restarts.

> **Note:** If a previously configured `PIHOLE_{PREFIX}_URL` is removed from the environment, the instance is marked as "Removed" on the next restart. Scheduled backups stop, but existing backups are retained and can still be downloaded or deleted individually.

## Environment Variables

### Per-Instance (auto-discovered)

| Variable | Required | Description |
|----------|----------|-------------|
| `PIHOLE_{PREFIX}_URL` | Yes | Pi-hole admin URL |
| `PIHOLE_{PREFIX}_PASSWORD` | Yes | Pi-hole admin password |
| `PIHOLE_{PREFIX}_VERIFY_SSL` | No | Verify SSL certificates (default: false) |
| `PIHOLE_{PREFIX}_NAME` | No | Display name (default: auto-generated from prefix) |
| `PIHOLE_{PREFIX}_SCHEDULE` | No | Backup frequency: `hourly`, `daily`, `weekly` (default: daily) |
| `PIHOLE_{PREFIX}_TIME` | No | Backup time for daily/weekly (default: 03:00) |
| `PIHOLE_{PREFIX}_DAY` | No | Day for weekly backups, 0=Mon..6=Sun (default: 0) |
| `PIHOLE_{PREFIX}_MAX_BACKUPS` | No | Max backups to keep (default: 10) |
| `PIHOLE_{PREFIX}_MAX_AGE_DAYS` | No | Delete backups older than N days (default: 30) |

### Global

| Variable | Required | Description |
|----------|----------|-------------|
| `TIME_ZONE` | No | Scheduler timezone (default: UTC) |
| `REQUIRE_AUTH` | No | Enable web UI password protection (default: false) |
| `APP_PASSWORD` | No | Password for web UI when `REQUIRE_AUTH=true` |
| `DEBUG` | No | Enable debug mode (default: false) |
| `ALLOWED_HOSTS` | No | Comma-separated allowed hosts (default: localhost,127.0.0.1) |

## Notifications

Get notified when backups fail. Configure via environment variables:

| Variable | Description |
|----------|-------------|
| `NOTIFY_ON_FAILURE` | Enable failure notifications (default: true) |
| `NOTIFY_ON_SUCCESS` | Enable success notifications (default: false) |
| `NOTIFY_DISCORD_ENABLED` | Enable Discord notifications |
| `NOTIFY_DISCORD_WEBHOOK_URL` | Discord webhook URL |
| `NOTIFY_SLACK_ENABLED` | Enable Slack notifications |
| `NOTIFY_SLACK_WEBHOOK_URL` | Slack webhook URL |
| `NOTIFY_TELEGRAM_ENABLED` | Enable Telegram notifications |
| `NOTIFY_TELEGRAM_BOT_TOKEN` | Telegram bot token |
| `NOTIFY_TELEGRAM_CHAT_ID` | Telegram chat ID |
| `NOTIFY_PUSHBULLET_ENABLED` | Enable Pushbullet notifications |
| `NOTIFY_PUSHBULLET_API_KEY` | Pushbullet API key |
| `NOTIFY_HOMEASSISTANT_ENABLED` | Enable Home Assistant notifications |
| `NOTIFY_HOMEASSISTANT_URL` | Home Assistant URL |
| `NOTIFY_HOMEASSISTANT_WEBHOOK_ID` | Webhook ID (or use `_TOKEN` for API) |

## Metrics

A Prometheus-compatible scrape endpoint is exposed at `/metrics/` (auth-exempt, text exposition format). The path also works without the trailing slash for Prometheus's default `metrics_path`. See [ADR-0016](docs/adr/0016-prometheus-metrics-endpoint.md) for the design.

Example scrape config:

```yaml
scrape_configs:
  - job_name: checkpoint-pihole
    static_configs:
      - targets: ["checkpoint-pihole:8000"]
```

Exposed metrics (all prefixed `pihole_`):

- `pihole_info{version}` — build info
- `pihole_scheduler_up` — `1` when the APScheduler process is running
- `pihole_config_info{config_id,config_name}` — metadata gauge; join on `config_id` for friendly names
- `pihole_config_active{config_id}` — `1` when scheduled backups are enabled
- `pihole_connection_status{config_id,status}` — one-hot connection state
- `pihole_backup_last_success_timestamp_seconds{config_id}` — unix timestamp (0 if never)
- `pihole_backup_last_status{config_id}` — `1`=success, `0`=failed, `-1`=none yet
- `pihole_backup_records{config_id,status}` — current count of backup records per status
- `pihole_backup_file_size_bytes{config_id}` — size of the latest successful backup
- `pihole_backup_total_size_bytes{config_id}` — sum of sizes across successful backups

Join the friendly name into dashboards with:

```promql
pihole_backup_records * on(config_id) group_left(config_name) pihole_config_info
```

## Data Storage

Backups and the database are stored in mounted volumes:

- `./data/` - SQLite database
- `./backups/` - Backup ZIP files

## Commands

```bash
# View logs
docker compose logs -f checkpoint-pihole

# Stop the application
docker compose down

# Rebuild after updates
docker compose up --build -d
```

## License

MIT

## Disclaimer

This project is third-party software and is not affiliated with, endorsed by, or
associated with the official Pi-hole project. "Pi-hole" is a registered trademark
of Pi-hole LLC.
