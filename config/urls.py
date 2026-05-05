from __future__ import annotations

from django.conf import settings
from django.contrib import admin
from django.db import connection
from django.http import HttpRequest, JsonResponse
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView


def health(request: HttpRequest) -> JsonResponse:
    """GET /health/ — load balancer and k8s readiness probe.

    WHY a DB connectivity check (not just HTTP 200):
      A process that is up but cannot reach the DB will fail every request.
      Returning 200 to the load balancer in that state routes live traffic to
      a broken instance. Checking DB connectivity makes the health signal accurate.

    WHY not using Django's check framework:
      System checks run at startup, not per-request. They don't detect runtime
      DB connection failures (pool exhaustion, network partition).

    WHY no authentication:
      Load balancers and readiness probes must reach this endpoint without auth.
      The response contains no sensitive data — just service status.

    Source: MAANG comparison §observability gap; k8s readiness probe convention;
            getsentry/sentry §/api/0/_health/.
    """
    try:
        connection.ensure_connection()
        db_ok = True
    except Exception:
        db_ok = False

    status = 200 if db_ok else 503
    return JsonResponse(
        {"status": "ok" if db_ok else "degraded", "db": db_ok}, status=status
    )


urlpatterns = [
    # GET /health/ — load balancer readiness probe. Unauthenticated by design.
    # Returns 200 {"status": "ok"} if DB is reachable,
    # 503 {"status": "degraded"} otherwise.
    path("health/", health, name="health"),
    # WHY settings.ADMIN_URL (not hardcoded "admin/"):
    #   Automated scanners probe /admin/ on every Django site. A non-guessable
    #   path (set via DJANGO_ADMIN_URL env var in production) reduces attack surface.
    #   Development default: "admin/". Production: set to a UUID-like path.
    #   Source: OWASP A05:2021; cookiecutter-django; Sentry.
    path(settings.ADMIN_URL, admin.site.urls),
    path("api/v1/", include("config.api_urls")),
    # Raw OpenAPI schema (YAML/JSON) — available in all environments.
    # WHY explicit registration: makes the schema URL auditable and allows
    # per-environment permission controls (e.g. IsAdminUser in production).
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
]

# WHY DEBUG-only Swagger UI:
#   The previous comment "disable in production via nginx deny rule" relied on an
#   external assumption. Django-level enforcement is defence-in-depth: if nginx
#   is misconfigured, the URL simply returns 404 rather than exposing the full
#   interactive API explorer. The raw schema remains available for contract tests.
if settings.DEBUG:
    urlpatterns += [
        path(
            "api/schema/ui/",
            SpectacularSwaggerView.as_view(url_name="schema"),
            name="swagger-ui",
        ),
    ]
