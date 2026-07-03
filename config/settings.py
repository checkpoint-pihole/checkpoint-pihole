"""
Django settings for checkpoint-pihole project.
"""

import os
import secrets
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

from config.env import get_bool_env

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

DEBUG = get_bool_env("DEBUG", False)


def get_or_create_secret_key() -> str:
    """Get secret key from env or generate and persist one (atomic).

    Uses O_CREAT | O_EXCL for atomic file creation to prevent race
    conditions when multiple processes start simultaneously.
    """
    key = os.environ.get("SECRET_KEY")
    if key:
        return key

    key_file = BASE_DIR / "data" / ".secret_key"
    key_file.parent.mkdir(parents=True, exist_ok=True)

    # Use exclusive create to ensure atomicity
    try:
        # O_CREAT | O_EXCL fails if file exists - atomic check-and-create
        fd = os.open(key_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            key = secrets.token_urlsafe(50)
            os.write(fd, key.encode())
            return key
        finally:
            os.close(fd)
    except FileExistsError:
        # Another process created it first, read their key
        return key_file.read_text().strip()


SECRET_KEY = get_or_create_secret_key()

# Parse ALLOWED_HOSTS with sensible defaults
_allowed_hosts_env = os.environ.get("ALLOWED_HOSTS", "")
if _allowed_hosts_env:
    ALLOWED_HOSTS = [h.strip() for h in _allowed_hosts_env.split(",") if h.strip()]
elif DEBUG:
    # Allow all hosts only in debug mode
    ALLOWED_HOSTS = ["*"]
else:
    # Default to localhost only in production
    ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_apscheduler",
    "backup",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "backup.middleware.simple_auth.SimpleAuthMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "backup.context_processors.app_info",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "data" / "db.sqlite3",
    }
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
        "LOCATION": BASE_DIR / "data" / "cache",
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"

TIME_ZONE = os.environ.get("TIME_ZONE", "UTC")

USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Backup storage path
BACKUP_DIR = BASE_DIR / "backups"

# Simple auth settings
REQUIRE_AUTH = get_bool_env("REQUIRE_AUTH", False)
APP_PASSWORD_HASH = ""
if REQUIRE_AUTH:
    _APP_PASSWORD_RAW = os.environ.get("APP_PASSWORD", "")
    if not _APP_PASSWORD_RAW:
        # Fail closed: an enabled-but-passwordless auth config would otherwise
        # be silently skipped by SimpleAuthMiddleware, serving the whole UI
        # unauthenticated while the operator believes it is protected.
        raise ImproperlyConfigured(
            "REQUIRE_AUTH is enabled but APP_PASSWORD is empty. "
            "Set APP_PASSWORD to a non-empty value, or unset REQUIRE_AUTH."
        )

    from django.contrib.auth.hashers import make_password

    APP_PASSWORD_HASH = make_password(_APP_PASSWORD_RAW)
    del _APP_PASSWORD_RAW
    os.environ.pop("APP_PASSWORD", None)

# Trust X-Forwarded-For for client IP (rate limiting) only when behind a proxy.
# Off by default so a directly-exposed container cannot be spoofed to evade limits.
TRUST_PROXY = get_bool_env("TRUST_PROXY", False)

# Sessions expire when browser closes
SESSION_EXPIRE_AT_BROWSER_CLOSE = True

# APScheduler settings
APSCHEDULER_DATETIME_FORMAT = "N j, Y, f:s a"
APSCHEDULER_RUN_NOW_TIMEOUT = 25

# Notification settings (configured via environment variables)
# See .env.example for available options
# NOTIFY_ON_FAILURE: Enable notifications for backup/restore failures (default: true)
# NOTIFY_ON_SUCCESS: Enable notifications for backup/restore success (default: false)
# NOTIFY_ON_CONNECTION_LOST: Enable notifications when Pi-hole is unreachable (default: true)
# Provider-specific settings: NOTIFY_DISCORD_*, NOTIFY_SLACK_*, NOTIFY_TELEGRAM_*,
#                             NOTIFY_PUSHBULLET_*, NOTIFY_HOMEASSISTANT_*

# Logging
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "backup": {
            "handlers": ["console"],
            "level": "DEBUG",
            "propagate": False,
        },
        "apscheduler": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
