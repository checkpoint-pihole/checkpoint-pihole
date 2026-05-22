# ADR-0017: Django 6.0 Upgrade

**Status:** Implemented
**Date:** 2026-05-09
**Deciders:** Leonardo Merza

## Context

### Background

Django 6.0 was released and is the current latest stable; the project pin
`Django>=5.0,<6.0` in `pyproject.toml` blocks adoption. Django 5.2 is an LTS
(security fixes through Apr 2028), so there is no urgency from upstream
support, but Django 6.0 ships several features we'd benefit from
(built-in CSP middleware, template partials, modernized email API,
background tasks framework) and the codebase audit shows we are already
clean of every API removed or deprecated in 5.x → 6.0.

### Current State

- Django 5.2.10 installed; pin `Django>=5.0,<6.0` in `pyproject.toml`.
- Python 3.12 (see `Dockerfile` line 1, `pyproject.toml` `requires-python = ">=3.12"`).
- SQLite backing store (Bookworm-based `python:3.12-slim` ships SQLite ≥3.40, which exceeds Django 6.0's 3.31+ requirement).
- Apps: `INSTALLED_APPS` is `admin/auth/contenttypes/sessions/messages/staticfiles + django_apscheduler + backup` (`config/settings.py:59`).
- Middleware: standard Django 5.x list plus `whitenoise.middleware.WhiteNoiseMiddleware` and `backup.middleware.simple_auth.SimpleAuthMiddleware` (`config/settings.py:70`).
- Storage: modern `STORAGES` dict (`config/settings.py:134`).
- `DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"` already set (`config/settings.py:143`).
- Test surface: `pytest-django==4.12.0` (post-PR #30) which already advertises Django 6.0 support.

### Codebase audit — what we already do right

A full grep across the project found **zero** uses of:

- `django.utils.timezone.utc`, `force_text`, `force_bytes` (legacy aliases)
- `django.contrib.postgres.fields.JSONField`
- `django.conf.urls.url()` (we use `path()` everywhere)
- `request.is_ajax()`
- `MIDDLEWARE_CLASSES`, `TEMPLATE_DIRS`, etc. (legacy settings)
- `django.core.urlresolvers` (use `django.urls`)
- `format_html()` no-arg calls
- `CheckConstraint(check=...)` — we have no `CheckConstraint`s
- `register_converter(...)` overrides
- Custom `ModelAdmin.lookup_allowed()` overrides
- Custom `ChoicesMeta`, custom `as_sql()`, custom `Field.pre_save()`
- `pytz` imports

The only structural touchpoint is the `Django>=5.0,<6.0` constraint itself.

### Requirements

- Stay on Python 3.12 (Django 6.0 supports 3.12/3.13/3.14).
- Keep SQLite as the backing store.
- All 214 existing tests must continue to pass.
- The container must still come up via `entrypoint.sh` (migrations → discover → scheduler → gunicorn).
- No regression in `/health/`, `/metrics/`, dashboard, settings, or backup-trigger flows.
- Pi-hole v6 backup integrations (HTTP client, retention, scheduler) unaffected.

### Constraints

- **`django-apscheduler` is the single risk surface.** PyPI classifiers for
  the latest release (0.7.0, Sep 2024) list `Framework :: Django :: 4.2 / 5.0 / 5.1`
  only — no 5.2 and no 6.0. The library uses standard ORM and migrations,
  so it should run on Django 6, but maintainer-verified support is absent.
- The schedule loop runs in a separate process from gunicorn (ADR-0003);
  scheduler breakage manifests as missed backups, not 500s.
- We can't reach Django 6 incrementally — it's a single pin lift.

## Options Considered

### Option 1: Lift the pin to `Django>=5.0,<7.0` and bump

**Description:** Change `pyproject.toml` to `Django>=5.0,<7.0`, run
`uv lock --upgrade-package django`, run the test suite, smoke-test the
container, and ship.

**Pros:**
- Lowest churn — one constraint change.
- Captures the full Django 6.0 feature set immediately.
- Codebase audit shows zero required code changes.
- Keeps us on the latest non-LTS for a year, then the 6.x LTS lands.

**Cons:**
- Carries the `django-apscheduler` unverified-compat risk for the lifetime
  of the upgrade until upstream releases a Django-6-tagged version.
- If the scheduler breaks at runtime in a way the test suite doesn't
  cover, we discover it in production (degraded backups).

### Option 2: Stay on Django 5.2 LTS, defer 6.0

**Description:** Keep the `<6.0` pin, document why, revisit when Django
6.x LTS is announced (~Apr 2027 based on the 5.2 LTS lifecycle).

**Pros:**
- Maximum stability; LTS line gets security fixes through Apr 2028.
- Avoids the `django-apscheduler` compat unknown.

**Cons:**
- Forgoes built-in CSP middleware (we'd otherwise add this manually for
  the dashboard if hardening is pursued).
- Locks us into 5.x ecosystem dependencies for another ~12 months.
- Doesn't materially reduce risk — Django 6 will still need to be
  adopted later, and the same `django-apscheduler` question will apply.

### Option 3: Test Django 6 against `django-apscheduler` first, then bump

**Description:** Spike on a throwaway branch — bump to Django 6, run the
existing test suite plus a manual scheduler smoke (kick the
`runapscheduler` command, watch a job execute), confirm no breakage, then
proceed with Option 1 with empirical evidence in hand.

**Pros:**
- Closes the only meaningful risk surface before committing.
- Keeps the upgrade itself a one-liner; the spike is just verification.
- Surfaces breakage in development, not production.

**Cons:**
- One extra cycle of effort vs. Option 1.
- If the spike reveals a real incompatibility, we either patch
  `django-apscheduler` ourselves or fall back to Option 2 anyway.

## Decision

**Chosen Option:** Option 3 — Spike `django-apscheduler` against Django 6 first, then bump.

**Rationale:** The library is the only unknown; everything else in the
codebase audited clean. A short spike collapses the risk to "we tested
it and it works" without committing the upgrade until we have evidence.
If the spike fails, Option 2 remains available with no sunk cost in the
main branch.

## Consequences

### Positive
- Uses up-to-date Django (security fixes, performance work, new features).
- Built-in CSP middleware available if/when the dashboard hardens.
- Template partials and the new email API simplify any future feature
  work that touches them.
- Aligns with `pytest-django 4.12`, which already supports Django 6.

### Negative
- One additional cycle of effort vs. a blind bump.
- Existing migrations remain valid but new migrations created post-upgrade
  use Django 6 migration semantics (interoperable, but not back-portable
  to 5.x without care).

### Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| `django-apscheduler` runtime break on Django 6 | Medium | High (silent missed backups) | Spike before merging; smoke `runapscheduler` end-to-end; pin to last-known-good if upstream regresses |
| Email API changes break failure notifications | Low | Medium | We use the high-level `EmailMessage` API; smoke-test the failure-notification path against an SMTP test container |
| `format_html` / `urlize` HTTPS default flip surfaces in templates | Low | Low | Audit confirmed no usages; CI catches regressions |
| `STORAGES` `ManifestStaticFilesStorage` ordering change leaks into static manifest | Low | Low | We don't currently use `ManifestStaticFilesStorage` (`STORAGES["staticfiles"]` is whitenoise's compressed variant); confirm before merge |
| New `BigAutoField` default behavior on new apps | Low | Low | Already set explicitly in settings; existing apps unaffected |
| Django 6 incompatibility surfaces post-merge in code path tests don't cover | Low | Medium | Smoke test covers entrypoint + dashboard + scheduler tick + backup creation + retention + metrics scrape |

## Implementation Plan

### Phase 0 — `django-apscheduler` Django-6 spike (throwaway branch)
- [ ] Branch: `spike/django-apscheduler-django-6`
- [ ] Edit `pyproject.toml` to `Django>=5.0,<7.0`; `uv lock --upgrade-package django`
- [ ] `uv run pytest` — confirm 214 pass
- [ ] `docker compose up --build` — confirm container boots, migrations run, no startup errors from `django_apscheduler` admin/migrations
- [ ] Run a manual smoke: `docker compose exec checkpoint-pihole uv run python manage.py runapscheduler` for a minute, verify the scheduler initializes and `DjangoJobStore` reads/writes to `django_apscheduler_djangojob` and `django_apscheduler_djangojobexecution` tables without errors
- [ ] Trigger one ad-hoc backup via `apscheduler_run_job` or by setting a 1-minute frequency; verify a `BackupRecord` is created
- [ ] If clean: proceed to Phase 1. If broken: file the failure mode in the issue tracker, fall back to Option 2 (close this ADR as Rejected), and update `0000-index.md` accordingly.

### Phase 1 — Upgrade PR
- [ ] Branch: `chore/django-6-upgrade`
- [ ] `pyproject.toml`: change `Django>=5.0,<6.0` → `Django>=5.0,<7.0`
- [ ] `uv lock --upgrade-package django` (do NOT run a full `uv lock --upgrade` — we want only the Django bump in this PR)
- [ ] `uv run ruff check . && uv run ruff format --check .`
- [ ] `uv run pytest` — all 214 must pass
- [ ] Smoke (mirroring Phase 0): `docker compose up --build`, hit `/`, `/health/`, `/metrics/`, trigger a backup, watch scheduler tick once
- [ ] Commit: `chore(deps): upgrade Django to 6.0` with body referencing this ADR
- [ ] PR title: `chore(deps): upgrade Django to 6.0`
- [ ] PR body: link this ADR + Phase 0 spike findings
- [ ] After merge, update this ADR's Status to `Implemented`

### Phase 2 — Index update
- [ ] Update `docs/adr/0000-index.md` row + Summary-by-Status counts

## Related ADRs

- [ADR-0001](./0001-pihole-backup-architecture.md) — Defines the Django 5.x baseline
- [ADR-0003](./0003-single-container-architecture.md) — Two-process layout that makes scheduler smoke testing distinct
- [ADR-0010](./0010-env-var-credentials.md) — Settings shape that must keep working
- [ADR-0016](./0016-prometheus-metrics-endpoint.md) — `/metrics/` endpoint that must keep producing valid output
- [ADR-0018](./0018-gunicorn-26-upgrade.md) — Companion infra upgrade (independent merge order, but verified compatible)

## References

- [Django 6.0 release notes](https://docs.djangoproject.com/en/6.0/releases/6.0/)
- [Django deprecation timeline](https://docs.djangoproject.com/en/6.0/internals/deprecation/)
- [Django supported versions](https://www.djangoproject.com/download/#supported-versions)
- [django-apscheduler PyPI](https://pypi.org/project/django-apscheduler/)
- [django-apscheduler issues — Django 6](https://github.com/jcass77/django-apscheduler/issues?q=Django+6)
- [pytest-django 4.12 changelog](https://github.com/pytest-dev/pytest-django/blob/main/docs/changelog.rst)
