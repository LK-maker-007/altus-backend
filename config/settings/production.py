from __future__ import annotations

import sentry_sdk
from django.core.exceptions import ImproperlyConfigured
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.integrations.redis import RedisIntegration
from sentry_sdk.types import Event, Hint

from .base import *  # settings inheritance - star import intentional (see pyproject.toml per-file-ignores)

DEBUG = False
ATOMIC_REQUESTS = True

# ── Production safety guards ───────────────────────────────────────────────────
# WHY crash on boot (not log a warning):
#   SMS_PROVIDER='mock' means OTP code '000000' authenticates ANY user — a
#   silent total auth bypass. A warning would scroll off in deployment logs and
#   never be noticed. A startup crash is the correct severity for a production
#   secret that was never configured. Better to fail a deploy than to ship with
#   zero authentication security.
#   Source: audit §MEDIUM §mock OTP gap in production; Twelve-Factor App §Config.
if SMS_PROVIDER == "mock":  # SMS_PROVIDER defined in base.py via star import
    raise ImproperlyConfigured(
        "SMS_PROVIDER='mock' is not allowed in production. "
        "Set SMS_PROVIDER=twilio or SMS_PROVIDER=msg91 in your production .env."
    )


def _filter_sentry_events(event: Event, hint: Hint) -> Event | None:
    """Strip PII and filter non-actionable errors before they reach Sentry.
    Never send phone numbers, OTPs, or tokens to Sentry.
    """
    # Scrub credentials from request data
    request_data = event.get("request")
    if isinstance(request_data, dict):
        payload = request_data.get("data")
        if isinstance(payload, dict):
            for field in (
                "phone_number",
                "otp",
                "token",
                "refresh_token",
                "access_token",
            ):
                if field in payload:
                    payload[field] = "[Filtered]"

    # Drop expected client errors — not bugs
    exc_group = event.get("exception")
    if isinstance(exc_group, dict):
        for exc in exc_group.get("values", []):
            if isinstance(exc, dict) and exc.get("type") in (
                "Http404",
                "PermissionDenied",
                "ValidationError",
            ):
                return None

    return event


if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        environment="production",
        traces_sample_rate=0.1,
        send_default_pii=False,  # phone numbers, names must NOT reach Sentry
        integrations=[
            DjangoIntegration(
                transaction_style="url",  # group by URL pattern, not raw URL
                middleware_spans=True,  # trace per-middleware execution time
                signals_spans=False,  # no signals in this project
            ),
            CeleryIntegration(
                monitor_beat_tasks=True,  # alert if Celery Beat stops
            ),
            RedisIntegration(),
        ],
        before_send=_filter_sentry_events,
    )

# ── Security headers ───────────────────────────────────────────────────────────
# WHY SECURE_PROXY_SSL_HEADER (P0 — deployment-blocking without this):
#   Nginx terminates TLS and proxies plain HTTP to Gunicorn. Without this,
#   Django thinks every request is HTTP — SECURE_SSL_REDIRECT loops infinitely.
#   Source: Django 6.0 docs §SECURE_PROXY_SSL_HEADER
#   Cookiecutter-Django, Sentry both set this. We were missing it.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

SECURE_SSL_REDIRECT = True

# HSTS — tell browsers to ONLY use HTTPS for this domain for 1 year
SECURE_HSTS_SECONDS = 31_536_000  # 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
# WHY SECURE_HSTS_PRELOAD: submits domain to browser preload lists.
# Browsers will enforce HTTPS even on first-ever visit (before any HSTS header).
# Source: hstspreload.org; cookiecutter-django default since 2024.
SECURE_HSTS_PRELOAD = True

# WHY SECURE_CONTENT_TYPE_NOSNIFF: prevents browsers from guessing MIME types.
# If an attacker uploads a polyglot file (valid image + hidden HTML), Chrome
# would not execute it as HTML. Source: OWASP; Django SecurityMiddleware docs.
SECURE_CONTENT_TYPE_NOSNIFF = True

# WHY SECURE_REFERRER_POLICY: controls how much referrer info is sent when
# navigating from admin to external URLs. "strict-origin-when-cross-origin"
# sends full URL on same-origin, only the origin on cross-origin HTTPS, nothing
# on cross-origin HTTP. Prevents leaking admin paths to external services.
# Source: MDN Referrer-Policy; OWASP Secure Headers Project.
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"

# WHY X_FRAME_OPTIONS = DENY: explicit over Django's default.
# Prevents the admin from being embedded in an <iframe> on any domain.
# Eliminates clickjacking attacks targeting admin sessions.
# Django 3.0+ default is DENY, but explicit = auditable.
X_FRAME_OPTIONS = "DENY"

# WHY SECURE_CROSS_ORIGIN_OPENER_POLICY: isolates the browsing context group.
# Prevents a window opened from the admin from accessing the admin's JS context
# (Cross-Origin Isolation). Required for high-security admin sessions.
# Default since Django 3.2: "same-origin". Explicit here = auditable.
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# WHY CONN_HEALTH_CHECKS: re-validates persistent DB connections before reuse.
# With CONN_MAX_AGE=0 (PgBouncer config) this is a no-op today but is a
# defensive setting — if CONN_MAX_AGE is ever raised it prevents stale errors.
# Source: Django 4.1 release notes (djangoproject.com)
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True
