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

_NO_PERMISSIONS: Sequence[type[BasePermission]] = ()
_NO_AUTH: Sequence[type[BaseAuthentication]] = ()


class HealthCheckView(APIView):

    permission_classes = _NO_PERMISSIONS
    authentication_classes = _NO_AUTH

    @extend_schema(
        auth=[],
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

        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            checks["database"] = "ok"
        except OperationalError as exc:
            checks["database"] = f"error: {exc}"
            is_healthy = False

        try:
            probe_key = "_health_probe"
            cache.set(probe_key, "1", timeout=5)
            result = cache.get(probe_key)
            if result != "1":
                raise ValueError("Cache round-trip failed: got unexpected value")
            checks["cache"] = "ok"
        except Exception as exc:
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
