# ADR-0002: Offline Static Assets (Remove CDN Dependencies)

**Status:** Implemented
**Date:** 2026-01-18
**Deciders:** Project Owner

---

## Context

The Checkpoint Pi-hole application currently loads all frontend assets from a CDN (jsDelivr):

| Asset | CDN URL | Version |
|-------|---------|---------|
| Bootstrap CSS | cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css | 5.3.2 |
| Bootstrap Icons | cdn.jsdelivr.net/npm/bootstrap-icons@1.11.1/font/bootstrap-icons.css | 1.11.1 |
| Bootstrap JS | cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js | 5.3.2 |

This creates several problems for self-hosted environments:

1. **Air-gapped networks**: Many Pi-hole users run on isolated networks without internet access
2. **Network dependency**: UI fails to render properly if CDN is unreachable
3. **Privacy concerns**: External requests to CDN reveal user activity
4. **Latency**: CDN requests add loading time, especially on slow connections
5. **Version control**: CDN assets could theoretically change (though versioned URLs mitigate this)

Since Checkpoint Pi-hole is designed as a self-hosted, Dockerized application for local network use, it should work completely offline.

---

## Decision

Bundle all static assets locally within the Docker image. Django's `collectstatic` will manage these files.

### Implementation Approach

#### 1. Directory Structure

Create a `static/` directory in the `backup` app:

```
backup/
├── static/
│   └── backup/
│       ├── css/
│       │   ├── bootstrap.min.css
│       │   └── bootstrap-icons.css
│       ├── js/
│       │   └── bootstrap.bundle.min.js
│       └── fonts/
│           └── bootstrap-icons.woff2
│           └── bootstrap-icons.woff
```

#### 2. Asset Sources

Download assets from official sources:

| Asset | Download URL |
|-------|-------------|
| Bootstrap 5.3.2 | https://github.com/twbs/bootstrap/releases/download/v5.3.2/bootstrap-5.3.2-dist.zip |
| Bootstrap Icons 1.11.1 | https://github.com/twbs/icons/releases/download/v1.11.1/bootstrap-icons-1.11.1.zip |

**Important**: Bootstrap Icons CSS references font files with relative paths. The fonts directory must maintain the correct relative path from the CSS file.

#### 3. Template Changes

Update `backup/templates/backup/base.html`:

**Before (CDN):**
```html
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
<link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.1/font/bootstrap-icons.css" rel="stylesheet">
...
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
```

**After (Local):**
```html
{% load static %}
<link href="{% static 'backup/css/bootstrap.min.css' %}" rel="stylesheet">
<link href="{% static 'backup/css/bootstrap-icons.css' %}" rel="stylesheet">
...
<script src="{% static 'backup/js/bootstrap.bundle.min.js' %}"></script>
```

#### 4. Django Settings

Current settings are already sufficient:

```python
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
```

`django.contrib.staticfiles` is already in `INSTALLED_APPS`.

#### 5. Dockerfile Changes

The Dockerfile already runs `collectstatic`:

```dockerfile
RUN python manage.py collectstatic --noinput
```

This will collect the new local assets into `staticfiles/` during image build.

#### 6. Whitenoise (Optional Enhancement)

Consider adding `whitenoise` for efficient static file serving in production:

```python
# settings.py
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',  # Add after SecurityMiddleware
    ...
]

STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'
```

**Benefits:**
- Compression and caching headers
- No need for separate static file server
- Works seamlessly with Gunicorn

---

## Alternatives Considered

### 1. Keep CDN with Fallback

```html
<link href="https://cdn.jsdelivr.net/..." rel="stylesheet"
      onerror="this.href='{% static 'backup/css/bootstrap.min.css' %}'">
```

**Rejected because:**
- Adds complexity
- Still makes external requests when online (privacy concern)
- Fallback mechanism is unreliable for CSS

### 2. NPM/Node Build Process

Use npm to manage Bootstrap and build assets.

**Rejected because:**
- Adds Node.js dependency to build
- Increases Docker image size
- Overkill for a simple Django app
- Complicates development workflow

### 3. Vendor Directory Outside Static

Store assets in a separate `vendor/` directory.

**Rejected because:**
- Doesn't integrate with Django's static file handling
- Would require custom URL routing
- Less maintainable

---

## Implementation Steps

### Step 1: Create Directory Structure

```bash
mkdir -p backup/static/backup/{css,js,fonts}
```

### Step 2: Download Bootstrap 5.3.2

```bash
# Download and extract
curl -L -o /tmp/bootstrap.zip \
  https://github.com/twbs/bootstrap/releases/download/v5.3.2/bootstrap-5.3.2-dist.zip
unzip /tmp/bootstrap.zip -d /tmp/

# Copy required files
cp /tmp/bootstrap-5.3.2-dist/css/bootstrap.min.css backup/static/backup/css/
cp /tmp/bootstrap-5.3.2-dist/js/bootstrap.bundle.min.js backup/static/backup/js/

# Cleanup
rm -rf /tmp/bootstrap.zip /tmp/bootstrap-5.3.2-dist
```

### Step 3: Download Bootstrap Icons 1.11.1

```bash
# Download and extract
curl -L -o /tmp/bootstrap-icons.zip \
  https://github.com/twbs/icons/releases/download/v1.11.1/bootstrap-icons-1.11.1.zip
unzip /tmp/bootstrap-icons.zip -d /tmp/

# Copy required files
cp /tmp/bootstrap-icons-1.11.1/font/bootstrap-icons.css backup/static/backup/css/
cp /tmp/bootstrap-icons-1.11.1/font/fonts/* backup/static/backup/fonts/

# Cleanup
rm -rf /tmp/bootstrap-icons.zip /tmp/bootstrap-icons-1.11.1
```

### Step 4: Fix Font Paths in CSS

The Bootstrap Icons CSS references fonts with `./fonts/` path. Update to work with Django static:

```css
/* In bootstrap-icons.css, change: */
src: url("./fonts/bootstrap-icons.woff2") ...

/* To: */
src: url("../fonts/bootstrap-icons.woff2") ...
```

### Step 5: Update base.html

Replace CDN links with Django static template tags.

### Step 6: Optional - Add Whitenoise

```bash
# Add to requirements.txt
whitenoise>=6.6
```

Update `settings.py` as described above.

### Step 7: Rebuild Docker Image

```bash
docker compose build --no-cache
docker compose up -d
```

---

## File Size Impact

| Asset | Size |
|-------|------|
| bootstrap.min.css | ~227 KB |
| bootstrap.bundle.min.js | ~80 KB |
| bootstrap-icons.css | ~90 KB |
| bootstrap-icons.woff2 | ~176 KB |
| bootstrap-icons.woff | ~256 KB |
| **Total** | **~829 KB** |

Docker image size increase: < 1 MB (minimal impact).

---

## Verification Checklist

- [ ] Static files directory structure created
- [ ] Bootstrap CSS/JS downloaded and placed correctly
- [ ] Bootstrap Icons CSS and fonts downloaded
- [ ] Font paths in bootstrap-icons.css updated
- [ ] `{% load static %}` added to base.html
- [ ] CDN links replaced with `{% static %}` tags
- [ ] `docker compose build` completes without errors
- [ ] UI renders correctly with no network requests to external CDNs
- [ ] Icons display correctly (font files loading)
- [ ] All pages work in browser with network disconnected
- [ ] Whitenoise serving files with proper cache headers (if implemented)

---

## Security Considerations

- **Integrity**: Downloaded files should be verified against known checksums
- **Updates**: Document process for updating Bootstrap versions
- **Source**: Always download from official GitHub releases, not third-party mirrors

---

## Future Considerations

- **Version updates**: Create a script or Makefile target to automate downloading new versions
- **CSS customization**: If custom Bootstrap build is needed, consider switching to SCSS compilation
- **Additional assets**: Any future frontend dependencies should follow the same local-first approach

---

## References

- [Bootstrap 5.3 Download](https://getbootstrap.com/docs/5.3/getting-started/download/)
- [Bootstrap Icons](https://icons.getbootstrap.com/)
- [Django Static Files](https://docs.djangoproject.com/en/5.0/howto/static-files/)
- [Whitenoise Documentation](http://whitenoise.evans.io/en/stable/)
