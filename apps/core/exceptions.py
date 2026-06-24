from __future__ import annotations

from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler


def exception_handler(exc: Exception, context: dict[str, object]) -> Response | None:
    response = drf_exception_handler(exc, context)

    if response is None:
        return None

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
