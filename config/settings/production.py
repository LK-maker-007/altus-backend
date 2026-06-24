from __future__ import annotations

import sentry_sdk
from django.core.exceptions import ImproperlyConfigured
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.integrations.redis import RedisIntegration
from sentry_sdk.types import Event, Hint

from config.logging_config import build_logging

from .base import *

DEBUG = False
ATOMIC_REQUESTS = True

LOGGING = build_logging(json_logs=True, level=env("DJANGO_LOG_LEVEL", default="INFO"))

if SMS_PROVIDER == "mock":
    raise ImproperlyConfigured(
        "SMS_PROVIDER='mock' is not allowed in production. "
        "Set SMS_PROVIDER=twilio or SMS_PROVIDER=msg91 in your production .env."
    )


def _filter_sentry_events(event: Event, hint: Hint) -> Event | None:
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
        send_default_pii=False,
        integrations=[
            DjangoIntegration(
                transaction_style="url",
                middleware_spans=True,
                signals_spans=False,
            ),
            CeleryIntegration(
                monitor_beat_tasks=True,
            ),
            RedisIntegration(),
        ],
        before_send=_filter_sentry_events,
    )

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

SECURE_SSL_REDIRECT = True

SECURE_HSTS_SECONDS = 31_536_000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

SECURE_CONTENT_TYPE_NOSNIFF = True

SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"

X_FRAME_OPTIONS = "DENY"

SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

DATABASES["default"]["CONN_HEALTH_CHECKS"] = True
