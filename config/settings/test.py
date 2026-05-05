from __future__ import annotations

"""
Test settings — used by pytest and CI pipeline.

Strategy: set all required env vars via os.environ BEFORE base.py is
imported so django-environ's env() calls find non-empty values.
Then override specific settings for test-optimised behaviour.

What differs from base:
  - Real PostgreSQL (SQLite cannot run GiST exclusion constraint or RLS)
  - CELERY_TASK_ALWAYS_EAGER=True → tasks run synchronously, no broker needed
  - SMS_PROVIDER='mock' → Twilio is never called
  - Fast password hasher → bcrypt is slow; tests don't need real hashing
  - Stub Twilio/R2 values → satisfy env validation without real credentials
"""

import os

# ── Set required env vars before base.py runs ─────────────────────────────────
# django-environ reads from os.environ if the .env file key is absent.
# We set all secrets to deterministic stub values so CI needs no .env file.

_defaults: dict[str, str] = {
    "SECRET_KEY": "ci-test-secret-key-not-for-production-do-not-use",
    "JWT_SECRET_KEY": "ci-test-jwt-secret-not-for-production-do-not-use",
    "QR_TOKEN_SECRET": "ci-test-qr-secret-not-for-production-do-not-use",
    "DATABASE_URL": "postgresql://yali_user:yali_password@localhost/yali_test",
    "REDIS_URL": "redis://localhost:6379/1",  # DB 1 — separate from dev DB 0
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

# ── Import base settings (reads env vars above) ────────────────────────────────
from .base import *  # settings inheritance — star import is intentional (see pyproject.toml per-file-ignores)

# ── Celery — always eager in tests ────────────────────────────────────────────
# Tasks run synchronously in the calling thread.
# CELERY_TASK_EAGER_PROPAGATES surfaces exceptions immediately rather than
# swallowing them silently in the broker.
# NOTE: transaction.on_commit() callbacks do NOT fire in CELERY_TASK_ALWAYS_EAGER
# mode unless the test is marked @pytest.mark.django_db(transaction=True).
# For task dispatch tests, always use transaction=True.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# ── Password hashing — fast hasher for test speed ─────────────────────────────
# MD5PasswordHasher is cryptographically insecure but ~100x faster than bcrypt.
# Acceptable in tests — production uses Django's default PBKDF2.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# ── Email — capture in memory, never send ─────────────────────────────────────
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# ── Cache — use dummy cache to avoid Redis dependency in unit tests ────────────
# Integration tests that specifically test cache behaviour should override
# this fixture-level with a real Redis backend.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

# ── Security ───────────────────────────────────────────────────────────────────
DEBUG = False  # test against production-like security config
ALLOWED_HOSTS = ["*"]  # allow all in test runner

# ── Transaction wrapping — match production behavior ──────────────────────────
# WHY ATOMIC_REQUESTS = True in tests (mirrors production.py):
#   production.py sets ATOMIC_REQUESTS = True — every view is wrapped in a DB
#   transaction. Tests that don't set this run without transaction wrapping,
#   meaning a view that partially writes and raises an uncaught exception leaves
#   dirty rows in the test DB that don't exist in production.
#   Consequence: tests that pass in the test environment can silently fail in
#   production when the transaction rolls back what the test assumed was committed.
#   Source: audit §MEDIUM §ATOMIC_REQUESTS only in production.py;
#           Django docs §ATOMIC_REQUESTS — "same as production is recommended."
#   NOTE: CELERY_TASK_ALWAYS_EAGER is also set below. on_commit() callbacks
#   only fire in transaction=True tests — see conftest.py for details.
ATOMIC_REQUESTS = True

# ── DRF throttling — disabled in tests ────────────────────────────────────────
# WHY: OTPSendRateThrottle and OTPVerifyRateThrottle use the cache (LocMemCache)
# to track request counts. LocMemCache is in-process and shared across all tests
# in a single pytest run — throttle state from one test bleeds into the next,
# causing HTTP 429 in tests that expect HTTP 400/401/200.
#
# The correct MAANG pattern (also used by DRF's own test suite): set all throttle
# rates to a value so high they never trigger in test, or empty the rates dict.
# Tests that specifically test throttle behaviour override throttle_classes
# on the view using @override_settings or by passing throttle_classes=[].
#
# Source: Django REST Framework docs §Testing — "Throttle rates should be
#         disabled in tests unless you are testing throttle behaviour specifically."
REST_FRAMEWORK = {
    **REST_FRAMEWORK,  # star-import from base.py — intentional, see pyproject per-file-ignores
    "DEFAULT_THROTTLE_RATES": {},  # disable all throttling in tests
}
