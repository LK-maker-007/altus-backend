from __future__ import annotations

import environ  # type: ignore[import-untyped]  # django-environ ships no py.typed or stubs

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
