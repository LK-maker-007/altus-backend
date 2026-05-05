from __future__ import annotations

from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

from apps.core.context import (
    _clear_context_var_complex_id,
    _set_context_var_complex_id,
)


class ComplexContextMiddleware:
    """Sets the ContextVar for multi-tenant Row-Level Security.

    complex_id resolution order (first non-None wins):
      1. request.complex_id — set by JWTAuthMiddleware from the Bearer token payload.
      2. request._force_auth_user.complex_id — DRF APIClient.force_authenticate()
         in tests.
      3. request.user.complex_id — Django session auth (Django Admin).

    WHY the transaction.atomic() + SET LOCAL was removed (Google review §SIGNIFICANT):
      SET LOCAL app.current_complex scopes to the current transaction. The intent was to
      support PostgreSQL Row-Level Security (RLS) policies that read this setting.
      The SET LOCAL + transaction overhead was removed because RLS is now enforced via
      PostgreSQL-native CREATE POLICY statements (migration 0003_rls_policies.py,
      ADR-012). DB policies enforce tenant isolation at the database layer independently
      of this middleware. The ContextVar (set here) feeds ComplexScopedManager for
      application-layer filtering (first line of defence); RLS policies are the second.
      Adding SET LOCAL back would require the PG role to have app.current_complex
      privileges and would add a round-trip on every request for no additional security.
      Source: ADR-012 §Decision.

    WHY try/finally for _clear_context_var_complex_id():
      If get_response(request) raises an uncaught exception, the ContextVar would remain
      set for the current thread's next request (in a thread-pool worker). The finally
      block guarantees cleanup regardless of success or exception.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        from uuid import UUID  # local to avoid top-level import cycle

        # Primary: JWT middleware writes this from the token payload.
        complex_id: str | UUID | None = getattr(request, "complex_id", None)

        # Fallback 1: DRF APIClient.force_authenticate() sets request._force_auth_user
        # *before* the middleware chain runs — request.user is still AnonymousUser here.
        if not complex_id:
            forced_user = getattr(request, "_force_auth_user", None)
            if forced_user is not None and not getattr(
                forced_user, "is_anonymous", True
            ):
                complex_id = getattr(forced_user, "complex_id", None)

        # Fallback 2: Django session auth (Django Admin).
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
            # Guarantees cleanup even when get_response() raises.
            # Prevents context bleed between requests in the same thread worker.
            _clear_context_var_complex_id()
