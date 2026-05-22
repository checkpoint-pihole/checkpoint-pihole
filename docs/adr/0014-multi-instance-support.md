# ADR-0014: Multi-Instance Pi-hole Support

**Status:** Implemented (with deviations noted below)
**Date:** 2026-04-07

---

## Context

Checkpoint Pi-hole currently backs up a single Pi-hole v6 instance. While the data model was designed with multi-instance in mind (ADR-0001, Section 5), the UI and credential system are hardcoded to single-instance:

- `PiholeConfig` has a `name` field and `BackupRecord` has a foreign key to it
- The scheduler creates per-config jobs via `run_backup_job_for_config(config_id)` (ADR-0013, Issue 1)
- `RetentionService.enforce_all()` iterates all active configs
- `BackupService`, `RestoreService` accept a `config` parameter

**But these layers are single-instance:**

- **Credentials**: `CredentialService` reads from single env vars `PIHOLE_URL`/`PIHOLE_PASSWORD`/`PIHOLE_VERIFY_SSL`
- **Views**: `dashboard()`, `settings_view()`, `create_backup()` all use `PiholeConfig.objects.first()`
- **Templates**: Dashboard shows one config, settings edits one config, no instance navigation
- **URLs**: No config selector in URL patterns

ADR-0013, Issue 7 documents this as a known limitation. Users running primary + secondary Pi-hole instances (a common HA setup) must deploy separate Checkpoint containers.

### Reference Implementation

The `nodered-backup` project in this repo family solves the same problem using an **environment variable prefix pattern**: each instance stores an `env_prefix` in the DB, and credentials are read from `FLOWHISTORY_{PREFIX}_USER`/`FLOWHISTORY_{PREFIX}_PASS` at runtime. Credentials never touch the database.

---

## Decision

**Add full multi-instance support using the environment variable prefix pattern for credentials, instance-scoped URL routing, and a card-based instance overview UI.**

---

## Options Considered

### Credential Storage

| Option | Pros | Cons |
|--------|------|------|
| **1. Env prefix pattern** | No DB encryption needed, Docker-friendly, proven pattern | Requires container restart to add credentials |
| 2. Encrypted DB fields (Fernet) | UI-only config, no restart | Adds `cryptography` dependency, partially reverts ADR-0010 |
| 3. Django Signer obfuscation | No new dependency, UI-only config | Not real encryption, passwords recoverable |
| 4. Plaintext DB fields | Simplest | Passwords visible in SQLite file |

**Recommendation: Option 1** — Matches the established pattern from nodered-backup, keeps credentials out of the database entirely (aligned with ADR-0010's philosophy), and avoids any encryption dependency.

### URL Structure

| Option | Pros | Cons |
|--------|------|------|
| **1. `/instances/<id>/` prefix** | RESTful, bookmarkable, clean | More URL patterns to maintain |
| 2. Query param `?config=<id>` | Simple | Not RESTful, messy with POST |
| 3. Session-based active instance | Fewer URL changes | Breaks multi-tab, confusing state |

**Recommendation: Option 1** — Clean REST semantics, works naturally with Django's URL routing.

### UI Approach

| Option | Pros | Cons |
|--------|------|------|
| **1. Instance card grid + detail pages** | Clear overview, scales to N instances | Two template layers |
| 2. Navbar dropdown switcher | Compact | Hides instance overview, doesn't scale |
| 3. Tabs on single page | Everything visible | Long page, doesn't scale |

**Recommendation: Option 1** — Provides both an at-a-glance overview and detailed per-instance views.

> **Note:** Instances are auto-discovered from `PIHOLE_{PREFIX}_URL` environment variables on container startup. There is no manual "add instance" UI — all instance lifecycle is driven by env vars.

---

## Implementation Plan

### Phase 1: Model Layer

**File:** `backup/models.py`

Add fields and a credential method to `PiholeConfig`:

```python
class PiholeConfig(models.Model):
    # ... existing fields ...

    # Multi-instance credential support
    env_prefix = models.CharField(
        max_length=50, default="PRIMARY", unique=True,
        help_text="Environment variable prefix (e.g., PRIMARY reads PIHOLE_PRIMARY_URL)"
    )

    def get_pihole_credentials(self):
        """Read Pi-hole credentials from environment variables using configured prefix.

        Env var pattern: PIHOLE_{PREFIX}_URL, PIHOLE_{PREFIX}_PASSWORD, PIHOLE_{PREFIX}_VERIFY_SSL
        """
        prefix = self.env_prefix.upper()
        url = os.environ.get(f"PIHOLE_{prefix}_URL", "")
        password = os.environ.get(f"PIHOLE_{prefix}_PASSWORD", "")
        verify_ssl = os.environ.get(f"PIHOLE_{prefix}_VERIFY_SSL", "false").lower() == "true"
        return {
            "url": url,
            "password": password,
            "verify_ssl": verify_ssl,
        }

    def is_credentials_configured(self):
        """Check if Pi-hole credentials are available in the environment."""
        creds = self.get_pihole_credentials()
        return bool(creds["url"] and creds["password"])
```

**Migrations:**
- `0003_add_multi_instance_fields.py` — Add `env_prefix` field (required, default `"PRIMARY"`)
- `0004_add_connection_status.py` — Add `connection_status` and `connection_error` fields
- `0005_alter_piholeconfig_env_prefix.py` — Add regex validator to `env_prefix`
- `0006_piholeconfig_env_prefix_unique.py` — Add `unique=True` constraint to `env_prefix`
- Data migration: existing `PiholeConfig` rows get `env_prefix = "PRIMARY"`

### Phase 2: Credential Service Refactor *(implemented as designed)*

**File:** `backup/services/credential_service.py`

Refactored to delegate to the config's credential method:

```python
class CredentialService:
    @staticmethod
    def get_credentials(config: PiholeConfig) -> dict:
        """Get Pi-hole credentials for a specific config instance."""
        creds = config.get_pihole_credentials()
        prefix = config.env_prefix.upper()
        if not creds["url"]:
            raise ValueError(f"PIHOLE_{prefix}_URL environment variable is required")
        if not creds["password"]:
            raise ValueError(f"PIHOLE_{prefix}_PASSWORD environment variable is required")
        return creds

    @staticmethod
    def is_configured(config: PiholeConfig) -> bool:
        """Check if Pi-hole credentials are configured for this instance."""
        return config.is_credentials_configured()

    @staticmethod
    def get_status(config: PiholeConfig) -> dict:
        """Get configuration status for display in UI."""
        creds = config.get_pihole_credentials()
        return {
            "url": creds["url"] or None,
            "has_password": bool(creds["password"]),
            "verify_ssl": creds["verify_ssl"],
            "env_prefix": config.env_prefix,
        }
```

### Phase 3: Service Layer Updates

**Files:** `backup/services/backup_service.py`, `backup/services/restore_service.py`

Both services already accept `config: PiholeConfig` in their constructors. Update the internal `_get_client()` calls from:
```python
creds = CredentialService.get_credentials()
```
to:
```python
creds = CredentialService.get_credentials(self.config)
```

No structural changes needed — just pass `self.config` through.

### Phase 4: URL Routing

**File:** `backup/urls.py`

```python
urlpatterns = [
    # Overview / instance list
    path("", views.dashboard, name="dashboard"),

    # Instance management
    path("instances/add/", views.add_instance, name="add_instance"),
    path("instances/<int:config_id>/", views.instance_dashboard, name="instance_dashboard"),
    path("instances/<int:config_id>/settings/", views.instance_settings, name="instance_settings"),

    # Per-instance API endpoints
    path("instances/<int:config_id>/backup/", views.create_backup, name="create_backup"),
    path("instances/<int:config_id>/test-connection/", views.test_connection, name="test_connection"),

    # Backup-level operations (unchanged — resolve config via backup.config FK)
    path("backup/<int:backup_id>/delete/", views.delete_backup, name="delete_backup"),
    path("backup/<int:backup_id>/download/", views.download_backup, name="download_backup"),
    path("api/restore/<int:backup_id>/", views.restore_backup, name="restore_backup"),

    # Legacy redirects
    path("settings/", views.settings_redirect, name="settings"),

    # Auth (unchanged)
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("health/", views.health_check, name="health_check"),
]
```

### Phase 5: View Layer

**File:** `backup/views.py`

**Refactored `dashboard()`** — smart routing based on config count:
```python
def dashboard(request):
    configs = PiholeConfig.objects.all()
    if configs.count() == 1:
        # Single-instance: show full dashboard directly (backward compat)
        config = configs.first()
        backups = BackupRecord.objects.filter(config=config)
        return render(request, "backup/instance_dashboard.html", {
            "config": config, "backups": backups, "single_instance": True,
        })
    # Multi-instance: show overview grid
    return render(request, "backup/instance_list.html", {"configs": configs})
```

**New `instance_dashboard(config_id)`:**
```python
def instance_dashboard(request, config_id):
    config = get_object_or_404(PiholeConfig, id=config_id)
    backups = BackupRecord.objects.filter(config=config)
    return render(request, "backup/instance_dashboard.html", {
        "config": config, "backups": backups, "single_instance": False,
    })
```

**New `instance_settings(config_id)`** — read-only view (no form):
```python
def instance_settings(request, config_id):
    config = get_object_or_404(PiholeConfig, id=config_id)
    credential_status = CredentialService.get_status(config)
    return render(request, "backup/settings.html", {"config": config, "credential_status": credential_status})
```

**Implementation note:** `add_instance()` was not implemented — instances are auto-discovered from environment variables via the `discover_instances` management command (run on startup). Manual instance creation via the UI is not currently supported.

**Refactored `create_backup(config_id)`** — use `get_object_or_404` instead of `.first()`.

**Refactored `test_connection(config_id)`** — load config by ID, call `CredentialService.get_credentials(config)`.

**`settings_redirect()`** — redirects `/settings/` to first config's settings page or dashboard.

**Auto-discovery behavior:** On startup, `discover_instances_from_env()` scans for `PIHOLE_{PREFIX}_URL` environment variables. Instances whose env vars are no longer present are marked as `removed` (connection_status) and deactivated (is_active=False). Their backup records and files are retained as orphaned backups — users can still download or delete them individually. The instance dashboard shows an alert banner for removed instances explaining the situation.

### Phase 6: Templates

**New `backup/templates/backup/instance_list.html`:**
- Card grid layout, one card per `PiholeConfig`
- Each card shows: name, Pi-hole URL (from env), last backup timestamp, schedule, status badge
- Quick actions: "Backup Now" button, "View" link, "Settings" link
- "Add Instance" button

**New/refactored `backup/templates/backup/instance_dashboard.html`:**
- Extracted from current `dashboard.html`
- Scoped to one config
- "Back to Overview" link when `single_instance` is False
- AJAX URLs point to `/instances/<id>/...`

**Modified `backup/templates/backup/settings.html`:**
- Add `env_prefix` field (with help text explaining the env var pattern)
- Show resolved env var status (URL detected, password detected)
- Per-instance scoping via `/instances/<id>/settings/`
- Instance removal handled by env var lifecycle (no delete button needed)

**Modified `backup/templates/backup/base.html`:**
- Add breadcrumb navigation below navbar when on instance pages
- "Dashboard > Instance Name > Settings" pattern

### Phase 7: Form Removal

**File:** `backup/forms.py`

`PiholeConfigForm` was removed — settings are read-only, all configuration is via environment variables. Only `LoginForm` remains.

### Phase 8: Testing

**Test scenarios:**

| Scenario | Expected |
|----------|----------|
| Single config exists | Root `/` shows full dashboard (backward compat) |
| Zero configs exist | Root `/` shows empty state with "Add Instance" |
| 2+ configs exist | Root `/` shows instance card grid |
| Env prefix `PRIMARY` set | Reads `PIHOLE_PRIMARY_URL`, `PIHOLE_PRIMARY_PASSWORD` |
| Per-instance backup | Creates backup using that config's env credentials |
| Per-instance test connection | Tests with that config's env credentials |
| Instance env var removed | Instance marked as removed, backups retained as orphaned |
| Instance with missing env vars | Shows clear error about which env var is missing |

**Files to update:**
- `backup/tests/conftest.py` — multi-config fixtures with `env_prefix`
- `backup/tests/unit/test_credential_service.py` — test prefix-based credential resolution
- `backup/tests/views/test_dashboard.py` — test single vs multi-config routing
- `backup/tests/views/` — instance settings views

---

## Files to Modify

| File | Changes |
|------|---------|
| `backup/models.py` | Add `env_prefix` field (unique) + `get_pihole_credentials()` method |
| `backup/migrations/0003-0006` | **New** — add fields, validators, unique constraint |
| `backup/services/credential_service.py` | Refactor to accept `config` parameter, delegate to model method |
| `backup/services/discovery_service.py` | **New** — auto-discover instances from `PIHOLE_*` env vars |
| `backup/services/backup_service.py` | Pass `self.config` to `CredentialService.get_credentials()`, path traversal protection |
| `backup/services/restore_service.py` | Pass `self.config` to `CredentialService.get_credentials()` |
| `backup/views.py` | Add instance views, read-only settings, remove dead orphan code |
| `backup/urls.py` | Add instance-prefixed URL patterns |
| `backup/forms.py` | Remove `PiholeConfigForm` (settings now read-only) |
| `backup/context_processors.py` | **New** — app version and build metadata |
| `backup/management/commands/discover_instances.py` | **New** — management command for discovery |
| `backup/templates/backup/instance_list.html` | **New** — instance card grid overview |
| `backup/templates/backup/instance_dashboard.html` | **New** — per-instance dashboard (extracted from dashboard.html) |
| `backup/templates/backup/_connection_badge.html` | **New** — shared connection status badge include |
| `backup/templates/backup/settings.html` | Read-only per-instance settings, uses shared badge |
| `backup/templates/backup/base.html` | Add breadcrumb navigation, footer with version |
| `.env.example` | Update with prefix pattern (old unprefixed vars removed) |
| `Dockerfile` | Add build metadata ARGs/ENVs |
| `docker-compose.yml` | Use `env_file: .env` for prefix passthrough |
| `entrypoint.sh` | Add `discover_instances` step |
| `docs/adr/0000-index.md` | Add ADR-0014 entry |

---

## Migration Path

**Breaking change**: The old `PIHOLE_URL`/`PIHOLE_PASSWORD`/`PIHOLE_VERIFY_SSL` env vars are no longer supported. All instances must use the prefixed pattern.

1. User pulls new Docker image, updates `.env` file:
   - `PIHOLE_URL` → `PIHOLE_PRIMARY_URL`
   - `PIHOLE_PASSWORD` → `PIHOLE_PRIMARY_PASSWORD`
   - `PIHOLE_VERIFY_SSL` → `PIHOLE_PRIMARY_VERIFY_SSL`
2. Runs `docker compose up`
3. Migration `0003` runs automatically:
   - Existing `PiholeConfig` gets `env_prefix = "PRIMARY"`
   - All existing backup records stay linked (FK unchanged)
4. To add a second Pi-hole, user adds env vars with a new prefix (e.g., `PIHOLE_SECONDARY_URL`, `PIHOLE_SECONDARY_PASSWORD`) and restarts the container — the instance is auto-discovered on startup
5. Container restart required after adding new env vars (standard Docker behavior)

---

## Consequences

### Positive

- Users can back up multiple Pi-hole instances from a single deployment
- No new dependencies — credentials stay in environment, no encryption library needed
- Consistent pattern with nodered-backup project in this repo family
- Scheduler, retention, and services require minimal changes (already multi-instance ready)
- Foundation for future features: bulk backup, cross-instance restore, instance health monitoring

### Negative

- Adding a new Pi-hole instance requires a container restart (env vars are auto-discovered on startup)
- More URL patterns and views to maintain
- Template count increases (instance_list, instance_dashboard)

### Risks

- **Env var misconfiguration**: User sets wrong prefix in UI vs env vars → backup silently fails. Mitigation: show resolved env var status on settings page, validate on test connection.
- **Breaking change for existing users**: The old `PIHOLE_URL`/`PIHOLE_PASSWORD` env vars no longer work. Users must rename to `PIHOLE_PRIMARY_URL`/`PIHOLE_PRIMARY_PASSWORD`. Mitigation: clear migration docs, app not yet publicly released.
- **SQLite concurrency**: Multiple instances backing up simultaneously could increase write contention. Mitigation: existing per-config locking in scheduler serializes per-config; SQLite WAL mode handles moderate concurrency.

---

## Future Considerations

- **Bulk "Backup All" button** on the overview page
- **Cross-instance restore** — restore a backup from one Pi-hole to another
- **Instance health monitoring** — periodic connectivity checks with status indicators
- **Per-instance notification settings** — different notification channels per Pi-hole
- **Instance groups/tags** — organize instances (e.g., "Primary DNS", "Secondary DNS")

---

## References

- [ADR-0001](0001-pihole-backup-architecture.md) — Original architecture, Section 5: multi-instance model design
- [ADR-0010](0010-env-var-credentials.md) — Env var credential decision (philosophy preserved here)
- [ADR-0013](0013-reliability-security-fixes.md) — Issue 1 (per-config scheduler) and Issue 7 (single-config UI limitation)
- nodered-backup `env_prefix` pattern — Reference implementation
