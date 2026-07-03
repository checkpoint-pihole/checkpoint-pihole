# ADR-0000: Architecture Decision Records Index

This document serves as the index for all Architecture Decision Records (ADRs) in the Checkpoint Pi-hole project.

---

## ADR Status Definitions

| Status | Description |
|--------|-------------|
| **Proposed** | Under discussion, not yet accepted |
| **Accepted** | Decision has been accepted but not yet implemented |
| **Implemented** | Decision has been accepted and fully implemented |
| **Deprecated** | Decision is no longer relevant or has been superseded |
| **Superseded** | Replaced by a newer ADR |

---

## ADR Index

| ADR | Title | Status | Date |
|-----|-------|--------|------|
| [ADR-0001](0001-pihole-backup-architecture.md) | Pi-hole v6 Backup Application Architecture | Implemented | 2026-01-18 |
| [ADR-0002](0002-offline-static-assets.md) | Offline Static Assets (Remove CDN Dependencies) | Implemented | 2026-01-18 |
| [ADR-0003](0003-single-container-architecture.md) | Single Container Architecture | Implemented | 2026-01-18 |
| [ADR-0004](0004-manual-backup-ui-refresh.md) | Manual Backup Trigger with UI Refresh on Completion | Implemented | 2026-01-18 |
| [ADR-0005](0005-testing-strategy.md) | Testing Strategy and Workflow | Implemented | 2026-01-18 |
| [ADR-0006](0006-github-docker-publish.md) | GitHub Actions Docker Image Publishing | Implemented | 2026-01-18 |
| [ADR-0007](0007-github-test-workflow.md) | GitHub Actions Test Workflow Integration | Implemented | 2026-01-18 |
| [ADR-0008](0008-one-click-restore.md) | One-Click Restore | Implemented | 2026-01-18 |
| [ADR-0009](0009-backup-failure-notifications.md) | Backup Failure Notifications | Implemented | 2026-01-18 |
| [ADR-0010](0010-env-var-credentials.md) | Replace Encrypted Database Fields with Environment Variables | Implemented | 2026-01-18 |
| [ADR-0011](0011-bug-review-findings.md) | Bug Review Findings and Remediation Plan | Implemented | 2026-01-18 |
| [ADR-0012](0012-dark-mode-toggle.md) | Dark Mode Toggle | Implemented | 2026-01-19 |
| [ADR-0013](0013-reliability-security-fixes.md) | Reliability and Security Fixes | Implemented | 2026-01-19 |
| [ADR-0014](0014-multi-instance-support.md) | Multi-Instance Pi-hole Support | Implemented | 2026-04-07 |
| [ADR-0015](0015-simple-password-authentication.md) | Simple Password Authentication | Accepted | 2026-04-14 |
| [ADR-0016](0016-prometheus-metrics-endpoint.md) | Prometheus Metrics Endpoint | Accepted | 2026-04-16 |
| [ADR-0017](0017-django-6-upgrade.md) | Django 6.0 Upgrade | Implemented | 2026-05-09 |
| [ADR-0018](0018-gunicorn-26-upgrade.md) | Gunicorn 26.0 Upgrade | Implemented | 2026-05-09 |
| [ADR-0019](0019-fable-audit-findings-2026-07-02.md) | Fable Audit Findings and Remediation Plan (2026-07-02) | Proposed | 2026-07-02 |

---

## Summary by Status

### Implemented (16)
- ADR-0001: Pi-hole v6 Backup Application Architecture
- ADR-0002: Offline Static Assets (Remove CDN Dependencies)
- ADR-0003: Single Container Architecture
- ADR-0004: Manual Backup Trigger with UI Refresh on Completion
- ADR-0005: Testing Strategy and Workflow
- ADR-0006: GitHub Actions Docker Image Publishing
- ADR-0007: GitHub Actions Test Workflow Integration
- ADR-0008: One-Click Restore
- ADR-0009: Backup Failure Notifications
- ADR-0010: Replace Encrypted Database Fields with Environment Variables
- ADR-0011: Bug Review Findings and Remediation Plan
- ADR-0012: Dark Mode Toggle
- ADR-0013: Reliability and Security Fixes
- ADR-0014: Multi-Instance Pi-hole Support
- ADR-0017: Django 6.0 Upgrade
- ADR-0018: Gunicorn 26.0 Upgrade

### Accepted (2)
- ADR-0015: Simple Password Authentication
- ADR-0016: Prometheus Metrics Endpoint

### Proposed (1)
- ADR-0019: Fable Audit Findings and Remediation Plan (2026-07-02)

---

## Creating New ADRs

When creating a new ADR:
1. Use the next sequential number (e.g., `0011-*.md`)
2. Follow the established format with Status, Date, and Deciders
3. Update this index file with the new entry
