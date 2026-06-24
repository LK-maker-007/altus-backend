from __future__ import annotations

from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

from apps.core.context import (
    _clear_context_var_complex_id,
    _set_context_var_complex_id,
)


class ComplexContextMiddleware:

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        from uuid import UUID

        complex_id: str | UUID | None = getattr(request, "complex_id", None)

        if not complex_id:
            forced_user = getattr(request, "_force_auth_user", None)
            if forced_user is not None and not getattr(
                forced_user, "is_anonymous", True
            ):
                complex_id = getattr(forced_user, "complex_id", None)

        if not complex_id:
            user = getattr(request, "user", None)
            if user is not None and not getattr(user, "is_anonymous", True):
                complex_id = getattr(user, "complex_id", None)

        if not complex_id:
            _clear_context_var_complex_id()
            return self.get_response(request)

        _set_context_var_complex_id(str(complex_id))
        try:
            return self.get_response(request)
        finally:
            _clear_context_var_complex_id()
