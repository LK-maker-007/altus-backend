from __future__ import annotations

from pathlib import Path

import django_stubs_ext
import environ  # django-environ 0.11.2 ships py.typed — no ignore needed

# WHY django_stubs_ext.monkeypatch():
#   django-stubs README §Installation: "required as a production dependency when
#   using generic subscript syntax (ModelAdmin[Model], QuerySet[Model]) in class
#   definitions." Without this, Python raises TypeError at runtime because Django's
#   ModelAdmin / QuerySet / Manager are not subscriptable.
#   Cost: zero — patches __class_getitem__ on a fixed set of Django classes.
#   Source: github.com/typeddjango/django-stubs → Installation → django_stubs_ext
django_stubs_ext.monkeypatch()

env = environ.Env()

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# WHY conditional (not unconditional) read_env:
#   In production containers, all secrets come from the container environment
#   (ECS task definition, Kubernetes secrets, etc.) — a .env file should not
#   exist. If one is accidentally committed or left on the server, unconditional
#   read_env() silently overrides the real container env vars with stale values.
#   The guard: only read .env if it physically exists. Local development is
#   unaffected (the file exists). Production containers are unaffected (the file
#   doesn't exist). Source: audit §Minor §.env unconditional load; cookiecutter-django.
_env_file = BASE_DIR / ".env"
if _env_file.exists():
    environ.Env.read_env(_env_file)

# ── Admin URL ─────────────────────────────────────────────────────────────────
# WHY env-configurable: avoids the predictable /admin/ path.
# Development: default "admin/". Production: set DJANGO_ADMIN_URL to a
# non-guessable path (e.g. "_admin-a8f3c1/") in the env file.
# Pattern: cookiecutter-django, Sentry.
ADMIN_URL: str = env("DJANGO_ADMIN_URL", default="admin/")

# ── Security ──────────────────────────────────────────────────────────────────
SECRET_KEY = env("SECRET_KEY")
# WHY SECRET_KEY_FALLBACKS (Django 4.1+):
#   During SECRET_KEY rotation, Django Admin sessions and CSRF tokens signed
#   with the old key remain valid. SECRET_KEY_FALLBACKS lists previous keys
#   that Django accepts for *verification* only (never for new signing).
#   Rotation: move old SECRET_KEY here → set new value as SECRET_KEY → deploy
#   → after session TTL clears (≤2 weeks), empty this list → deploy.
#   Source: Django 4.1 release notes §SECRET_KEY_FALLBACKS; docs/runbooks/secrets-rotation.md.
SECRET_KEY_FALLBACKS: list[str] = env.list("SECRET_KEY_FALLBACKS", default=[])

ALLOWED_HOSTS: list[str] = env.list("ALLOWED_HOSTS", default=[])

# ── Application ───────────────────────────────────────────────────────────────
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",  # ExclusionConstraint, HStoreField, RangeField
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "corsheaders",
    "django_filters",
    "django_celery_beat",
    # WHY drf_spectacular: machine-readable OpenAPI schema for contract testing
    # and preventing silent breaking changes between backend and mobile client.
    # Source: Google Principal Architect review §MISSING "No OpenAPI/Schema Generation"
    "drf_spectacular",
]

LOCAL_APPS = [
    # WHY "apps.core.CoreConfig" (not "apps.core"):
    #   Django 6 auto-discovery only finds AppConfig subclasses from apps.py,
    #   not from __init__.py. The full dotted path forces Django to use our
    #   CoreConfig, which calls ready() → imports apps.core.openapi →
    #   registers MiddlewareJWTAuthenticationScheme in drf-spectacular's
    #   extension registry before any schema check or system check runs.
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

# ── Middleware ─────────────────────────────────────────────────────────────────
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

# ── Database ───────────────────────────────────────────────────────────────────
DATABASES = {
    "default": env.db("DATABASE_URL"),
}
DATABASES["default"]["CONN_MAX_AGE"] = 0  # PgBouncer transaction mode requires 0
# WHY config.db_backend (custom ENGINE):
#   The PostgreSQL RLS policies in 0003_rls_policies.py use:
#     USING (complex_id::text = current_setting('app.current_complex', true))
#   current_setting() returns NULL when the GUC is never SET → policy evaluates
#   to false → all RLS-protected tables silently return zero rows (or BYPASSRLS
#   bypasses them entirely). config/db_backend/base.py injects SET LOCAL
#   app.current_complex into every cursor when the ContextVar is active, bridging
#   the application-layer ComplexScopedManager to the DB-layer RLS policies.
#   Source: config/db_backend/base.py; ADR-012; audit §Critical §RLS GUC.
DATABASES["default"]["ENGINE"] = "config.db_backend"

# ── Nginx proxy IP (used by Gunicorn forwarded_allow_ips) ──────────────────────
# WHY env-configurable:
#   Gunicorn must only trust X-Forwarded-For from known proxy IPs to prevent
#   spoofing. Development: 127.0.0.1 (nginx on localhost). Production: set
#   NGINX_PROXY_IP to the private IP of the nginx/load-balancer instance.
#   Source: gunicorn.conf.py §Security; audit §Significant §forwarded_allow_ips.
NGINX_PROXY_IP: str = env("NGINX_PROXY_IP", default="127.0.0.1")

# ── Auth ───────────────────────────────────────────────────────────────────────
AUTH_USER_MODEL = "users.User"

# ── JWT (custom — not simplejwt) ───────────────────────────────────────────────
JWT_SECRET_KEY = env("JWT_SECRET_KEY")
JWT_ACCESS_TOKEN_LIFETIME_MINUTES = env.int(
    "JWT_ACCESS_TOKEN_LIFETIME_MINUTES", default=15  # US-004: 15-minute access token
)
JWT_REFRESH_TOKEN_LIFETIME_DAYS = env.int(
    "JWT_REFRESH_TOKEN_LIFETIME_DAYS", default=30  # US-004: 30-day refresh token
)
# WHY JWT_PREVIOUS_SECRET_KEY (zero-downtime JWT rotation):
#   During JWT_SECRET_KEY rotation, tokens signed with the old key remain valid
#   for up to JWT_REFRESH_TOKEN_LIFETIME_DAYS (default 30 days). Setting this
#   to the old key value allows apps.core.jwt_utils.decode_jwt() to accept both
#   old and new tokens during the transition window.
#   Rotation procedure:
#     1. JWT_PREVIOUS_SECRET_KEY = <old JWT_SECRET_KEY>  → deploy
#     2. JWT_SECRET_KEY = <new key>                      → deploy
#     3. After 30 days (all old tokens expired), unset JWT_PREVIOUS_SECRET_KEY → deploy
#   Run `python manage.py rotate_jwt_secret` for a guided rotation assistant.
#   Source: docs/runbooks/secrets-rotation.md; auth_patterns_2026.md §JWT Rotation.
JWT_PREVIOUS_SECRET_KEY: str = env("JWT_PREVIOUS_SECRET_KEY", default="")

# ── DRF ────────────────────────────────────────────────────────────────────────
REST_FRAMEWORK = {
    # WHY empty list is gone — see apps/core/authentication.py for the full explanation.
    # TL;DR: DRF's Request.user ignores Django middleware. DEFAULT_AUTHENTICATION_CLASSES=[]
    # caused IsAuthenticated to always see AnonymousUser → 403 on all protected views.
    # MiddlewareJWTAuthentication bridges JWTAuthMiddleware's result into DRF.
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "apps.core.authentication.MiddlewareJWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_FILTER_BACKENDS": ["django_filters.rest_framework.DjangoFilterBackend"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.CursorPagination",
    "PAGE_SIZE": 20,
    "EXCEPTION_HANDLER": "apps.core.exceptions.exception_handler",
    # WHY empty DEFAULT_THROTTLE_CLASSES (not global): throttles are applied
    # per-view with throttle_classes = [...]. Global throttling would apply to ALL
    # endpoints including health checks, admin, and static files — wrong.
    # Rates are defined here so they can be tuned without code changes.
    "DEFAULT_THROTTLE_CLASSES": [],
    "DEFAULT_THROTTLE_RATES": {
        # 3 OTP send requests/hour per phone number — cost-denial attack prevention
        "otp_send": "3/hour",
        # 5 OTP verify requests/hour per phone number — brute-force prevention
        # OTPService.check_lockout() provides a secondary 3-attempt/15-min defence
        "otp_verify": "5/hour",
        # 5 token refresh requests/minute per IP — replay attack prevention
        # Access token TTL is 15 min so legitimate clients hit this ~4x/hour.
        # 5/min allows retries while blocking automated stuffing (100s/second).
        "token_refresh": "5/minute",
        # 10 booking hold requests/minute per resident — prevents slot denial-of-service.
        # A resident creating a hold takes ≤1 second of real interaction. 10/min
        # accommodates network retries while blocking automated slot-hoarding scripts.
        # GiST exclusion constraint is the data-integrity backstop; this is the
        # abuse-prevention layer. Source: audit §MEDIUM §BookingHoldView no throttle.
        "booking_hold": "10/minute",
    },
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

# ── Celery ─────────────────────────────────────────────────────────────────────
CELERY_BROKER_URL = env("REDIS_URL")
CELERY_RESULT_BACKEND = None
CELERY_TASK_IGNORE_RESULT = True
CELERY_TASK_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TIMEZONE = "Asia/Kolkata"
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
CELERY_BEAT_SCHEDULE = {
    # Sweep holds past their TTL every 2 minutes.
    # Low-risk: .update() is idempotent; already-expired rows are a no-op.
    "expire-stale-booking-holds": {
        "task": "apps.bookings.tasks.expire_stale_holds",
        "schedule": 120,  # seconds
    },
    # Sweep visitor passes past their expected_until window every 5 minutes.
    "expire-stale-visitor-passes": {
        "task": "apps.visitors.tasks.expire_stale_visitors",
        "schedule": 300,  # seconds
    },
    # Phase 2 of Expo push API: poll getReceipts for SENT notifications.
    # WHY 30 minutes: Expo docs state receipts are available "15-30 minutes
    # after sending". Running every 30 min ensures receipts are always ready.
    # Task is idempotent — only processes SENT records older than 15 min.
    # Source: docs.expo.dev/push-notifications/sending-notifications/#receipts
    "check-expo-push-receipts": {
        "task": "apps.notifications.tasks.check_push_receipts",
        "schedule": 1800,  # 30 minutes in seconds
    },
}


# ── Cache ──────────────────────────────────────────────────────────────────────
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": env("REDIS_URL"),
    }
}

# ── Internationalisation ────────────────────────────────────────────────────────
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = False
USE_TZ = True

# ── Static ─────────────────────────────────────────────────────────────────────
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# NOTE: every model in this codebase declares an explicit UUID PK.
# This setting only affects models WITHOUT a declared PK field.
# django-stubs mypy plugin crashes when this is UUIDField (plugin bug).
# Enforcing the UUID-only contract via code review and CheckConstraints.
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ── CORS ───────────────────────────────────────────────────────────────────────
CORS_ALLOWED_ORIGINS: list[str] = env.list("CORS_ALLOWED_ORIGINS", default=[])

# ── Sentry ─────────────────────────────────────────────────────────────────────
SENTRY_DSN = env("SENTRY_DSN", default="")

# ── QR token ───────────────────────────────────────────────────────────────────
QR_TOKEN_SECRET = env("QR_TOKEN_SECRET")
QR_TOKEN_LIFETIME_DAYS = env.int("QR_TOKEN_LIFETIME_DAYS", default=7)

# ── Cloudflare R2 ──────────────────────────────────────────────────────────────
R2_ACCOUNT_ID = env("R2_ACCOUNT_ID", default="")
R2_ACCESS_KEY_ID = env("R2_ACCESS_KEY_ID", default="")
R2_SECRET_ACCESS_KEY = env("R2_SECRET_ACCESS_KEY", default="")
R2_BUCKET_NAME = env("R2_BUCKET_NAME", default="yali-media")
R2_PUBLIC_URL = env("R2_PUBLIC_URL", default="")

# ── Expo Push ──────────────────────────────────────────────────────────────────
EXPO_PUSH_URL = env("EXPO_PUSH_URL", default="https://exp.host/--/api/v2/push/send")

# ── SMS ────────────────────────────────────────────────────────────────────────
# SMS_PROVIDER: 'mock' (local dev) | 'twilio' (current prod) | 'msg91' (future).
# When SMS_PROVIDER=twilio, all TWILIO_* vars are required — no defaults.
# Missing secrets crash on boot rather than silently sending nothing (§10.1).
SMS_PROVIDER = env("SMS_PROVIDER", default="mock")
TWILIO_ACCOUNT_SID = env("TWILIO_ACCOUNT_SID", default="")
TWILIO_AUTH_TOKEN = env("TWILIO_AUTH_TOKEN", default="")
TWILIO_PHONE_NUMBER = env("TWILIO_PHONE_NUMBER", default="")
# Twilio Verify Service SID — required when SMS_PROVIDER=twilio
TWILIO_VERIFY_SERVICE_SID = env("TWILIO_VERIFY_SERVICE_SID", default="")
# MSG91 — alternative Indian SMS provider. Required when SMS_PROVIDER=msg91.
# WHY default="": matches the Twilio pattern above; prod .env must set these.
MSG91_AUTH_KEY = env("MSG91_AUTH_KEY", default="")
MSG91_TEMPLATE_ID = env("MSG91_TEMPLATE_ID", default="")

# ── OpenAPI / drf-spectacular ──────────────────────────────────────────────────
# Machine-readable API contract. Exposes /api/schema/ (download) and
# /api/schema/ui/ (Swagger UI — development only).
# WHY SERVE_INCLUDE_SCHEMA=False: schema endpoint is registered explicitly in
# urls.py, not auto-included. This makes the schema URL auditable and allows
# permission controls to be added (e.g., IsAdminUser for production).
SPECTACULAR_SETTINGS = {
    "TITLE": "Yali API",
    "DESCRIPTION": (
        "Apartment complex management API. "
        "Covers auth, bookings, visitors, maintenance, packages, and community."
    ),
    "VERSION": "1.0.0",
    "CONTACT": {"name": "Yali Engineering"},
    "SERVE_INCLUDE_SCHEMA": False,
    # WHY COMPONENT_SPLIT_REQUEST=True: separate request/response schemas
    # so request bodies (which lack read-only fields) are documented correctly.
    "COMPONENT_SPLIT_REQUEST": True,
    # WHY DISABLE_ERRORS_AND_WARNINGS=False: expose schema warnings during
    # development so incomplete view annotations are caught early.
    "DISABLE_ERRORS_AND_WARNINGS": False,
    # WHY ENUM_NAME_OVERRIDES:
    #   Multiple models share field names "category" and "status" but carry
    #   different TextChoices sets. spectacular's postprocess_schema_enums hook
    #   (active by default) detects this as a naming collision and emits W001,
    #   appending a hash-based suffix (e.g. "Status14bEnum") to disambiguate.
    #   ENUM_NAME_OVERRIDES maps a stable, human-readable name to each
    #   TextChoices class via its full import path. spectacular resolves the
    #   import at schema-generation time and uses the key as the component name.
    #   Source: drf-spectacular docs §FAQ "I get warnings regarding my Enum";
    #           drf-spectacular.readthedocs.io/en/latest/faq.html (2026).
    "ENUM_NAME_OVERRIDES": {
        # --- "category" collisions (3 models, 3 distinct choice sets) ---
        "FacilityCategoryEnum": "apps.facilities.models.FacilityCategory",
        "TicketCategoryEnum": "apps.maintenance.models.TicketCategory",
        "AnnouncementCategoryEnum": "apps.community.models.AnnouncementCategory",
        # --- "status" collisions (5 models, 5 distinct choice sets) ---
        "BookingStatusEnum": "apps.bookings.models.BookingStatus",
        "VisitorStatusEnum": "apps.visitors.models.VisitorStatus",
        "PackageStatusEnum": "apps.packages.models.PackageStatus",
        "TicketStatusEnum": "apps.maintenance.models.TicketStatus",
        "LostFoundStatusEnum": "apps.lost_found.models.LostFoundStatus",
    },
}
# NOTE: No SILENCED_SYSTEM_CHECKS.
# drf_spectacular.W001 (unknown authenticator) is resolved by
# MiddlewareJWTAuthenticationScheme in apps/core/openapi.py.
# drf-spectacular auto-discovers OpenApiAuthenticationExtension subclasses
# from any module imported at startup — apps.core.openapi is loaded via
# apps.core AppConfig.ready() (see apps/core/apps.py).
