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
