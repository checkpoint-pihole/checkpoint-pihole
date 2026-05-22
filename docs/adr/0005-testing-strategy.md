# ADR-0005: Testing Strategy and Workflow

**Status:** Implemented
**Date:** 2026-01-18
**Deciders:** Project Owner

---

## Context

The Checkpoint Pi-hole application currently has no automated tests. As the codebase grows, we need a testing strategy to:
- Ensure reliability of backup operations
- Prevent regressions when adding features
- Validate Pi-hole API integration behavior
- Enable confident refactoring
- Support future CI/CD pipelines

The application has distinct layers that require different testing approaches:
- **Services**: Business logic (`pihole_client.py`, `backup_service.py`, `retention_service.py`)
- **Views**: HTTP request/response handling
- **Models**: Data integrity and validation
- **Middleware**: Authentication flow
- **Scheduler**: Job execution and scheduling

---

## Decision

Implement a comprehensive testing strategy using pytest with Django integration.

### Technology Stack

| Component | Technology | Rationale |
|-----------|------------|-----------|
| Test Framework | pytest + pytest-django | Superior to unittest, better fixtures, cleaner syntax |
| Mocking | unittest.mock / pytest-mock | Standard library, no additional dependencies |
| HTTP Mocking | responses / requests-mock | Mock Pi-hole API calls without network |
| Coverage | pytest-cov | Track test coverage metrics |
| Factory | factory_boy | Generate test data for models |

### Testing Layers

#### 1. Unit Tests (Priority: High)

Test individual functions and classes in isolation.

**Services to test:**

| Service | Test Focus | Mocking Required |
|---------|------------|------------------|
| `PiholeV6Client` | Authentication flow, session management, error handling | HTTP responses |
| `BackupService` | Backup creation, file operations, checksum calculation | PiholeV6Client, filesystem |
| `RetentionService` | Count-based deletion, age-based deletion, edge cases | Database records, filesystem |

**Example test scenarios for `PiholeV6Client`:**
- Successful authentication returns session ID
- Invalid password returns appropriate error
- Session expiry triggers re-authentication
- SSL verification errors handled gracefully
- Connection timeout handling
- Teleporter download returns ZIP bytes

**Example test scenarios for `BackupService`:**
- Successful backup creates file and database record
- Backup failure records error in database
- File checksum is calculated correctly
- Manual vs scheduled backup flag is set correctly
- Backup deletion removes both file and record

**Example test scenarios for `RetentionService`:**
- Keeps exactly `max_backups` count
- Deletes backups older than `max_age_days`
- Handles empty backup list gracefully
- Preserves newest backups when enforcing limits
- Orphaned file cleanup works correctly

#### 2. Integration Tests (Priority: Medium)

Test interaction between components.

**Test scenarios:**
- Full backup workflow: API call → file save → database record
- Retention after backup: backup creation triggers retention check
- Settings change → scheduler reschedule
- Authentication middleware → protected view access

#### 3. View Tests (Priority: Medium)

Test HTTP endpoints and response handling.

| View | Test Focus |
|------|------------|
| `DashboardView` | Renders with/without config, displays backup list |
| `SettingsView` | Form validation, config save, redirect |
| `test_connection` | AJAX response format, error messages |
| `create_backup` | Triggers backup, returns JSON response |
| `download_backup` | File download, 404 for missing |
| `delete_backup` | Removes backup, handles missing |

#### 4. Model Tests (Priority: Low)

Test model validation and methods.

**Test scenarios:**
- `PiholeConfig` field validation (URL format, time fields)
- `BackupRecord` status choices
- Encrypted password field behavior
- Model relationships and cascading deletes

#### 5. Middleware Tests (Priority: Low)

Test authentication middleware.

**Test scenarios:**
- Unauthenticated request redirects to login
- Authenticated session accesses protected views
- Login endpoint is always accessible
- Static files bypass authentication

---

## Test Directory Structure

```
backup/
├── tests/
│   ├── __init__.py
│   ├── conftest.py              # Shared fixtures
│   ├── factories.py             # Model factories
│   │
│   ├── unit/
│   │   ├── __init__.py
│   │   ├── test_pihole_client.py
│   │   ├── test_backup_service.py
│   │   └── test_retention_service.py
│   │
│   ├── integration/
│   │   ├── __init__.py
│   │   ├── test_backup_workflow.py
│   │   └── test_scheduler_integration.py
│   │
│   └── views/
│       ├── __init__.py
│       ├── test_dashboard.py
│       ├── test_settings.py
│       └── test_backup_endpoints.py
```

---

## Fixtures and Factories

### Shared Fixtures (`conftest.py`)

```python
@pytest.fixture
def pihole_config(db):
    """Create a test PiholeConfig instance."""
    return PiholeConfigFactory()

@pytest.fixture
def backup_record(pihole_config):
    """Create a test BackupRecord instance."""
    return BackupRecordFactory(config=pihole_config)

@pytest.fixture
def mock_pihole_response():
    """Mock successful Pi-hole API responses."""
    # Returns context manager for responses library
```

### Model Factories (`factories.py`)

```python
class PiholeConfigFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PiholeConfig

    name = "Test Pi-hole"
    pihole_url = "https://192.168.1.100"
    password = "testpassword"
    verify_ssl = False
    backup_frequency = "daily"
    max_backups = 10
    max_age_days = 30
    is_active = True

class BackupRecordFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = BackupRecord

    config = factory.SubFactory(PiholeConfigFactory)
    filename = factory.Sequence(lambda n: f"backup_{n}.zip")
    file_size = 1024
    checksum = "abc123..."
    status = "success"
```

---

## Mocking Strategy

### Pi-hole API Mocking

Use `responses` library to mock HTTP calls:

```python
@responses.activate
def test_authenticate_success():
    responses.add(
        responses.POST,
        "https://192.168.1.100/api/auth",
        json={"session": {"sid": "test-session-id", "validity": 300}},
        status=200
    )

    client = PiholeV6Client("https://192.168.1.100", "password")
    success, message = client.authenticate()

    assert success is True
    assert client.session_id == "test-session-id"
```

### Filesystem Mocking

Use `tmp_path` fixture for file operations:

```python
def test_backup_creates_file(tmp_path, pihole_config, monkeypatch):
    monkeypatch.setattr(settings, 'BACKUP_DIR', str(tmp_path))

    service = BackupService(pihole_config)
    record, message = service.create_backup()

    assert (tmp_path / record.filename).exists()
```

---

## Coverage Requirements

| Category | Target Coverage |
|----------|-----------------|
| Services | 90%+ |
| Views | 80%+ |
| Models | 70%+ |
| Overall | 80%+ |

---

## CI/CD Integration (Future)

### GitHub Actions Workflow

```yaml
# .github/workflows/test.yml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install -r requirements-dev.txt
      - name: Run tests
        run: pytest --cov=backup --cov-report=xml
      - name: Upload coverage
        uses: codecov/codecov-action@v4
```

---

## Dependencies to Add

```
# requirements-dev.txt
pytest>=8.0
pytest-django>=4.7
pytest-cov>=4.1
pytest-mock>=3.12
responses>=0.24
factory-boy>=3.3
```

---

## Implementation Phases

### Phase 1: Foundation
- [ ] Add test dependencies to `requirements-dev.txt`
- [ ] Create `pytest.ini` or `pyproject.toml` configuration
- [ ] Set up `conftest.py` with basic fixtures
- [ ] Create model factories

### Phase 2: Service Unit Tests
- [ ] `test_pihole_client.py` - All API client scenarios
- [ ] `test_backup_service.py` - Backup creation/deletion
- [ ] `test_retention_service.py` - Retention policy enforcement

### Phase 3: View Tests
- [ ] `test_dashboard.py` - Dashboard rendering
- [ ] `test_settings.py` - Settings form handling
- [ ] `test_backup_endpoints.py` - AJAX endpoints

### Phase 4: Integration Tests
- [ ] `test_backup_workflow.py` - End-to-end backup flow
- [ ] `test_scheduler_integration.py` - Scheduler job execution

### Phase 5: CI/CD
- [ ] Create GitHub Actions workflow
- [ ] Configure coverage reporting
- [ ] Add test status badge to README

---

## Test Commands

```bash
# Run all tests
docker compose exec checkpoint-pihole pytest

# Run with coverage
docker compose exec checkpoint-pihole pytest --cov=backup --cov-report=term-missing

# Run specific test file
docker compose exec checkpoint-pihole pytest backup/tests/unit/test_pihole_client.py

# Run tests matching pattern
docker compose exec checkpoint-pihole pytest -k "test_authenticate"

# Run with verbose output
docker compose exec checkpoint-pihole pytest -v

# Run in parallel (requires pytest-xdist)
docker compose exec checkpoint-pihole pytest -n auto
```

---

## Consequences

### Positive
- Increased confidence in code changes
- Faster bug detection
- Documentation through tests
- Enables automated CI/CD
- Easier onboarding for contributors

### Negative
- Initial time investment to write tests
- Test maintenance overhead
- Need to mock external Pi-hole API
- Slight increase in container build time (dev dependencies)

### Mitigations
- Start with high-value service tests
- Use factories to reduce test data boilerplate
- Comprehensive mocking strategy for external calls
- Separate dev dependencies from production image

---

## References

- [pytest Documentation](https://docs.pytest.org/)
- [pytest-django Documentation](https://pytest-django.readthedocs.io/)
- [responses Library](https://github.com/getsentry/responses)
- [factory_boy Documentation](https://factoryboy.readthedocs.io/)
