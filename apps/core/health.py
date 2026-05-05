from __future__ import annotations

from collections.abc import Sequence

from django.core.cache import cache
from django.db import OperationalError, connection
from drf_spectacular.utils import extend_schema
from rest_framework.authentication import BaseAuthentication
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

# Empty tuples — no auth or permissions required for health probes.
# Tuple pattern matches other views in this codebase (_PUBLIC, _AUTH).
# Tuples are immutable → no RUF012; Sequence[_type] satisfies DRF stubs.
_NO_PERMISSIONS: Sequence[type[BasePermission]] = ()
_NO_AUTH: Sequence[type[BaseAuthentication]] = ()


class HealthCheckView(APIView):
    """
    GET /api/v1/health/ — Health check for Docker/K8s/LB probes.

    Used by:
      - Docker compose healthcheck for the api service
      - Kubernetes readiness + liveness probes
      - Load balancer health checks

    Checks:
      1. PostgreSQL — SELECT 1 via Django ORM connection
      2. Redis — set/get round-trip via Django cache backend

    Returns 200 when all dependencies healthy, 503 when any fail.

    503 (not 500): "Service Unavailable" tells load balancers to remove
    this instance from rotation. 500 signals a bug; a dependency being
    down is not a bug.

    NOT behind IsAuthenticated — K8s probes have no Bearer token.
    Source: Google SRE Book ch4 + github.com/getsentry/self-hosted (2026-04-25)
    """

    # Public endpoint — K8s/Docker probes have no Bearer token.
    permission_classes = _NO_PERMISSIONS
    authentication_classes = _NO_AUTH

    @extend_schema(
        auth=[],  # public — K8s/Docker probes have no Bearer token
        responses={
            200: {
                "type": "object",
                "properties": {
                    "status": {"type": "string"},
                    "checks": {"type": "object"},
                },
            },
            503: {
                "type": "object",
                "properties": {
                    "status": {"type": "string"},
                    "checks": {"type": "object"},
                },
            },
        },
        summary="Health check — PostgreSQL + Redis readiness probe",
        tags=["ops"],
    )
    def get(self, request: Request) -> Response:
        checks: dict[str, str] = {}
        is_healthy = True

        # ── PostgreSQL check ──────────────────────────────────────────────────
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            checks["database"] = "ok"
        except OperationalError as exc:
            checks["database"] = f"error: {exc}"
            is_healthy = False

        # ── Redis check ───────────────────────────────────────────────────────
        try:
            # cache.set + get is the safest health check — PING is not exposed
            # uniformly across all cache backends (Redis, Memcached, locmem).
            # set/get works on all of them and tests the full cache round-trip.
            probe_key = "_health_probe"
            cache.set(probe_key, "1", timeout=5)
            result = cache.get(probe_key)
            if result != "1":
                raise ValueError("Cache round-trip failed: got unexpected value")
            checks["cache"] = "ok"
        except Exception as exc:  # cache.set can raise on connection error
            checks["cache"] = f"error: {exc}"
            is_healthy = False

        status_code = 200 if is_healthy else 503
        return Response(
            {
                "status": "ok" if is_healthy else "degraded",
                "checks": checks,
            },
            status=status_code,
        )
