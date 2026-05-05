from __future__ import annotations

from django.http import HttpRequest

from apps.users.models import User


class AuthenticatedRequest(HttpRequest):
    """Typed HttpRequest subclass for views where JWTAuthMiddleware has run.

    Used as the request type annotation in views and middleware that rely on
    request.user being a resolved User and request.complex_id / request.request_id
    being set. Do NOT instantiate directly — Django creates HttpRequest;
    this class only exists to satisfy mypy's type checker.

    Reference: django-stubs typed request pattern —
    https://github.com/typeddjango/django-stubs#how-to-use
    """

    user: User  # narrowed from AbstractBaseUser — set by JWTAuthMiddleware
    complex_id: str | None
    request_id: str
    # WHY access_jti / access_exp on the request:
    #   LogoutView must blacklist the *current* access token's JTI so that the
    #   token is immediately revoked — not just after its 15-min natural expiry.
    #   Storing JTI + exp here avoids re-decoding the token in the view and keeps
    #   decode logic in one place (JWTAuthMiddleware._decode_token).
    access_jti: str | None  # JTI claim of current access token; None if unauthenticated
    access_exp: int | None  # exp claim of current access token; used to set Redis TTL
