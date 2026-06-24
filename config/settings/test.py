from __future__ import annotations

import os

_defaults: dict[str, str] = {
    "SECRET_KEY": "ci-test-secret-key-not-for-production-do-not-use",
    "JWT_SECRET_KEY": "ci-test-jwt-secret-not-for-production-do-not-use",
    "QR_TOKEN_SECRET": "ci-test-qr-secret-not-for-production-do-not-use",
    "DATABASE_URL": "postgresql://yali_user:yali_password@localhost/yali_test",
    "REDIS_URL": "redis://localhost:6379/1",
    "SMS_PROVIDER": "mock",
    "TWILIO_ACCOUNT_SID": "ACci",
    "TWILIO_AUTH_TOKEN": "ci",
    "TWILIO_VERIFY_SERVICE_SID": "VAci",
    "TWILIO_PHONE_NUMBER": "+10000000000",
    "R2_ACCOUNT_ID": "ci",
    "R2_ACCESS_KEY_ID": "ci",
    "R2_SECRET_ACCESS_KEY": "ci",
    "R2_ENDPOINT_URL": "https://ci.r2.cloudflarestorage.com",
    "R2_PUBLIC_URL": "https://media.ci.yali.app",
}
for _key, _val in _defaults.items():
    os.environ.setdefault(_key, _val)

from .base import *

INSTALLED_APPS += ["django_migration_linter"]

MIGRATION_LINTER_OPTIONS = {
    "exclude_apps": ["django_celery_beat"],
    "ignore_name_contains": "_initial",
    "ignore_name": [
        "0004_add_event_date_venue",
        "0005_add_booking_idempotency_key",
        "0002_fix_visitor_otp_unique_constraint",
    ],
}

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

DEBUG = False
ALLOWED_HOSTS = ["*"]

ATOMIC_REQUESTS = True

REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    "DEFAULT_THROTTLE_RATES": {},
}
