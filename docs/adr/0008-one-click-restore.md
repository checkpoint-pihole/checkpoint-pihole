# ADR-0008: One-Click Restore

**Status:** Implemented
**Date:** 2026-01-18

---

## Context

Checkpoint Pi-hole currently supports creating and downloading backups via the Pi-hole v6 Teleporter API, but users cannot restore backups directly through the application. To restore, users must:

1. Download the backup ZIP from the app
2. Log into Pi-hole admin UI
3. Navigate to Settings > Teleporter
4. Upload the ZIP file manually

This friction reduces the value of having automated backups and makes disaster recovery slower than necessary.

---

## Decision

Implement one-click restore functionality that allows users to restore any backup directly to their Pi-hole instance via the Teleporter API.

### Pi-hole v6 Teleporter API

The restore endpoint mirrors the backup endpoint:

- **Endpoint:** `POST /api/teleporter`
- **Authentication:** `X-FTL-SID` header (same as backup)
- **Content-Type:** `multipart/form-data`
- **Body:** ZIP file as `file` field

The API accepts the same ZIP format that it exports, making round-trip backup/restore straightforward.

---

## Implementation Plan

### 1. Extend `PiholeV6Client` (`backup/services/pihole_client.py`)

Add a new method to upload backups:

```python
def upload_teleporter_backup(self, backup_data: bytes) -> dict:
    """
    Upload a Teleporter backup to Pi-hole.

    Args:
        backup_data: ZIP file content as bytes

    Returns:
        API response dict

    Raises:
        Exception on failure
    """
    self._ensure_authenticated()

    files = {"file": ("backup.zip", backup_data, "application/zip")}
    response = self._session.post(
        self._get_url("/api/teleporter"),
        headers=self._get_headers(),
        files=files,
        verify=self.verify_ssl,
        timeout=120,
    )
    response.raise_for_status()
    return response.json()
```

### 2. Add Restore Service (`backup/services/restore_service.py`)

Create a new service to handle restore logic:

```python
class RestoreService:
    """Service for restoring backups to Pi-hole."""

    def __init__(self, config: PiholeConfig):
        self.config = config

    def restore_backup(self, record: BackupRecord) -> dict:
        """
        Restore a backup to Pi-hole.

        Args:
            record: BackupRecord to restore

        Returns:
            API response from Pi-hole

        Raises:
            FileNotFoundError: Backup file missing
            Exception: API errors
        """
        # Verify file exists
        filepath = Path(record.file_path)
        if not filepath.exists():
            raise FileNotFoundError(f"Backup file not found: {record.filename}")

        # Verify checksum before restore
        if record.checksum:
            actual_checksum = self._calculate_checksum(filepath)
            if actual_checksum != record.checksum:
                raise ValueError("Backup file corrupted (checksum mismatch)")

        # Upload to Pi-hole
        client = PiholeV6Client(
            base_url=self.config.pihole_url,
            password=self.config.password,
            verify_ssl=self.config.verify_ssl,
        )

        with open(filepath, "rb") as f:
            backup_data = f.read()

        return client.upload_teleporter_backup(backup_data)
```

### 3. Add View Endpoint (`backup/views.py`)

Add AJAX endpoint for restore:

```python
@require_POST
def restore_backup(request, backup_id):
    """AJAX endpoint to restore a backup to Pi-hole."""
    record = get_object_or_404(BackupRecord, id=backup_id)
    config = record.config

    try:
        service = RestoreService(config)
        result = service.restore_backup(record)
        return JsonResponse({
            "success": True,
            "message": "Backup restored successfully",
        })
    except FileNotFoundError as e:
        return JsonResponse({"success": False, "error": str(e)})
    except ValueError as e:
        return JsonResponse({"success": False, "error": str(e)})
    except Exception as e:
        logger.exception("Restore error")
        return JsonResponse({"success": False, "error": str(e)})
```

### 4. Add URL Route (`backup/urls.py`)

```python
path("api/restore/<int:backup_id>/", views.restore_backup, name="restore_backup"),
```

### 5. Update Dashboard UI (`backup/templates/backup/dashboard.html`)

Add restore button to each backup row with confirmation dialog:

```html
<button class="btn btn-sm btn-warning restore-btn"
        data-backup-id="{{ backup.id }}"
        data-backup-name="{{ backup.filename }}"
        title="Restore this backup">
    <i class="bi bi-arrow-counterclockwise"></i> Restore
</button>
```

JavaScript handler with confirmation:

```javascript
document.querySelectorAll('.restore-btn').forEach(btn => {
    btn.addEventListener('click', async function() {
        const backupId = this.dataset.backupId;
        const backupName = this.dataset.backupName;

        if (!confirm(`Restore "${backupName}" to Pi-hole?\n\nThis will overwrite your current Pi-hole configuration.`)) {
            return;
        }

        // Show loading state
        this.disabled = true;
        this.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Restoring...';

        try {
            const response = await fetch(`/api/restore/${backupId}/`, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': csrfToken,
                },
            });
            const data = await response.json();

            if (data.success) {
                showAlert('success', 'Backup restored successfully!');
            } else {
                showAlert('danger', `Restore failed: ${data.error}`);
            }
        } catch (error) {
            showAlert('danger', `Restore failed: ${error.message}`);
        } finally {
            this.disabled = false;
            this.innerHTML = '<i class="bi bi-arrow-counterclockwise"></i> Restore';
        }
    });
});
```

---

## Files to Modify

| File | Change |
|------|--------|
| `backup/services/pihole_client.py` | Add `upload_teleporter_backup()` method |
| `backup/services/restore_service.py` | New file - restore orchestration |
| `backup/views.py` | Add `restore_backup()` view |
| `backup/urls.py` | Add restore route |
| `backup/templates/backup/dashboard.html` | Add restore button + JS |

---

## UX Considerations

### Confirmation Dialog
Restore is a destructive operation that overwrites the current Pi-hole config. The confirmation dialog should:
- Clearly state what will happen
- Show the backup filename and date
- Require explicit user action (not just Enter key)

### Loading State
Restore may take several seconds. Show:
- Spinner on the button
- Disable all restore buttons during operation
- Toast notification on completion

### Error Handling
Common failure scenarios:
- Backup file deleted from disk → Clear error message
- Checksum mismatch → "Backup corrupted" warning
- Pi-hole unreachable → Connection error with retry suggestion
- Invalid credentials → Re-authentication prompt

---

## Future Enhancements

These are explicitly out of scope for this ADR but noted for future consideration:

1. **Selective restore** - Choose which components to restore (blocklists, DNS, DHCP, etc.)
2. **Pre-restore backup** - Automatically create a backup before restoring
3. **Restore history** - Track when backups were restored
4. **Dry run** - Preview what will change before restoring

---

## Consequences

### Positive
- Users can restore backups without leaving the app
- Faster disaster recovery
- Completes the backup/restore workflow

### Negative
- Adds risk of accidental config overwrites (mitigated by confirmation)
- Restore errors could leave Pi-hole in inconsistent state (Pi-hole handles this atomically)

### Risks
- **Pi-hole API changes:** The Teleporter API is stable but could change. We should handle API errors gracefully.
- **Large backups:** Very large configs might timeout. The 120s timeout should be sufficient for typical configs.

---

## Alternatives Considered

### 1. Link to Pi-hole Admin UI
Just provide a direct link to Pi-hole's Teleporter page with instructions.

**Rejected:** Too much friction, doesn't add value beyond downloading the file.

### 2. Restore via SSH/File Copy
Copy the backup directly to Pi-hole's data directory.

**Rejected:** Requires SSH access, more complex setup, bypasses Pi-hole's import validation.

### 3. Full Config Sync (Not Just Restore)
Build a two-way sync between backup and live Pi-hole.

**Rejected:** Over-engineering for the initial feature. Can be added later.
