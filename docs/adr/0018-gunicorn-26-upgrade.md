# ADR-0018: Gunicorn 26.0 Upgrade

**Status:** Implemented
**Date:** 2026-05-09
**Deciders:** Leonardo Merza

## Context

### Background

The container ships with `gunicorn==23.0.0` (current floor `gunicorn>=21.0`).
Three majors have shipped since: 24.0.0, 25.0.0, 26.0.0. Per the 2026-05-09
dependency audit (`docs/dep-upgrade-2026-05-09.md`), the bump was held back
under the skill rule "majors are always HOLD_BACK regardless of release-note
content" pending a deliberate decision. This ADR is that decision.

### Current State

- `gunicorn==23.0.0`, sync worker, no eventlet/gevent.
- Invocation in `entrypoint.sh:71`:
    `gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 2 --access-logfile - --error-logfile -`
- Container starts gunicorn in the background after migrations and the
  APScheduler subprocess (ADR-0003); `entrypoint.sh:67` traps SIGTERM/SIGINT
  and forwards to gunicorn so docker stop is graceful.
- Python 3.12 (Dockerfile).
- Reverse proxy: deployments live behind a homelab Caddy/nginx/Traefik (this
  is the assumed posture; the container exposes 8000 with no in-container
  TLS).

### Cross-major impact summary (per release-notes investigation)

| Area | 24.0.0 | 25.0.0 | 26.0.0 |
|------|--------|--------|--------|
| Sync worker behavior | unchanged | unchanged | unchanged |
| CLI flags we use (`--bind`, `--workers`, `--access-logfile`, `--error-logfile`) | unchanged | unchanged | unchanged |
| Signal handling (SIGTERM=graceful, SIGINT/SIGQUIT=fast) | unchanged | clarified for ASGI; sync unchanged | unchanged |
| Logging defaults (stdout/stderr `-`) | unchanged | unchanged | unchanged |
| `requires-python` floor | `>=3.7` | `>=3.10` | `>=3.10` (3.10–3.13 classified) |
| Notable additions | ASGI worker (beta), uWSGI binary protocol | Dirty arbiters, HTTP/2 beta, HTTP 103 Early Hints | RFC 9112 HTTP/1.1 strictness, eventlet removed, gunicorn_h1c C parser |
| Required `entrypoint.sh` edits | none | none | none |

### Requirements

- `entrypoint.sh` must continue to start gunicorn the same way.
- SIGTERM-from-docker must continue to drain in-flight requests and exit
  cleanly within the graceful timeout.
- `/`, `/login/`, `/health/`, `/metrics/`, and AJAX endpoints
  (`/backup/run/`, `/backup/<id>/delete/`, `/test-connection/`) must all
  return successful responses through the upstream reverse proxy.
- 214 existing tests must pass (gunicorn isn't exercised by the test
  suite directly — Django uses its own test client — so testing here is
  smoke + behavioral).

### Constraints

- Eventlet is removed in 26.0. We don't use it; non-issue.
- 26.0 enforces RFC 9112 HTTP/1.1 strictness: rejects authority-form
  request-targets outside CONNECT, asterisk-form outside OPTIONS, relative
  references, control chars in header values, forbidden trailer field
  names, and Content-Length list-form. Caddy/nginx/Traefik all normalize
  the request line before forwarding, so production is unaffected. The
  realistic surface is direct-curl smoke tests against `:8000` from
  inside the homelab (e.g. health probes that hit container directly).

## Options Considered

### Option 1: Direct bump to 26.0.x

**Description:** `pyproject.toml` `gunicorn>=21.0` → `gunicorn>=26.0,<27.0`,
re-lock, smoke-test, ship in one PR.

**Pros:**
- Simplest; one PR.
- All three majors landed without changes affecting our invocation path.
- We immediately benefit from the 26.0 request-smuggling and HTTP-parser
  hardening, which is a security improvement for any deployment that
  hasn't yet wrapped the container in a normalizing reverse proxy.

**Cons:**
- Three majors at once means slightly less ability to bisect if a
  scheduler/web interaction surprises us.

### Option 2: Step-bump 23 → 24 → 25 → 26 across separate PRs

**Description:** Three PRs, one per major, each with its own smoke.

**Pros:**
- Easy bisect if something regresses.
- Easier rollback granularity.

**Cons:**
- 3× the PR overhead with no observable difference for sync-worker users.
- The release-note investigation found no breaking change for our
  configuration in 24.0 or 25.0 — there is nothing to attribute a
  regression to.

### Option 3: Replace gunicorn with uvicorn / granian

**Description:** Migrate to an ASGI server.

**Pros:**
- Future-proofs for any ASGI work (Django channels, async views).
- Granian in particular is faster for many workloads.

**Cons:**
- We're a synchronous Django app with no current ASGI ambition.
- Different signal/lifecycle semantics need fresh validation against
  `entrypoint.sh`.
- This is an ADR scope creep — out of band for a maintenance bump.

## Decision

**Chosen Option:** Option 1 — Direct bump to 26.0.x.

**Rationale:** Sync-worker semantics, our CLI surface, signal handling,
and stdout logging are stable across all three majors per the gunicorn
maintainers' release notes. The only material change is RFC 9112 strictness
in 26.0, which a normalizing reverse proxy renders moot. Stepping through
24 and 25 individually creates PR overhead with no observable benefit for
this configuration.

## Consequences

### Positive
- Up-to-date HTTP parser with request-smuggling hardening.
- C-accelerated parser (`gunicorn_h1c`) becomes the default on CPython —
  modest throughput improvement.
- Removes the deprecated-eventlet code path from the install footprint.
- Aligns the floor pin with what we actually want to support
  (`>=26.0,<27.0` mirrors the existing `Django>=5.0,<6.0`-style bounds).

### Negative
- A direct curl probe against `:8000` that uses unusual request-line shapes
  (e.g. someone hand-typing `OPTIONS *`) will now 400. This is correct
  behavior; mention in the runbook only if the homelab dashboards/probes
  do it today.

### Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Reverse proxy emits a request shape 26.0 rejects | Low | Medium | Caddy/nginx/Traefik all normalize; smoke through the proxy in staging before merging |
| Container shutdown semantics regress (SIGTERM forwarding) | Low | Medium | `docker compose stop checkpoint-pihole`; expect graceful drain in logs, no SIGKILL after grace period |
| New C parser surfaces bug we don't have CI coverage for | Low | Low | Smoke a backup-zip download (large response body); regression would manifest as truncated/corrupt download |
| Health check breaks (curl loop/probe) | Medium | Low | Verify the existing healthcheck still returns 200 from inside the container; trivial fix if it doesn't |
| `--access-logfile -` formatting differs subtly | Low | Low | Smoke confirms stdout still flows; downstream log scrapers are out of scope |

## Implementation Plan

### Single upgrade PR
- [ ] Branch: `chore/gunicorn-26-upgrade`
- [ ] `pyproject.toml`: change `gunicorn>=21.0` → `gunicorn>=26.0,<27.0`
- [ ] `uv lock --upgrade-package gunicorn` (do NOT run a full `uv lock --upgrade`)
- [ ] `uv run ruff check . && uv run ruff format --check .`
- [ ] `uv run pytest` — all 214 must pass (gunicorn isn't directly tested but pytest-django stand-alone test client must keep working)
- [ ] Manual smoke (sequence matters):
    1. `docker compose up --build` — confirm `[4/4] Starting web server...` log line and gunicorn boot lines (`Listening at: http://0.0.0.0:8000`, `Using worker: sync`, `Booting worker with pid: ...`)
    2. `curl -i http://localhost:8000/health/` — expect 200 JSON
    3. `curl -i http://localhost:8000/metrics/` — expect 200, Prometheus exposition body
    4. `curl -i http://localhost:8000/` — expect 200 (or 302 → /login/ if auth on)
    5. `curl -i -X POST http://localhost:8000/backup/run/<config_id>/` (with CSRF token) — expect a 2xx and a `BackupRecord` row appears
    6. Download the latest backup ZIP via the dashboard — confirm bytes match (`sha256sum` against the stored file)
    7. `docker compose stop checkpoint-pihole` — observe in logs: `Handling signal: term`, workers gracefully exit, container exits 0 within `graceful_timeout` (default 30s). No SIGKILL.
- [ ] If smoke is green: commit, push, open PR. PR body links this ADR.
- [ ] After merge, update this ADR's Status to `Implemented`.

### Index update
- [ ] Update `docs/adr/0000-index.md` row + Summary-by-Status counts

## Related ADRs

- [ADR-0003](./0003-single-container-architecture.md) — Defines `entrypoint.sh` two-process layout that signal-forwarding must keep working
- [ADR-0017](./0017-django-6-upgrade.md) — Companion framework upgrade; gunicorn 26 + Django 6 are compatible (both stable on Python 3.12, both speak unchanged WSGI). The two ADRs may merge in either order; if both ship in the same week, do gunicorn first because its surface is smaller.

## References

- [gunicorn 24.0.0 release](https://github.com/benoitc/gunicorn/releases/tag/24.0.0)
- [gunicorn 25.0.0 release](https://github.com/benoitc/gunicorn/releases/tag/25.0.0)
- [gunicorn 26.0.0 release](https://github.com/benoitc/gunicorn/releases/tag/26.0.0)
- [gunicorn settings reference](https://docs.gunicorn.org/en/stable/settings.html)
- [RFC 9112 (HTTP/1.1 Messaging)](https://www.rfc-editor.org/rfc/rfc9112.html)
