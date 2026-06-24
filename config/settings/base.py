from __future__ import annotations

from pathlib import Path

import django_stubs_ext
import environ

django_stubs_ext.monkeypatch()

env = environ.Env()

BASE_DIR = Path(__file__).resolve().parent.parent.parent

_env_file = BASE_DIR / ".env"
if _env_file.exists():
    environ.Env.read_env(_env_file)

ADMIN_URL: str = env("DJANGO_ADMIN_URL", default="admin/")

SECRET_KEY = env("SECRET_KEY")
SECRET_KEY_FALLBACKS: list[str] = env.list("SECRET_KEY_FALLBACKS", default=[])

ALLOWED_HOSTS: list[str] = env.list("ALLOWED_HOSTS", default=[])

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "corsheaders",
    "django_filters",
    "django_celery_beat",
    "drf_spectacular",
]

LOCAL_APPS = [
    "apps.core.CoreConfig",
    "apps.users",
    "apps.facilities",
    "apps.bookings",
    "apps.visitors",
    "apps.packages",
    "apps.maintenance",
    "apps.community",
    "apps.emergency",
    "apps.lost_found",
    "apps.notifications",
    "apps.dashboard",
    "apps.security",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "apps.core.middleware.RequestIdMiddleware",
    "apps.core.middleware.JWTAuthMiddleware",
    "apps.core.middleware.ComplexContextMiddleware",
    "apps.core.middleware.StructuredLoggingMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
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
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": env.db("DATABASE_URL"),
}
DATABASES["default"]["CONN_MAX_AGE"] = 0
DATABASES["default"]["ENGINE"] = "config.db_backend"

NGINX_PROXY_IP: str = env("NGINX_PROXY_IP", default="127.0.0.1")

AUTH_USER_MODEL = "users.User"

JWT_SECRET_KEY = env("JWT_SECRET_KEY")
JWT_ACCESS_TOKEN_LIFETIME_MINUTES = env.int(
    "JWT_ACCESS_TOKEN_LIFETIME_MINUTES", default=15
)
JWT_REFRESH_TOKEN_LIFETIME_DAYS = env.int("JWT_REFRESH_TOKEN_LIFETIME_DAYS", default=30)
JWT_PREVIOUS_SECRET_KEY: str = env("JWT_PREVIOUS_SECRET_KEY", default="")

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "apps.core.authentication.MiddlewareJWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_FILTER_BACKENDS": ["django_filters.rest_framework.DjangoFilterBackend"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.CursorPagination",
    "PAGE_SIZE": 20,
    "EXCEPTION_HANDLER": "apps.core.exceptions.exception_handler",
    "DEFAULT_THROTTLE_CLASSES": [],
    "DEFAULT_THROTTLE_RATES": {
        "otp_send": "3/hour",
        "otp_verify": "5/hour",
        "token_refresh": "5/minute",
        "booking_hold": "10/minute",
    },
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

CELERY_BROKER_URL = env("REDIS_URL")
CELERY_RESULT_BACKEND = None
CELERY_TASK_IGNORE_RESULT = True
CELERY_TASK_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TIMEZONE = "Asia/Kolkata"
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
CELERY_BEAT_SCHEDULE = {
    "expire-stale-booking-holds": {
        "task": "apps.bookings.tasks.expire_stale_holds",
        "schedule": 120,
    },
    "expire-stale-visitor-passes": {
        "task": "apps.visitors.tasks.expire_stale_visitors",
        "schedule": 300,
    },
    "check-expo-push-receipts": {
        "task": "apps.notifications.tasks.check_push_receipts",
        "schedule": 1800,
    },
}


CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": env("REDIS_URL"),
    }
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = False
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CORS_ALLOWED_ORIGINS: list[str] = env.list("CORS_ALLOWED_ORIGINS", default=[])

from config.logging_config import build_logging, configure_structlog

_LOG_LEVEL = env("DJANGO_LOG_LEVEL", default="INFO")
_JSON_LOGS = env.bool("DJANGO_JSON_LOGS", default=False)
LOGGING = build_logging(json_logs=_JSON_LOGS, level=_LOG_LEVEL)
configure_structlog()

SENTRY_DSN = env("SENTRY_DSN", default="")

QR_TOKEN_SECRET = env("QR_TOKEN_SECRET")
QR_TOKEN_LIFETIME_DAYS = env.int("QR_TOKEN_LIFETIME_DAYS", default=7)

R2_ACCOUNT_ID = env("R2_ACCOUNT_ID", default="")
R2_ACCESS_KEY_ID = env("R2_ACCESS_KEY_ID", default="")
R2_SECRET_ACCESS_KEY = env("R2_SECRET_ACCESS_KEY", default="")
R2_BUCKET_NAME = env("R2_BUCKET_NAME", default="yali-media")
R2_PUBLIC_URL = env("R2_PUBLIC_URL", default="")

EXPO_PUSH_URL = env("EXPO_PUSH_URL", default="https://exp.host/--/api/v2/push/send")

SMS_PROVIDER = env("SMS_PROVIDER", default="mock")
TWILIO_ACCOUNT_SID = env("TWILIO_ACCOUNT_SID", default="")
TWILIO_AUTH_TOKEN = env("TWILIO_AUTH_TOKEN", default="")
TWILIO_PHONE_NUMBER = env("TWILIO_PHONE_NUMBER", default="")
TWILIO_VERIFY_SERVICE_SID = env("TWILIO_VERIFY_SERVICE_SID", default="")
MSG91_AUTH_KEY = env("MSG91_AUTH_KEY", default="")
MSG91_TEMPLATE_ID = env("MSG91_TEMPLATE_ID", default="")

SPECTACULAR_SETTINGS = {
    "TITLE": "Yali API",
    "DESCRIPTION": (
        "Apartment complex management API. "
        "Covers auth, bookings, visitors, maintenance, packages, and community."
    ),
    "VERSION": "1.0.0",
    "CONTACT": {"name": "Yali Engineering"},
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "DISABLE_ERRORS_AND_WARNINGS": False,
    "ENUM_NAME_OVERRIDES": {
        "FacilityCategoryEnum": "apps.facilities.models.FacilityCategory",
        "TicketCategoryEnum": "apps.maintenance.models.TicketCategory",
        "AnnouncementCategoryEnum": "apps.community.models.AnnouncementCategory",
        "BookingStatusEnum": "apps.bookings.models.BookingStatus",
        "VisitorStatusEnum": "apps.visitors.models.VisitorStatus",
        "PackageStatusEnum": "apps.packages.models.PackageStatus",
        "TicketStatusEnum": "apps.maintenance.models.TicketStatus",
        "LostFoundStatusEnum": "apps.lost_found.models.LostFoundStatus",
    },
}
