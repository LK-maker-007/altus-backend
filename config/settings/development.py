from __future__ import annotations

import environ  # django-environ 0.11.2 ships py.typed — no ignore needed

from .base import *  # settings inheritance - star import intentional (see pyproject.toml per-file-ignores)

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")

DEBUG = True
SECRET_KEY = env("SECRET_KEY", default="dev-insecure-secret-change-before-production")
JWT_SECRET_KEY = env("JWT_SECRET_KEY", default="dev-insecure-jwt-secret")
QR_TOKEN_SECRET = env("QR_TOKEN_SECRET", default="dev-insecure-qr-secret")

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "0.0.0.0"]

# ── Email (console in dev) ─────────────────────────────────────────────────────
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# ── CORS (all origins in dev) ─────────────────────────────────────────────────
CORS_ALLOW_ALL_ORIGINS = True

# ── Logging ────────────────────────────────────────────────────────────────────
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "DEBUG"},
}

# ── Migration linter (development only) ────────────────────────────────────────
# WHY MIGRATION_LINTER_OVERRIDE_MAKEMIGRATIONS:
#   Hooks the linter into `manage.py makemigrations` so dangerous migrations are
#   caught at creation time locally — before commit, before CI. Shift-left safety.
#   CI runs lintmigrations separately (config/settings/test.py). This is the local
#   equivalent that fires automatically on every makemigrations invocation.
#
#   Source: github.com/3YOURMIND/django-migration-linter — makemigrations integration
#   Verified: django-migration-linter 6.0.0 docs (released 2026-01-04, Django 6.0)
#
# WHY not in base.py:
#   django_migration_linter must NOT be in production INSTALLED_APPS.
INSTALLED_APPS += ["django_migration_linter"]
MIGRATION_LINTER_OVERRIDE_MAKEMIGRATIONS = True
MIGRATION_LINTER_OPTIONS = {
    "exclude_apps": ["django_celery_beat"],
    "ignore_name_contains": "_initial",
    "ignore_name": [
        "0004_add_event_date_venue",
        "0005_add_booking_idempotency_key",
        "0002_fix_visitor_otp_unique_constraint",
    ],
}
