# ADR-0019: Fable Audit Findings and Remediation Plan (2026-07-02)

**Status:** Proposed
**Date:** 2026-07-02
**Deciders:** Project Owner

---

## Context

A multi-agent code audit ("fable-audit") was run against the codebase on the `fix/audit-safety` branch, immediately after commit `713d1ac` ("fail-closed auth, retention path guard, unified bool env parsing") had already closed five separate issues. The audit dispatched one finder agent per dimension (security, correctness, quality, deployment, test coverage), and every raw finding was independently re-verified by a second, adversarial "skeptic" agent instructed to refute it against the real code — findings that survived refutation are recorded here. The full report, including per-finding verifier evidence and a disclosed methodology caveat, lives at [`docs/AUDIT-2026-07-02.md`](../AUDIT-2026-07-02.md).

This ADR follows the precedent set by [ADR-0011](0011-bug-review-findings.md) and [ADR-0013](0013-reliability-security-fixes.md): bundling all findings from one review pass into a single tracking document rather than one ADR per finding.

The audit covered:
- Discovery/reconciliation (`backup/services/discovery_service.py`)
- Backup/restore/retention services (`backup/services/backup_service.py`, `restore_service.py`, `retention_service.py`)
- Pi-hole API client (`backup/services/pihole_client.py`)
- Notification providers (`backup/services/notifications/`)
- Views and endpoints (`backup/views.py`)
- Container startup and healthcheck (`entrypoint.sh`, `Dockerfile`, `docker-compose.yml`)
- CI/CD workflows (`.github/workflows/`)
- Test coverage across all of the above

No findings re-open any of the five issues `713d1ac` already fixed (fail-open auth, retention path traversal, inconsistent bool env parsing, session fixation, spoofable rate-limit IP).

**Methodology caveat:** a scripting bug in the audit tooling caused 3 of the 36 raw skeptic-verifications to inspect an unrelated project instead of this one, wrongly refuting 3 findings as "fabricated." All three underlying issues below survived in this ADR anyway because an independent second finder had raised the same issue with a correctly-scoped verifier, and the top 5 by severity were separately spot-checked directly against this repo. See the full report's Methodology section for detail.

---

## Findings

### High Priority

#### Finding 1: Re-Added Env Var Never Reactivates a Removed Instance

| | |
|---|---|
| **Location** | `backup/services/discovery_service.py:105-154` |
| **Status** | [ ] Not Fixed |
| **Priority** | High |

**Description:**
When a `PIHOLE_{PREFIX}_URL` env var disappears, the matching `PiholeConfig` row is marked `connection_status='removed'`, `is_active=False`. If the same prefix is later restored, the reconciliation function skips the existing row entirely when `force=False` (`if existing and not force`), and even the `force=True` path only `setattr`s fields returned by `_build_config_kwargs` (name, schedule, retention) — `is_active` and `connection_status` are never included and never reset.

**Impact:**
`backup/management/commands/runapscheduler.py` filters scheduled jobs on `is_active=True`. A "removed" instance's scheduled backups therefore never resume, even after valid credentials are restored — silently and with no error surfaced anywhere. Only manual Django admin/DB intervention recovers it.

**Suggested Fix:**
```python
# In discover_instances_from_env, when a prefix is present in the environment
# and the existing row was previously marked removed, reset its status
# regardless of the force flag:
if existing.connection_status == "removed" or not existing.is_active:
    existing.is_active = True
    existing.connection_status = "unknown"
    existing.connection_error = ""
    existing.save()
```

**Testing:**
- Remove a `PIHOLE_*_URL` env var and restart; verify the config is marked removed/inactive.
- Restore the env var and restart (with and without `--force`); verify `is_active` and `connection_status` reset and the instance's scheduled jobs resume.

---

### Medium Priority

#### Finding 2: Session/CSRF Cookies Never Marked Secure

| | |
|---|---|
| **Location** | `config/settings.py` (session config block, ~line 176) |
| **Status** | [ ] Not Fixed |
| **Priority** | Medium |

**Description:**
None of `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `SECURE_PROXY_SSL_HEADER`, `SECURE_SSL_REDIRECT`, or HSTS settings are set anywhere in `config/settings.py`. `backup/middleware/simple_auth.py` gates every page on `request.session.get("authenticated")`, so the session cookie is the app's actual auth token. ADR-0001 claims "secure cookies" as an implemented control; the code does not match.

**Impact:**
An operator who enables `REQUIRE_AUTH` behind a TLS-terminating reverse proxy still gets a non-`Secure` session cookie, since gunicorn only ever sees plain HTTP. An attacker who can strip TLS or induce one plain-HTTP request can capture and replay the cookie for full UI access (create/restore/delete backups).

**Suggested Fix:**
```python
# Gate on a new HTTPS/production flag, paired with the existing TRUST_PROXY setting:
if TRUST_PROXY:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
```

**Testing:**
- Verify session cookie carries `Secure` when the new flag is enabled behind a TLS proxy.
- Verify login still works over plain HTTP in the default (no-proxy, no-flag) local setup.

---

#### Finding 3: delete_backup Reports Success Even When the File Was Not Deleted

| | |
|---|---|
| **Location** | `backup/views.py:187-196`, `backup/services/backup_service.py:21-47,189-196` |
| **Status** | [ ] Not Fixed |
| **Priority** | Medium |

**Description:**
`delete_backup_file_and_record()` returns `False` (deliberately keeping the DB record) when `unlink()` raises `OSError`. `BackupService.delete_backup()` forwards that bool, but `views.py`'s `delete_backup` view discards the return value and unconditionally responds `{"success": true}`.

**Impact:**
If the backups volume goes read-only (fs error, ro remount, NFS hiccup), a delete click appears to succeed in the UI — the row vanishes then reappears on next page load — while the file and record are both still present. The user believes disk space was reclaimed when it wasn't.

**Suggested Fix:**
```python
if not service.delete_backup(record):
    return JsonResponse(
        {"success": False, "error": "Backup file could not be deleted; it will be retried"},
        status=500,
    )
return JsonResponse({"success": True})
```

**Testing:**
- Make the backups directory read-only and attempt a delete via the UI; verify the endpoint returns `success: false` and the row remains visible.

---

#### Finding 4: Scheduler Monitor Gives Up Silently — Container Keeps Running With Backups Dead

| | |
|---|---|
| **Location** | `entrypoint.sh:26-37,54,79` |
| **Status** | [ ] Not Fixed |
| **Priority** | Medium |

**Description:**
`monitor_scheduler` runs as a backgrounded subshell (`monitor_scheduler &`). After `MAX_RESTARTS=10` is exhausted, its `return 1` only sets the exit status of that detached subshell — nothing propagates it to PID 1, which stays blocked on `wait $GUNICORN_PID`. `/health/` does return 503 once the scheduler is confirmed dead, and the compose healthcheck marks the container unhealthy, but `restart: unless-stopped` only acts on container exit, not health status.

**Impact:**
The web UI keeps serving indefinitely while scheduled backups are permanently stopped. The app's own failure-notification pipeline fires only from inside scheduler-executed jobs, so it stays silent too — the failure is only visible via the container's "unhealthy" Docker status.

**Suggested Fix:**
```bash
# On giving up, make the failure terminal so the restart policy applies:
if [ "$restart_count" -ge "$MAX_RESTARTS" ]; then
    echo "Scheduler exhausted $MAX_RESTARTS restarts; stopping container"
    kill -TERM 1
    return 1
fi
```

**Testing:**
- Force the scheduler to crash-loop (e.g. corrupt the `django_apscheduler` tables) and verify the container exits and is restarted by the compose policy after `MAX_RESTARTS` is hit.

---

#### Finding 5: Non-ZIP 200 Response From Pi-hole Stored as a Successful Backup

| | |
|---|---|
| **Location** | `backup/services/pihole_client.py:131-155` |
| **Status** | [ ] Not Fixed |
| **Priority** | Medium |

**Description:**
`download_teleporter_backup` only logs a warning when the response Content-Type is neither zip nor octet-stream — it still returns the body. `BackupService.create_backup` writes those bytes to disk, checksums them, and records `status='success'` with no ZIP magic-byte validation anywhere.

**Impact:**
If Pi-hole sits behind a proxy/auth portal that answers 200 `text/html` for the Teleporter endpoint (maintenance page, WAF block page), every scheduled backup "succeeds" and retention rotates out real ZIPs — the corruption is only discovered when a restore is attempted and Pi-hole rejects the upload.

**Suggested Fix:**
```python
if not content.startswith(b"PK\x03\x04"):
    raise ValueError("Teleporter response is not a valid ZIP file")
```

**Testing:**
- Point a test instance's URL at a server returning 200 `text/html`; verify the backup is recorded as failed, not successful.

---

#### Finding 6: Path-Containment Guard Covers Delete Only — Download/Restore Trust file_path Unchecked

| | |
|---|---|
| **Location** | `backup/services/backup_service.py:198-203`, `backup/services/restore_service.py:59-71`, `backup/views.py:226-252` |
| **Status** | [ ] Not Fixed |
| **Priority** | Medium (downgraded from finder's initial High by the verifier — see note) |

**Description:**
The `resolve()` + `relative_to(BACKUP_DIR)` containment guard added in `713d1ac` protects only the delete path. `get_backup_file()` (download) and `RestoreService.restore_backup()` both open `Path(record.file_path)` directly with no containment check — the exact threat model the delete guard's own docstring names ("a record whose file_path was tampered with via the admin, or an imported/legacy database"). `BackupRecordAdmin` leaves `file_path`/`checksum` editable in the Django admin.

**Impact:**
An admin-panel user (or an imported/legacy DB) who edits a `BackupRecord.file_path` to point outside `BACKUP_DIR` can trigger an arbitrary-file read via download, or upload an arbitrary local file's contents to Pi-hole via restore. Exploitation requires a Django staff/superuser account (none is created by the shipped setup) or direct sqlite write access — hence medium, not high.

**Suggested Fix:**
```python
# Extract the containment check already used by delete_backup_file_and_record
# into a shared helper, and use it in get_backup_file() and restore_backup() too:
def resolve_backup_path(record: BackupRecord) -> Path | None:
    filepath = Path(record.file_path).resolve()
    backup_dir = settings.BACKUP_DIR.resolve()
    try:
        filepath.relative_to(backup_dir)
    except ValueError:
        return None
    return filepath
```
Also treat a blank `checksum` as a verification failure on restore, and add `file_path`/`checksum` to `BackupRecordAdmin.readonly_fields`.

**Testing:**
- Point a `BackupRecord.file_path` outside `BACKUP_DIR` via the admin and verify both download and restore refuse it.

---

#### Finding 7: Container Runs as Root — Contradicts ADR-0001's "Implemented" Non-Root Design

| | |
|---|---|
| **Location** | `Dockerfile` (no `USER` directive) |
| **Status** | [ ] Not Fixed |
| **Priority** | Medium |

**Description:**
The Dockerfile has no `USER` directive anywhere, so gunicorn, the APScheduler process, and migrations all run as root. `docs/adr/0001-pihole-backup-architecture.md` specifies `useradd -m -u 1000 appuser` + `USER appuser` and is marked "Implemented" in the ADR index — the implementation never adopted it.

**Impact:**
Any code-execution or file-write bug (including Finding 6 above) has root scope in-container. It is also a documentation-accuracy problem: an operator auditing the ADRs would conclude the container is non-root when it is not.

**Suggested Fix:**
```dockerfile
RUN useradd -m -u 1000 appuser \
    && chown -R appuser:appuser /app/data /app/backups /app/staticfiles
USER appuser
```
Alternatively, if root is now the accepted trade-off, amend ADR-0001's status/consequences and the index entry so they stop asserting a security property that doesn't hold.

**Testing:**
- Rebuild and verify `docker exec <container> whoami` returns `appuser`, and that migrations/scheduler/gunicorn all still function with the bind-mounted volumes.

---

#### Finding 8: AJAX Endpoints Have Drifted Contracts — HTML 404s Reach a JSON-Only Frontend

| | |
|---|---|
| **Location** | `backup/views.py:125-127,158-160,187,202`, `backup/templates/backup/instance_dashboard.html:334,367` |
| **Status** | [ ] Not Fixed |
| **Priority** | Medium |

**Description:**
`test_connection`/`create_backup` return JSON 404s via `filter().first()`. `delete_backup`/`restore_backup` use `get_object_or_404`, which raises `Http404` and returns Django's HTML 404 page. The dashboard's `fetch` handlers call `response.json()` unconditionally with no `response.ok` check.

**Impact:**
A stale dashboard row (deleted by retention or a second browser tab) clicked for delete/restore triggers a `SyntaxError` in the frontend, surfacing a garbled parse-error toast instead of "Backup not found."

**Suggested Fix:**
```python
def _json_get_or_404(model, **kwargs):
    obj = model.objects.filter(**kwargs).first()
    if obj is None:
        return None, JsonResponse({"success": False, "error": f"{model.__name__} not found."}, status=404)
    return obj, None
```
Use this helper in all four AJAX views.

**Testing:**
- Delete a backup in one tab, then click delete/restore on the same (now-stale) row in another tab; verify a proper JSON error toast appears.

---

#### Finding 9: Compose Default SECRET_KEY Is a Public Placeholder That Disables Auto-Generation

| | |
|---|---|
| **Location** | `docker-compose.yml:13` |
| **Status** | [ ] Not Fixed |
| **Priority** | Medium (downgraded from finder's initial High by the verifier — see note) |

**Description:**
`docker-compose.yml` sets `SECRET_KEY=${SECRET_KEY:-change-me-in-production-use-long-random-string}`. Since `get_or_create_secret_key()` returns any truthy env value, the persisted-random-key fallback in `config/settings.py` can never execute under the shipped compose file — every deployment that doesn't explicitly set `SECRET_KEY` in `.env` runs with this literal string committed to the public repo.

**Impact:**
The app uses default DB-backed sessions (no `SESSION_ENGINE` override), so a known `SECRET_KEY` cannot forge an authenticated session today. Present-day impact is limited to forging the Django messages cookie and generally weakening any future use of signing — hence medium, not high.

**Suggested Fix:**
```yaml
# docker-compose.yml
environment:
  SECRET_KEY: ${SECRET_KEY:-}   # empty string is falsy; falls through to the
                                 # persisted-random-key generation in ./data
```

**Testing:**
- Run `docker compose up` with no `SECRET_KEY` in `.env`; verify `data/.secret_key` gets created with a random value instead of the container receiving the placeholder string.

---

#### Finding 10: Healthcheck Detects Scheduler Exhaustion but Nothing Restarts the Container

| | |
|---|---|
| **Location** | `docker-compose.yml:20-25` |
| **Status** | [ ] Not Fixed |
| **Priority** | Medium |

**Description:**
Same root cause as Finding 4: the healthcheck (`curl -f /health/`, 30s interval) correctly turns the container unhealthy once the scheduler is confirmed dead, but `restart: unless-stopped` only triggers on container exit, and no autoheal service exists in this stack. There is also no `start_period`, so a slow first boot (migrations + connection checks against unreachable Pi-holes) can burn healthcheck retries before gunicorn is listening.

**Suggested Fix:** Resolved together with Finding 4 (make scheduler-exhaustion terminal at the process level so the restart policy applies). Additionally:
```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:8000/health/"]
  interval: 30s
  start_period: 30s
```

---

#### Finding 11: pihole_backup_last_status Aggregation Logic Has Zero Assertions

| | |
|---|---|
| **Location** | `backup/services/metrics_service.py:108-152` |
| **Status** | [ ] Not Fixed |
| **Priority** | Medium |

**Description:**
No unit tests exist for `metrics_service.py`; the only coverage is `backup/tests/views/test_metrics.py` hitting the `/metrics` endpoint, which never asserts the `pihole_backup_last_status` gauge for a config with only-failed backups, zero backups, or duplicate-timestamp records (the `-id` tiebreaker at lines 111/120 is untested for ties).

**Impact:**
A regression that swaps `latest_any_by_config` for `latest_success_by_config`, or changes the ordering to `-id`, would pass the entire test suite while reporting `pihole_backup_last_status=1` (healthy) during an active failure streak — defeating the alert this metric exists for.

**Suggested Fix:**
Add `backup/tests/unit/test_metrics_service.py` calling `build_registry()` directly, covering: all-failed config, no-records config, and two records sharing an identical `created_at`.

---

#### Finding 12: Home Assistant Notification Provider's Dual Auth-Mode Branching Is Untested

| | |
|---|---|
| **Location** | `backup/services/notifications/homeassistant.py:19-56` |
| **Status** | [ ] Not Fixed |
| **Priority** | Medium |

**Description:**
No test instantiates `HomeAssistantProvider`. The webhook-vs-REST branch, `validate_config()`'s either/or rule, and the 200/201 success check are all unverified.

**Impact:**
A change that inverts the branch condition or drops the `Authorization` header would pass CI; a user configured with `NOTIFY_HOMEASSISTANT_TOKEN` would then get silent 401s on every failure notification — discovered only when a real backup failure goes unnoticed.

**Suggested Fix:**
Add tests mocking `requests.post` for both auth modes (webhook_id set vs. token-only) asserting endpoint, headers, and status handling.

---

#### Finding 13: NotificationSettings Event Routing and Provider Loading Are Entirely Untested

| | |
|---|---|
| **Location** | `backup/services/notifications/config.py:26-93`, `backup/services/notifications/service.py:57,63,85-107` |
| **Status** | [ ] Not Fixed |
| **Priority** | Medium |

**Description:**
`should_notify()`'s substring event routing and `_load_providers()`'s five `NOTIFY_*_ENABLED` branches have zero coverage — no test references `NotificationSettings`, any `NOTIFY_*` env var, or `reload_notification_settings`.

**Impact:**
A rename of an event value that drops the `"failed"` substring would make `should_notify` return `False` for backup failures with every existing test staying green — users with `NOTIFY_ON_FAILURE=true` would silently stop receiving failure alerts.

**Suggested Fix:**
Add tests using `monkeypatch.setenv` + `reload_notification_settings()` covering the truth table across all `NotificationEvent` values and the three toggles.

---

#### Finding 14: Discord/Slack/Pushbullet Providers Have No Direct Tests

| | |
|---|---|
| **Location** | `backup/services/notifications/discord.py:23,36-38,46,55`, `slack.py:62,71`, `pushbullet.py:33,41` |
| **Status** | [ ] Not Fixed |
| **Priority** | Medium |

**Description:**
No test instantiates any of the three providers. Discord's 204-only success check, Slack's `hooks.slack.com` URL-prefix rule, and Pushbullet's header/status handling are all unverified.

**Impact:**
A well-meaning normalization (e.g. Discord 204→200) would silently break real delivery for that provider with CI staying green — only observable against the live API.

**Suggested Fix:**
Add per-provider unit tests mocking `requests.post`, asserting exact success status codes, payload shape, and `validate_config()` acceptance/rejection.

---

### Low Priority

#### Finding 15: logout_view Accepts GET and Flushes the Session

| | |
|---|---|
| **Location** | `backup/views.py:306-309` |
| **Status** | [ ] Not Fixed |
| **Priority** | Low |

No `@require_POST` guard; a cross-site GET or browser prefetch to `/logout/` silently ends the session (nuisance denial-of-session, no data loss). **Fix:** add `@require_POST` and drive logout from a CSRF-protected form, matching ADR-0001's original design (which specifies POST).

---

#### Finding 16: Refresh Job's remove_job/add_job Window Can Drop a Due Backup Run

| | |
|---|---|
| **Location** | `backup/management/commands/runapscheduler.py:87,115-125` |
| **Status** | [ ] Not Fixed |
| **Priority** | Low |

`remove_job` then `add_job` are separate lock acquisitions; a scheduler tick landing in that gap silently misses the job and pushes its next fire to the following cron period. **Fix:** drop the explicit `remove_job` call — `add_job(..., replace_existing=True)` already swaps atomically.

---

#### Finding 17: NotificationService Lazy Executor and Singleton Are Not Thread-Safe

| | |
|---|---|
| **Location** | `backup/services/notifications/service.py:39-44,122-127` |
| **Status** | [ ] Not Fixed |
| **Priority** | Low |

Unlike `config.py`'s double-checked-locking singleton, `service.py`'s lazy `ThreadPoolExecutor` and module singleton have no lock. Concurrent first-use from two scheduler threads can construct duplicates (verified low-impact: leaked executors are still joined at interpreter exit). **Fix:** apply the same `threading.Lock` double-checked pattern used in `config.py`.

---

#### Finding 18: NOTIFY_ON_CONNECTION_LOST Is Advertised but Never Emitted

| | |
|---|---|
| **Location** | `backup/services/discovery_service.py:200-213`, `backup/services/notifications/base.py:15` |
| **Status** | [ ] Not Fixed |
| **Priority** | Low |

The `CONNECTION_LOST` event and its settings toggle exist and are wired into `should_notify`, but `check_connections()` never actually emits it — the documented toggle is a silent no-op. **Fix:** emit `NotificationEvent.CONNECTION_LOST` from `check_connections()` on an `ok → unreachable` transition, or remove the setting from `.env.example`/ADR-0009 until implemented.

---

#### Finding 19: Dead "if not config" Guards Misrepresent the Orphaned-Instance Model

| | |
|---|---|
| **Location** | `backup/views.py:205-206,231-233`, `backup/templates/backup/instance_dashboard.html:33` |
| **Status** | [ ] Not Fixed |
| **Priority** | Low |

`BackupRecord.config` is a non-nullable CASCADE FK and can never be falsy; these guards (and a matching template branch) are unreachable dead code that implies a data model that doesn't exist. **Fix:** delete the three dead branches (ADR-0014 already planned this cleanup for `views.py` but missed these).

---

#### Finding 20: 401 Re-Auth-and-Retry Logic Triplicated in PiholeV6Client

| | |
|---|---|
| **Location** | `backup/services/pihole_client.py:101-111,140-155,184-200` |
| **Status** | [ ] Not Fixed |
| **Priority** | Low |

The re-auth-on-401 sequence is copy-pasted three times and has already drifted — the retry-path download skips the Content-Type sanity check the happy path performs. **Fix:** extract a single `_request_with_reauth()` helper.

---

#### Finding 21: _calculate_checksum Duplicated Verbatim

| | |
|---|---|
| **Location** | `backup/services/backup_service.py:85-91`, `backup/services/restore_service.py:32-38` |
| **Status** | [ ] Not Fixed |
| **Priority** | Low |

The write-side and verify-side of the same SHA256 integrity contract are two separate copies with no backup→restore round-trip test to catch drift. **Fix:** move to one shared module-level function.

---

#### Finding 22: dashboard() Single-Instance Branch Duplicates instance_dashboard()'s Context

| | |
|---|---|
| **Location** | `backup/views.py:36-51,79-96` |
| **Status** | [ ] Not Fixed |
| **Priority** | Low |

Identical context-building logic exists in two places; a future context key added to only one path renders silently blank on the other. **Fix:** extract a shared `_render_instance_dashboard()` helper.

---

#### Finding 23: cleanup() Kills a Stale SCHEDULER_PID After a Monitor-Driven Restart

| | |
|---|---|
| **Location** | `entrypoint.sh:17,23,39,54,58-66` |
| **Status** | [ ] Not Fixed |
| **Priority** | Low |

After a scheduler restart inside the monitor subshell, the parent shell's `SCHEDULER_PID` still points at the dead original process, so the SIGTERM trap never signals the replacement — it dies by SIGKILL at container teardown instead. Verified low-impact since the scheduler has no SIGTERM handler either way. **Fix:** track the scheduler PID in a file the parent trap re-reads.

---

#### Finding 24: Build-Time collectstatic Bakes a Fallback Secret Key Into Image Layers

| | |
|---|---|
| **Location** | `Dockerfile:39-41` |
| **Status** | [ ] Not Fixed |
| **Priority** | Low |

`collectstatic` runs with no `SECRET_KEY` set, so a random key is written into `/app/data/.secret_key` inside the published, public image layer. Shadowed by the `./data` volume mount under the shipped compose file; only reachable via an undocumented bare `docker run`. **Fix:** set a throwaway build-only key for the collectstatic step and remove the generated file afterward.

---

#### Finding 25: CI/Publish Workflows Delegate to a Mutable @v2 Ref With secrets: inherit

| | |
|---|---|
| **Location** | `.github/workflows/ci.yml:14,26`, `build-and-push.yml:17,31`, `cleanup-pr-image.yml:9` |
| **Status** | [ ] Not Fixed |
| **Priority** | Low |

All three workflows call an external reusable workflow repo (`ljmerza/misc-actions`) at a mutable `@v2` tag (confirmed to have already been re-pointed once) with `secrets: inherit` and `packages: write`/`id-token: write` permissions. **Fix:** pin to a full commit SHA and replace `secrets: inherit` with an explicit secrets mapping.

---

#### Finding 26: env_prefix Validator and Unique Constraint Never Asserted by Any Test

| | |
|---|---|
| **Location** | `backup/models.py:39-47` |
| **Status** | [ ] Not Fixed |
| **Priority** | Low |

No test exercises the `RegexValidator` or `unique=True` constraint in the rejecting direction. **Fix:** add `backup/tests/unit/test_models.py` covering invalid `env_prefix` values and duplicate-prefix creation.

---

#### Finding 27: Telegram send() Assembly Untested Beyond _escape_markdown

| | |
|---|---|
| **Location** | `backup/services/notifications/telegram.py:40-77` |
| **Status** | [ ] Not Fixed |
| **Priority** | Low |

The `_escape_markdown` helper has 13 passing unit tests, but nothing tests whether `send()` actually applies it to every field, or the MarkdownV2/status-code handling. **Fix:** add a `TelegramProvider.send()` test with special characters in every field.

---

#### Finding 28: _get_app_info() Env-Var Precedence and Git Fallback Untested

| | |
|---|---|
| **Location** | `backup/context_processors.py:9-36` |
| **Status** | [ ] Not Fixed |
| **Priority** | Low |

Runs on every template render; zero test coverage of the `PackageNotFoundError` fallback, `GIT_COMMIT_SHORT` precedence, or the git-subprocess `except Exception` swallowing (unreachable in the production image today, which has no git binary — but only by accident of the current exception handling being broad). **Fix:** add unit tests for each branch with the `lru_cache` cleared between cases.

---

#### Finding 29: discover_instances CLI Wrapper Never Invoked by Any Test

| | |
|---|---|
| **Location** | `backup/management/commands/discover_instances.py:23-46` |
| **Status** | [ ] Not Fixed |
| **Priority** | Low |

Only the underlying `discover_instances_from_env` is unit-tested — the CLI wrapper's `--force`/`--skip-check` flag wiring and output formatting are not. `entrypoint.sh` runs this under `set -e` on every container boot, so a flag-wiring regression would crash-loop the container with the suite staying green. **Fix:** add a `call_command('discover_instances')` test covering both flags.

---

## Decision

Track all 29 findings in this ADR. Suggested remediation order:

### Phase 1: Correctness (backups must actually run and actually delete/restore what they claim to)
1. Finding 1: Removed instances never reactivate
2. Finding 3: delete_backup false-success response
3. Finding 5: Non-ZIP responses stored as successful backups
4. Finding 4 / 10: Scheduler-exhaustion doesn't stop the container

### Phase 2: Security Hardening
5. Finding 6: Path-containment guard on download/restore
6. Finding 2: Session/CSRF cookie Secure flags
7. Finding 7: Non-root container user
8. Finding 9: Compose SECRET_KEY placeholder

### Phase 3: Test Coverage (notification layer and metrics)
9. Finding 11: metrics_service assertions
10. Findings 12–14: notification provider tests

### Phase 4: Quality / Low-Priority Cleanup
11. Findings 8, 15–29 as time permits

---

## Consequences

### Positive
- Single tracking document for all 29 findings, consistent with this project's existing ADR-0011/0013 convention.
- Findings are pre-filtered by adversarial verification, reducing false-positive remediation effort.
- Clear prioritization separates backup-correctness risk (Phase 1) from hardening and coverage work (Phases 2–4).

### Negative
- Development and review effort required to work through 29 items.
- Some fixes (e.g. Finding 7's non-root user, Finding 9's compose default) require operators to re-pull/redeploy, not just a code change.

### Mitigations
- Fix and land findings incrementally with regression tests per finding, as ADR-0011/0013 did.
- Re-run `docs/AUDIT-2026-07-02.md`'s dimensions (or a future fable-audit pass) after remediation to confirm no regressions.

---

## Progress Tracking

| Finding | Priority | Status |
|---------|----------|--------|
| 1 | High | Not Fixed |
| 2 | Medium | Not Fixed |
| 3 | Medium | Not Fixed |
| 4 | Medium | Not Fixed |
| 5 | Medium | Not Fixed |
| 6 | Medium | Not Fixed |
| 7 | Medium | Not Fixed |
| 8 | Medium | Not Fixed |
| 9 | Medium | Not Fixed |
| 10 | Medium | Not Fixed |
| 11 | Medium | Not Fixed |
| 12 | Medium | Not Fixed |
| 13 | Medium | Not Fixed |
| 14 | Medium | Not Fixed |
| 15 | Low | Not Fixed |
| 16 | Low | Not Fixed |
| 17 | Low | Not Fixed |
| 18 | Low | Not Fixed |
| 19 | Low | Not Fixed |
| 20 | Low | Not Fixed |
| 21 | Low | Not Fixed |
| 22 | Low | Not Fixed |
| 23 | Low | Not Fixed |
| 24 | Low | Not Fixed |
| 25 | Low | Not Fixed |
| 26 | Low | Not Fixed |
| 27 | Low | Not Fixed |
| 28 | Low | Not Fixed |
| 29 | Low | Not Fixed |

---

## References

- [docs/AUDIT-2026-07-02.md](../AUDIT-2026-07-02.md) — full audit report with per-finding verifier evidence and methodology
- [ADR-0011](0011-bug-review-findings.md) — precedent for bundling review findings into one ADR
- [ADR-0013](0013-reliability-security-fixes.md) — precedent, second bug-review pass
- [ADR-0001](0001-pihole-backup-architecture.md) — original architecture, referenced by Findings 2 and 7
- [ADR-0016](0016-prometheus-metrics-endpoint.md) — referenced by Finding 11
- Commit `713d1ac` — the five issues it fixed are explicitly out of scope for this ADR
