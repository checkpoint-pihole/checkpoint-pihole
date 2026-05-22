# ADR-0010: Replace Encrypted Database Fields with Environment Variables

**Status:** Implemented
**Date:** 2026-01-18

---

## Context

Checkpoint Pi-hole currently stores the Pi-hole password in the database using `django-encrypted-model-fields`. This approach:

1. **Requires an encryption key** - Users must set `FIELD_ENCRYPTION_KEY` (32 characters) in their environment
2. **Adds a dependency** - The `django-encrypted-model-fields` package must be maintained
3. **Creates migration complexity** - Changing the encryption key requires data migration
4. **Provides limited security benefit** - The encryption key is stored in the same environment as the database, so an attacker with filesystem access can decrypt the passwords anyway

The current implementation in `backup/models.py`:
```python
from encrypted_model_fields.fields import EncryptedCharField

class PiholeConfig(models.Model):
    password = EncryptedCharField(max_length=255)
```

This requires configuration in `.env`:
```
FIELD_ENCRYPTION_KEY=change-this-to-32-random-chars!!
```

---

## Decision

Replace the encrypted database field with environment variables for Pi-hole credentials. The application will read credentials directly from environment variables rather than storing them in the database.

### New Environment Variables

```bash
# Pi-hole connection settings
PIHOLE_URL=https://192.168.1.100
PIHOLE_PASSWORD=your-pihole-password
PIHOLE_VERIFY_SSL=false
```

### Rationale

1. **12-Factor App Compliance** - Credentials belong in the environment, not the database
2. **Simpler Configuration** - One less key to manage (`FIELD_ENCRYPTION_KEY` removed)
3. **Docker-Friendly** - Environment variables are the standard way to configure Docker containers
4. **Reduced Attack Surface** - No encrypted data to decrypt; credentials never touch the database
5. **Easier Secret Management** - Works naturally with Docker secrets, Kubernetes secrets, HashiCorp Vault, etc.

---

## Implementation Plan

### Phase 1: Add Environment Variable Support

#### 1.1 Update Settings (`config/settings.py`)

Add new settings for Pi-hole credentials:

```python
# Pi-hole credentials (from environment)
PIHOLE_URL = os.environ.get("PIHOLE_URL", "")
PIHOLE_PASSWORD = os.environ.get("PIHOLE_PASSWORD", "")
PIHOLE_VERIFY_SSL = os.environ.get("PIHOLE_VERIFY_SSL", "false").lower() == "true"
```

#### 1.2 Create Credential Service (`backup/services/credential_service.py`)

Abstract credential retrieval to support future multi-instance scenarios:

```python
from django.conf import settings


class CredentialService:
    """Service for retrieving Pi-hole credentials."""

    @staticmethod
    def get_credentials() -> dict:
        """
        Get Pi-hole credentials from environment.

        Returns:
            dict with keys: url, password, verify_ssl

        Raises:
            ValueError if required credentials are missing
        """
        url = settings.PIHOLE_URL
        password = settings.PIHOLE_PASSWORD

        if not url:
            raise ValueError("PIHOLE_URL environment variable is required")
        if not password:
            raise ValueError("PIHOLE_PASSWORD environment variable is required")

        return {
            "url": url,
            "password": password,
            "verify_ssl": settings.PIHOLE_VERIFY_SSL,
        }
```

#### 1.3 Update PiholeConfig Model (`backup/models.py`)

Remove the password field and make URL optional (fallback to env var):

```python
class PiholeConfig(models.Model):
    """Configuration for a Pi-hole instance."""

    name = models.CharField(max_length=100, default="Primary Pi-hole")

    # URL can be overridden per-config, but defaults to env var
    pihole_url = models.URLField(
        blank=True,
        help_text="Leave blank to use PIHOLE_URL environment variable"
    )

    # Remove: password = EncryptedCharField(max_length=255)
    # Remove: verify_ssl field (now in env var)

    # ... rest of fields unchanged
```

### Phase 2: Update Services

#### 2.1 Update BackupService (`backup/services/backup_service.py`)

```python
from backup.services.credential_service import CredentialService

class BackupService:
    def __init__(self, config: PiholeConfig):
        self.config = config
        self._credentials = None

    @property
    def credentials(self):
        if self._credentials is None:
            self._credentials = CredentialService.get_credentials()
        return self._credentials

    def _get_client(self):
        creds = self.credentials
        return PiholeV6Client(
            base_url=self.config.pihole_url or creds["url"],
            password=creds["password"],
            verify_ssl=creds["verify_ssl"],
        )
```

#### 2.2 Update RestoreService (`backup/services/restore_service.py`)

Apply same pattern as BackupService.

#### 2.3 Update Views (`backup/views.py`)

Update the settings form and test connection to use environment credentials:

```python
def test_connection(request):
    """Test Pi-hole connection using environment credentials."""
    try:
        creds = CredentialService.get_credentials()
        client = PiholeV6Client(
            base_url=creds["url"],
            password=creds["password"],
            verify_ssl=creds["verify_ssl"],
        )
        # ... test connection
    except ValueError as e:
        return JsonResponse({"success": False, "error": str(e)})
```

### Phase 3: Update UI

#### 3.1 Simplify Settings Form (`backup/forms.py`)

Remove password field from the form. Show environment variable status instead:

```python
class PiholeConfigForm(forms.ModelForm):
    class Meta:
        model = PiholeConfig
        fields = [
            "name",
            "backup_frequency",
            "backup_time",
            "backup_day",
            "max_backups",
            "max_age_days",
            "is_active",
        ]
        # Removed: pihole_url, password, verify_ssl
```

#### 3.2 Update Settings Template

Show current connection status based on environment variables:

```html
<div class="card mb-4">
    <div class="card-header">Pi-hole Connection</div>
    <div class="card-body">
        <p><strong>URL:</strong> {{ pihole_url|default:"Not configured" }}</p>
        <p><strong>Password:</strong> {% if pihole_password %}Configured{% else %}Not set{% endif %}</p>
        <p><strong>SSL Verification:</strong> {{ verify_ssl|yesno:"Enabled,Disabled" }}</p>
        <button id="test-connection" class="btn btn-secondary">Test Connection</button>
    </div>
</div>
```

### Phase 4: Migration and Cleanup

#### 4.1 Create Database Migration

```python
# backup/migrations/XXXX_remove_password_field.py
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("backup", "previous_migration"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="piholeconfig",
            name="password",
        ),
        migrations.RemoveField(
            model_name="piholeconfig",
            name="verify_ssl",
        ),
    ]
```

#### 4.2 Remove Dependencies

Update `pyproject.toml`:
```diff
- "django-encrypted-model-fields>=0.6.5",
```

#### 4.3 Update Environment Files

Update `.env.example`:
```diff
- # Encryption key for storing Pi-hole password (must be 32 characters)
- FIELD_ENCRYPTION_KEY=change-this-to-32-random-chars!!

+ # Pi-hole connection (required)
+ PIHOLE_URL=https://192.168.1.100
+ PIHOLE_PASSWORD=your-pihole-admin-password
+ PIHOLE_VERIFY_SSL=false
```

Update `docker-compose.yml`:
```diff
  environment:
    - SECRET_KEY=${SECRET_KEY}
-   - FIELD_ENCRYPTION_KEY=${FIELD_ENCRYPTION_KEY}
+   - PIHOLE_URL=${PIHOLE_URL}
+   - PIHOLE_PASSWORD=${PIHOLE_PASSWORD}
+   - PIHOLE_VERIFY_SSL=${PIHOLE_VERIFY_SSL:-false}
    - TIME_ZONE=${TIME_ZONE:-UTC}
```

#### 4.4 Remove Encryption Settings

Update `config/settings.py`:
```diff
- # Encrypted fields key (must be 32 characters)
- FIELD_ENCRYPTION_KEY = os.environ.get("FIELD_ENCRYPTION_KEY", "change-this-key-to-32-characters")
```

---

## Files to Modify

| File | Change |
|------|--------|
| `config/settings.py` | Add PIHOLE_* settings, remove FIELD_ENCRYPTION_KEY |
| `backup/models.py` | Remove password and verify_ssl fields |
| `backup/services/credential_service.py` | New file - credential retrieval |
| `backup/services/backup_service.py` | Use CredentialService |
| `backup/services/restore_service.py` | Use CredentialService |
| `backup/views.py` | Update to use env vars, simplify settings |
| `backup/forms.py` | Remove credential fields from form |
| `backup/templates/backup/settings.html` | Show env var status instead of input fields |
| `backup/migrations/XXXX_*.py` | Remove password field |
| `pyproject.toml` | Remove django-encrypted-model-fields |
| `.env.example` | Update with new variables |
| `docker-compose.yml` | Update environment section |
| `README.md` | Update configuration documentation |

---

## Migration Path for Existing Users

Users upgrading from the encrypted field version:

1. **Before upgrading**: Note their current Pi-hole URL and password from the settings page
2. **Update environment**: Add `PIHOLE_URL` and `PIHOLE_PASSWORD` to `.env`
3. **Remove old variable**: Remove `FIELD_ENCRYPTION_KEY` from `.env`
4. **Rebuild container**: `docker compose up --build`

The migration will automatically remove the old fields. No data loss occurs because the password was only used for API authentication, not stored data.

---

## Consequences

### Positive

- **Simpler setup** - Fewer environment variables to configure
- **No encryption key management** - Eliminates a common point of confusion
- **Standard Docker pattern** - Credentials via environment variables is industry standard
- **Better secret management** - Compatible with Docker secrets, Kubernetes secrets, etc.
- **Reduced dependencies** - One less package to maintain
- **Clearer security model** - No false sense of security from "encrypted" database fields

### Negative

- **Breaking change** - Existing users must update their configuration
- **Single instance only** - Environment variables support only one Pi-hole (but this matches current UI)
- **Visible in process list** - Environment variables can be seen via `ps` (mitigated by Docker isolation)

### Neutral

- **Multi-instance support** - If needed later, can add `PIHOLE_2_URL`, `PIHOLE_2_PASSWORD` pattern or re-introduce database storage with proper secret management

---

## Alternatives Considered

### 1. Keep Encrypted Fields

Continue using `django-encrypted-model-fields`.

**Rejected:** Adds complexity without meaningful security benefit. The encryption key is stored alongside the database.

### 2. Use Django's Built-in Signing

Use `django.core.signing` to encrypt passwords.

**Rejected:** Same fundamental issue - the key is in the environment alongside the data.

### 3. External Secret Manager

Integrate with HashiCorp Vault, AWS Secrets Manager, etc.

**Rejected:** Over-engineering for a self-hosted backup tool. Users who need this can mount secrets as environment variables.

### 4. Docker Secrets Only

Support only Docker secrets (`/run/secrets/pihole_password`).

**Rejected:** Too limiting. Environment variables are more universally supported and can be sourced from Docker secrets if needed.

---

## Future Considerations

### Multi-Instance Support

If multi-Pi-hole support is needed, consider:

```bash
# Option A: Numbered variables
PIHOLE_1_URL=https://192.168.1.100
PIHOLE_1_PASSWORD=password1
PIHOLE_2_URL=https://192.168.1.101
PIHOLE_2_PASSWORD=password2

# Option B: JSON configuration
PIHOLE_INSTANCES='[{"url":"https://192.168.1.100","password":"pw1"},...]'
```

This ADR focuses on single-instance to match current functionality. Multi-instance can be a separate ADR if needed.

---

## References

- [12-Factor App: Config](https://12factor.net/config)
- [Docker: Environment variables](https://docs.docker.com/compose/environment-variables/)
- [OWASP: Secrets Management](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html)
