from __future__ import annotations

import importlib.util

import environ

from config.logging_config import build_logging

from .base import *

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")

DEBUG = True
SECRET_KEY = env("SECRET_KEY", default="dev-insecure-secret-change-before-production")
JWT_SECRET_KEY = env("JWT_SECRET_KEY", default="dev-insecure-jwt-secret")
QR_TOKEN_SECRET = env("QR_TOKEN_SECRET", default="dev-insecure-qr-secret")

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "0.0.0.0"]

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

CORS_ALLOW_ALL_ORIGINS = True

LOGGING = build_logging(json_logs=False, level="DEBUG")

# Only wire the migration linter when it's actually installed (it's a dev tool,
# absent from the production-deps Docker image that also runs these settings).
if importlib.util.find_spec("django_migration_linter"):
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
