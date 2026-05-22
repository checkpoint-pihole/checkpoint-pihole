# ADR-0016: Prometheus Metrics Endpoint

**Status:** Accepted
**Date:** 2026-04-16
**Deciders:** Leonardo Merza

## Context

### Background

Operators running Checkpoint Pi-hole alongside Prometheus/Grafana have no
standard way to alert on backup health. The only existing observability surface
is `/health/` (JSON liveness) and the application logs. Important signals —
"last successful backup per instance", "connection status", "scheduler
liveness", "total stored backup bytes" — are locked inside the SQLite database.

### Current State

- Django 5.x app with two processes in one container: APScheduler
  (`BlockingScheduler`) and Gunicorn (see ADR-0003).
- `BackupRecord` and `PiholeConfig` already capture every signal an operator
  would want to alert on (`file_size`, `status`, `created_at`,
  `last_successful_backup`, `connection_status`, `is_active`).
- Scheduler writes to the DB; Gunicorn reads from it. There is no shared
  in-memory state between the two processes.
- `SimpleAuthMiddleware` already exempts `/health/` and `/login/`; exempting one
  more path is a one-line change.

### Requirements

- Standard Prometheus text-exposition format (scrapers must parse without
  custom config).
- Per-instance labels so multi-Pi-hole deployments (ADR-0014) expose one time
  series per config.
- Auth-exempt: Prometheus scrapers don't hold Django sessions.
- No new process, no new port — must serve from the existing Gunicorn.
- Minimal dependency footprint.

### Constraints

- Single container, two processes — metrics state can't live in
  scheduler-process memory if the web process is the one serving `/metrics/`.
- SQLite is the backing store; any per-scrape query must stay cheap (indexed
  aggregates, not table scans of all history).

## Options Considered

### Option 1: `prometheus_client` with DB-derived gauges

**Description:** Add `prometheus_client` as a dependency. Implement a small
`metrics_service` that, on each request, builds a fresh `CollectorRegistry`,
runs a few aggregate ORM queries over `BackupRecord` and `PiholeConfig`, and
populates gauges. The view returns `generate_latest(registry)`.

**Pros:**
- Tiny dep footprint; `prometheus_client` is the reference SDK.
- Stateless — no multiprocess dir, no instrumentation in services.
- DB is already the source of truth; reading it is correct by construction.
- Works identically across any number of Gunicorn workers.
- Mirrors the existing `/health/` pattern (read DB, return response).

**Cons:**
- True counters (e.g. "HTTP requests ever") aren't modelled here; COUNT
  aggregates are exposed as gauges instead. Acceptable because backup counts
  are naturally queryable.
- No in-process latency histograms (e.g. "backup download duration"). Can be
  added later via a separate mechanism.

### Option 2: `django-prometheus`

**Description:** Use the `django-prometheus` package, which adds middleware
auto-instrumenting Django requests, ORM queries, and cache calls, plus helpers
for model-level metrics.

**Pros:**
- Out-of-box HTTP latency, request count, DB query metrics.

**Cons:**
- Most auto-exposed metrics (request latency, template render time) aren't
  domain signals for this app. Backup health matters more than view latency.
- Still requires custom collectors for the domain metrics we actually want.
- Multi-process support requires `PROMETHEUS_MULTIPROC_DIR` shared between
  scheduler and Gunicorn — extra volume, extra cleanup on restart.
- Heavier middleware surface on every request.

### Option 3: `prometheus_client` multiprocess mode

**Description:** Instrument `backup_service.create_backup` and Pi-hole API
client calls with real `Counter` / `Histogram` objects. Set
`PROMETHEUS_MULTIPROC_DIR` to a path shared by scheduler and Gunicorn so the
web process sees counter increments made in the scheduler process.

**Pros:**
- Real latency histograms for backup duration, API calls.
- Proper counter semantics for "total backups attempted ever".

**Cons:**
- Multiprocess mode restricts gauge semantics (must pick `min`/`max`/`sum`/
  `livesum` for gauges).
- Requires shared filesystem dir that must be cleaned on restart.
- Scatters instrumentation across services; the DB already tells us
  everything important.
- Over-engineered for current observability needs — YAGNI.

## Decision

**Chosen Option:** Option 1 — `prometheus_client` with DB-derived gauges.

**Rationale:** the DB is already the authoritative record of backup outcomes,
so recomputing a few aggregates per scrape is both correct and simple. It
avoids every cross-process concern Options 2 and 3 introduce (multiproc dir,
shared volumes, restricted gauge modes), and keeps the implementation small
enough to review in one sitting. The pattern matches `/health/` — stateless,
DB-backed, auth-exempt.

If in the future we want in-process latency histograms (backup duration,
Pi-hole API response times), we can add them under a separate endpoint or
adopt Option 3 then. The DB-derived metrics remain valid alongside.

## Consequences

### Positive
- Grafana dashboards and Prometheus alerts work out of the box with standard
  scrape config.
- Multi-instance deployments (ADR-0014) get per-instance time series for free.
- No new process, no new port, no new volume.
- Scheduler and gunicorn stay decoupled — no IPC introduced.

### Negative
- Each scrape runs a handful of aggregate queries. At default Prometheus 15s
  scrape interval on a SQLite DB with indexed `config_id` this is negligible,
  but non-zero.
- No latency histograms for backup or API operations (deferred).
- Metric values are a snapshot at scrape time, not a push-on-event counter.

### Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Scrape query cost grows with backup history | Low | Low | Aggregates use indexed `config_id`; SUM/COUNT on hundreds of rows is sub-ms on SQLite |
| `/metrics/` leaks instance names to unauthenticated scrapers | Medium | Low | Labels use the user-chosen `name`; document that the endpoint is auth-exempt and advise reverse-proxy scoping if hostnames are sensitive |
| prometheus_client version drift breaks exposition | Low | Low | Pin `>=0.20,<1.0`; covered by tests |
| Adding a new metric later requires schema changes | Low | Low | All current metrics are derivable from existing model fields |

## Metrics Exposed

All metrics are prefixed `pihole_`. Config-scoped data metrics carry only
the stable `config_id` label. The friendly `config_name` is exposed on a
separate info-style gauge (`pihole_config_info`) so renames don't leave
stale duplicate series on the data metrics; dashboards join on `config_id`.

The gauge name `pihole_backup_records` avoids the `_total` suffix that
Prometheus/OpenMetrics reserves for monotonic counters, since retention can
cause the underlying count to decrease.

| Metric | Type | Extra labels | Source |
|--------|------|--------------|--------|
| `pihole_info` | gauge | version | build metadata |
| `pihole_scheduler_up` | gauge | — | `is_scheduler_running()` |
| `pihole_config_info` | gauge | config_name | `PiholeConfig.name` (info/metadata join target) |
| `pihole_config_active` | gauge | — | `PiholeConfig.is_active` |
| `pihole_connection_status` | gauge | status | one-hot over `connection_status` choices |
| `pihole_backup_last_success_timestamp_seconds` | gauge | — | `PiholeConfig.last_successful_backup` |
| `pihole_backup_last_status` | gauge | — | most recent `BackupRecord` (1=success, 0=failed, -1=none) |
| `pihole_backup_records` | gauge | status | `COUNT(BackupRecord)` grouped by status |
| `pihole_backup_file_size_bytes` | gauge | — | latest successful `BackupRecord.file_size` |
| `pihole_backup_total_size_bytes` | gauge | — | `SUM(file_size)` across successful backups |

## Implementation Plan

- [x] Add `prometheus-client>=0.20,<1.0` to `pyproject.toml`
- [x] Create `backup/services/metrics_service.py` with `build_registry()`
- [x] Add `metrics_view` to `backup/views.py`
- [x] Register `path("metrics/", ...)` in `backup/urls.py`
- [x] Exempt `/metrics/` in `backup/middleware/simple_auth.py`
- [x] Add `backup/tests/views/test_metrics.py`
- [x] Document endpoint and metric names in `README.md`
- [x] Update `docs/adr/0000-index.md`

## Related ADRs

- [ADR-0003](./0003-single-container-architecture.md) — Two-process layout that shaped the DB-derived choice
- [ADR-0014](./0014-multi-instance-support.md) — Motivates per-config labels
- [ADR-0015](./0015-simple-password-authentication.md) — Auth model that `/metrics/` must be exempted from

## References

- [Prometheus Python client](https://github.com/prometheus/client_python)
- [Prometheus exposition formats](https://prometheus.io/docs/instrumenting/exposition_formats/)
- [Prometheus naming best practices](https://prometheus.io/docs/practices/naming/)
