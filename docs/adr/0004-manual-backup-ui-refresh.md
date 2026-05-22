# ADR-0004: Manual Backup Trigger with UI Refresh on Completion

**Status:** Implemented
**Date:** 2026-01-18

---

## Context

Checkpoint Pi-hole allows users to trigger manual backups via a "Backup Now" button. The current implementation:

1. `POST /api/backup/` calls `BackupService.create_backup()` synchronously
2. Returns JSON with `success`, `backup_id`, `filename`
3. Frontend shows toast, then does **full page reload after 1-second delay**

### Problems

- **Fixed 1s delay is arbitrary** - doesn't correlate with actual completion
- **Full page reload** - loses scroll position, feels jarring
- **No progress indication** - just a spinner with "Creating..."
- **Toast may be missed** - if reload happens before user reads it

### Constraints

- Single-container deployment (Gunicorn + APScheduler)
- No task queue (Celery/RQ) infrastructure
- Bootstrap 5 + vanilla JavaScript frontend
- Pi-hole exports are typically fast (1-5 seconds, 10-500KB)

---

## Decision

**Implement Enhanced Synchronous Flow with Partial DOM Update**

Keep the synchronous backup call (it works for typical use cases) but replace full page reload with targeted DOM updates.

---

## Options Considered

| Option | Complexity | Pros | Cons |
|--------|------------|------|------|
| **1. Enhanced Sync + DOM Update** | Low | Minimal changes, instant feedback, no new deps | No true progress, HTML duplication |
| 2. Background Job + Polling | Medium-High | True async, progress states | More code, threading concerns, overkill |
| 3. Server-Sent Events | High | Real-time progress | Blocks worker, complex for 5s operation |
| 4. WebSocket | Very High | Full real-time | Requires Channels, major arch change |

**Recommendation: Option 1** - Best balance of effort vs. UX improvement for operations that complete in 1-5 seconds.

---

## Implementation Plan

### Phase 1: Backend - Expand JSON Response

**File:** `backup/views.py` (lines 77-94)

```python
return JsonResponse({
    'success': True,
    'backup': {
        'id': record.id,
        'filename': record.filename,
        'file_size': record.file_size,
        'status': record.status,
        'is_manual': record.is_manual,
        'created_at': record.created_at.isoformat(),
        'created_at_display': record.created_at.strftime('%b %d, %Y %H:%M'),
    }
})
```

### Phase 2: Frontend - DOM Update Instead of Reload

**File:** `backup/templates/backup/dashboard.html`

1. **Update `createBackup()`** - Add abort controller with 60s timeout, call `addBackupToTable()` on success
2. **Add `addBackupToTable(backup)`** - Insert new row at top of table, update backup count badge
3. **Add `updateLastBackupCard(timestamp)`** - Update the "Last Backup" status card
4. **Add `formatFileSize(bytes)`** - Utility for file size display
5. **Handle edge case** - If no table exists yet (first backup), fall back to page reload

### Phase 3: Polish

- Add subtle CSS transition when new row appears
- Test error scenarios (Pi-hole offline, auth failure, timeout)
- Verify mobile responsiveness

---

## Files to Modify

| File | Changes |
|------|---------|
| `backup/views.py` | Expand `create_backup` JSON response with full backup record |
| `backup/templates/backup/dashboard.html` | Update JS: DOM insertion instead of reload |

---

## Consequences

### Positive
- No jarring page reload
- Instant feedback when backup completes
- Consistent with existing `deleteBackup()` pattern (already does DOM manipulation)
- No new dependencies

### Negative
- Table row HTML duplicated in JavaScript (mitigation: could use server-rendered partial in future)
- No detailed progress (just spinner) - acceptable for 1-5s operations

---

## Verification

1. Click "Backup Now" - new row appears at top of table without page reload
2. Toast shows backup filename
3. "Last Backup" card updates
4. Backup count badge increments
5. Test with Pi-hole offline - error toast appears, no row added
6. Test timeout - warning toast after 60s
