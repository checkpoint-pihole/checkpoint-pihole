# ADR-0012: Dark Mode Toggle

**Status:** Implemented
**Date:** 2026-01-19

---

## Context

Checkpoint Pi-hole currently uses a light-only theme with Bootstrap 5.3.2. Users may prefer dark mode for:
- Reduced eye strain in low-light environments
- Personal preference
- Consistency with system-wide dark mode settings
- Server rooms and monitoring setups where dark UIs are common

### Current State

- Bootstrap 5.3.2 includes native dark mode support via `data-bs-theme` attribute
- No theme switching mechanism exists
- All styling relies on Bootstrap defaults (light theme)
- Bootstrap Icons already includes sun/moon icons

### Constraints

- Single-container deployment (no backend changes preferred)
- Bootstrap 5 + vanilla JavaScript frontend
- Must work on login page (unauthenticated users)
- No flash of wrong theme on page load

---

## Decision

**Implement client-side dark mode toggle using Bootstrap's native `data-bs-theme` with localStorage persistence**

---

## Options Considered

| Option | Complexity | Pros | Cons |
|--------|------------|------|------|
| **1. localStorage + Bootstrap data-bs-theme** | Low | No backend changes, instant, works everywhere | Preference not synced across devices |
| 2. Django session storage | Medium | Server-side persistence | Requires backend changes, can't prevent flash without JS |
| 3. Database user preferences | High | Multi-device sync | No user model exists, requires migrations, overkill |
| 4. Cookie storage | Low | Works without localStorage | Sent with every request, no benefit over localStorage |

**Recommendation: Option 1** - Bootstrap 5.3.2's native dark mode makes this trivial. localStorage provides instant persistence without backend complexity.

---

## Implementation Plan

### Phase 1: Create Theme Manager Module

**File:** `backup/static/backup/js/theme.js` (new)

```javascript
const ThemeManager = {
    STORAGE_KEY: 'checkpoint-pihole-theme',

    getPreference() {
        const stored = localStorage.getItem(this.STORAGE_KEY);
        if (stored) return stored;
        return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    },

    apply(theme) {
        document.documentElement.setAttribute('data-bs-theme', theme);
        this.updateIcon(theme);
    },

    save(theme) {
        localStorage.setItem(this.STORAGE_KEY, theme);
    },

    toggle() {
        const current = document.documentElement.getAttribute('data-bs-theme') || 'light';
        const next = current === 'dark' ? 'light' : 'dark';
        this.apply(next);
        this.save(next);
    },

    updateIcon(theme) {
        const icon = document.querySelector('#themeToggle i');
        if (icon) {
            icon.className = theme === 'dark' ? 'bi bi-sun-fill' : 'bi bi-moon-fill';
        }
    },

    init() {
        this.updateIcon(this.getPreference());
        window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
            if (!localStorage.getItem(this.STORAGE_KEY)) {
                this.apply(e.matches ? 'dark' : 'light');
            }
        });
    }
};

document.addEventListener('DOMContentLoaded', () => ThemeManager.init());
```

### Phase 2: Update Base Template

**File:** `backup/templates/backup/base.html`

**a) Add flash prevention script in `<head>` (before CSS, line 7):**

```html
<script>
(function() {
    var theme = localStorage.getItem('checkpoint-pihole-theme');
    if (!theme) {
        theme = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }
    document.documentElement.setAttribute('data-bs-theme', theme);
})();
</script>
```

**b) Add theme toggle button in navbar (line 51, before logout):**

```html
<ul class="navbar-nav">
    <li class="nav-item">
        <button class="nav-link" id="themeToggle" onclick="ThemeManager.toggle()"
                aria-label="Toggle dark mode" title="Toggle dark mode">
            <i class="bi bi-moon-fill"></i>
        </button>
    </li>
    {% if request.session.authenticated %}
    <li class="nav-item">
        <a class="nav-link" href="{% url 'logout' %}">
            <i class="bi bi-box-arrow-right"></i> Logout
        </a>
    </li>
    {% endif %}
</ul>
```

**c) Add button CSS in existing `<style>` block:**

```css
#themeToggle {
    background: transparent;
    border: none;
    cursor: pointer;
}
#themeToggle:hover {
    opacity: 0.8;
}
```

**d) Load theme.js after Bootstrap bundle:**

```html
<script src="{% static 'backup/js/bootstrap.bundle.min.js' %}"></script>
<script src="{% static 'backup/js/theme.js' %}"></script>
```

---

## Files to Modify

| File | Changes |
|------|---------|
| `backup/static/backup/js/theme.js` | **New file** - Theme manager module |
| `backup/templates/backup/base.html` | Flash prevention script, toggle button, CSS, theme.js include |
| `docs/adr/0000-index.md` | Add ADR-0012 entry |

---

## Consequences

### Positive

- No backend changes required
- Works on login page (unauthenticated)
- Respects system preference by default
- No flash of wrong theme on page load
- Preference persists across sessions
- Bootstrap handles all component styling automatically

### Negative

- Preference not synced across devices/browsers (localStorage is local)
- Logo may need adjustment for dark background visibility

---

## Verification

1. **Persistence test** - Toggle theme, refresh page → should stay on selected theme
2. **Navigation test** - Toggle theme, navigate pages → should persist
3. **System preference test** - Clear localStorage, change OS dark mode → should follow
4. **Flash test** - Hard refresh (Ctrl+Shift+R) → no flash of wrong theme
5. **Login page test** - Theme should work on login page
6. **Mobile test** - Toggle should work in collapsed navbar menu
7. **Accessibility test** - Button has aria-label, keyboard accessible
