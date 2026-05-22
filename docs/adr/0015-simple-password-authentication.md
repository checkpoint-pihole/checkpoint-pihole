# ADR-0015: Simple Password Authentication

**Status:** Accepted
**Date:** 2026-04-14
**Deciders:** Leonardo Merza

## Context

### Background

Checkpoint Pi-hole needs optional authentication to protect the web UI. The design goal is Pi-hole-style simplicity: set a password, it just works. No usernames, no database-stored credentials, no extra configuration.

### Current State

The app already has a working simple auth system:
- `APP_PASSWORD` env var for the password
- `REQUIRE_AUTH` env var to enable/disable
- `SimpleAuthMiddleware` redirects unauthenticated requests to `/login/`
- Session-based (Django's `django_session` table in SQLite)
- Rate limiting: 5 attempts per minute per IP

Two issues needed fixing:
1. **Plain-text `==` comparison** — vulnerable to timing attacks, password visible in memory as plain text
2. **Session lifetime** — Django default of 2 weeks is too long for a security-sensitive app

### Requirements

- Password set via single env var (`APP_PASSWORD`)
- No username — password only
- No database storage for credentials
- Secure against timing attacks
- Simple for users — just set an env var and it works

### Constraints

- Single Docker container deployment
- Must work with existing env var pattern (`PIHOLE_{PREFIX}_URL`, etc.)
- No additional dependencies beyond Django

## Options Considered

### Option 1: Hash on Startup (PBKDF2)

**Description:** Read plain-text `APP_PASSWORD` from env var, hash it once at Django startup using `make_password()` (PBKDF2), store only the hash in memory. Use `check_password()` for constant-time comparison on login.

**Pros:**
- Password only exists as plain text briefly during startup
- Constant-time comparison prevents timing attacks
- Uses Django's battle-tested password hashing (PBKDF2 with 870,000 iterations)
- Zero UX change — user still just sets `APP_PASSWORD=mysecret`
- No extra dependencies

**Cons:**
- Password is still plain text in the env var and briefly in memory at startup
- Small startup cost for hashing (negligible)

### Option 2: Constant-Time Compare Only

**Description:** Keep plain-text password in memory, but replace `==` with `hmac.compare_digest()` to prevent timing attacks.

**Pros:**
- Minimal code change
- Prevents timing attacks

**Cons:**
- Password stays as plain text in memory for the entire process lifetime
- Visible via `/proc` or memory dumps
- Doesn't use Django's password infrastructure

### Option 3: Pre-Hashed Env Var

**Description:** User provides an already-hashed password in the env var (generated via a CLI helper command).

**Pros:**
- Password never exists in plain text anywhere
- Most secure option

**Cons:**
- Terrible UX — user must run a hash command before setting the env var
- Breaks the "just set it and it works" principle
- Confusing env var value (long hash string)

## Decision

**Chosen Option:** Hash on Startup (PBKDF2)

**Rationale:** Best balance of security and simplicity. The password is hashed immediately at startup and the raw value is deleted from settings. Users just set `APP_PASSWORD=whatever` and it works — same UX as before but with proper cryptographic comparison. Django's `check_password()` provides constant-time comparison and PBKDF2 hashing out of the box.

Sessions expire when the browser closes (`SESSION_EXPIRE_AT_BROWSER_CLOSE = True`) instead of lasting 2 weeks.

## Consequences

### Positive
- Password no longer stored as plain text in application memory
- Timing attacks prevented via constant-time hash comparison
- Sessions don't persist across browser restarts
- Zero UX change for users

### Negative
- Password is still plain text in the env var (inherent to the env var approach)
- Users must re-login after closing the browser

### Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Env var password visible in Docker inspect | Low | Medium | Standard Docker security practice; same as Pi-hole |
| Session fixation | Low | Low | Django's session framework handles this |
| Brute force via distributed IPs | Low | Medium | Existing rate limiting (5/min/IP) provides baseline protection |

## Implementation Plan

- [x] Hash `APP_PASSWORD` at startup in `config/settings.py` using `make_password()`
- [x] Replace `==` comparison with `check_password()` in `backup/views.py`
- [x] Update middleware guard from `APP_PASSWORD` to `APP_PASSWORD_HASH` in `backup/middleware/simple_auth.py`
- [x] Add `SESSION_EXPIRE_AT_BROWSER_CLOSE = True` to settings
- [x] Update test fixtures to use `make_password()` for `APP_PASSWORD_HASH`

## Related ADRs

- [ADR-0010](./0010-env-var-credentials.md) - Environment variable credential pattern
- [ADR-0013](./0013-reliability-security-fixes.md) - Prior security fixes

## References

- [Django Password Management](https://docs.djangoproject.com/en/5.2/topics/auth/passwords/)
- [OWASP Password Storage Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)
