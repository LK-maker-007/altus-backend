from __future__ import annotations

import time
from collections.abc import Callable

import structlog
from django.http import HttpRequest, HttpResponse

logger = structlog.get_logger(__name__)


class StructuredLoggingMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        started_at = time.monotonic()
        status_code = 500  # default; overwritten on success
        try:
            response = self.get_response(request)
            status_code = response.status_code
            return response
        except Exception:
            raise
        finally:
            # WHY finally (not after get_response):
            #   If get_response raises an unhandled exception (Django 500 path),
            #   execution never reaches the line after the call — the request is
            #   silently un-logged. try/finally guarantees request_completed fires
            #   for every request, including 500s. Pattern from
            #   ComplexContextMiddleware.
            #   Source: audit §Minor §StructuredLoggingMiddleware 500 path.
            user = getattr(request, "user", None)
            logger.info(
                "request_completed",
                method=request.method,
                path=request.path,
                status=status_code,
                request_id=getattr(request, "request_id", None),
                complex_id=str(getattr(request, "complex_id", "") or ""),
                user_id=str(user.id) if user and user.is_authenticated else None,
                duration_ms=round((time.monotonic() - started_at) * 1000),
            )
