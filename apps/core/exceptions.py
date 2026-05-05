from __future__ import annotations

from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler


def exception_handler(exc: Exception, context: dict[str, object]) -> Response | None:
    """
    Central DRF exception handler. Produces the api-contract §2 error shape:
    {"error": {"code": "...", "message": "...", "details": {}}}

    Handles two cases:
    1. APIException subclasses (DRF native + our domain exceptions) — mapped here.
    2. Everything else — delegated to DRF default (returns None → Django 500 handler).
    """
    response = drf_exception_handler(exc, context)

    if response is None:
        return None

    # Normalise to api-contract §2 nested error shape regardless of DRF exception type
    if isinstance(response.data, dict) and "detail" in response.data:
        message = str(response.data["detail"])
    else:
        message = str(exc)

    response.data = {
        "error": {
            "code": getattr(exc, "default_code", "error"),
            "message": message,
            "details": {},
        }
    }
    return response
