"""
apps/core/authentication.py

WHY this exists — The Root Cause:
    Django's MIDDLEWARE list runs sequentially. The original code had:
        ...
        JWTAuthMiddleware      (line 61) → sets request.user = jwt_user
        AuthenticationMiddleware (line 66) → OVERWRITES request.user = AnonymousUser

    AuthenticationMiddleware always overwrites request.user with a session-based
    user (AnonymousUser for API requests). So when DRF's MiddlewareJWTAuthentication
    read request._request.user, it got AnonymousUser — not our jwt_user.

WHY this fix works:
    Decode the JWT directly from the Authorization header inside the DRF
    authentication class. This is self-contained and immune to middleware ordering.
    It re-uses JWTAuthMiddleware's _decode_token / _get_user static methods so
    the JWT verification logic stays in a single place.

    This is the canonical pattern used by drf-simplejwt, djangorestframework-jwt,
    and the DRF docs §"Custom authentication":
    https://www.django-rest-framework.org/api-guide/authentication/#custom-authentication

WHY keep JWTAuthMiddleware:
    It still serves a purpose: it sets request.complex_id (used by
    ComplexContextMiddleware and structured logging). The middleware and this
    class share _decode_token / _get_user so JWT verification is DRY.
"""

from __future__ import annotations

from rest_framework.authentication import BaseAuthentication
from rest_framework.request import Request

from apps.core.middleware.jwt_auth import JWTAuthMiddleware
from apps.users.models import User


class MiddlewareJWTAuthentication(BaseAuthentication):
    """
    DRF authentication class that decodes the Bearer JWT from the Authorization
    header and returns the authenticated User.

    Re-uses JWTAuthMiddleware._decode_token and ._get_user so JWT verification
    logic is not duplicated. Returns None (not AnonymousUser) on failure —
    this signals DRF to try the next authenticator (of which there are none,
    so it falls through to UNAUTHENTICATED_USER = AnonymousUser).

    WHY not read request._request.user:
        AuthenticationMiddleware (Django built-in) runs AFTER JWTAuthMiddleware
        in the MIDDLEWARE stack and overwrites request.user with a session-based
        AnonymousUser. Reading request._request.user would always yield AnonymousUser.
    """

    def authenticate(self, request: Request) -> tuple[User, None] | None:
        # Extract raw token from Authorization header on the underlying HttpRequest.
        # Using request._request (not request) to bypass DRF's header parsing.
        token = JWTAuthMiddleware._extract_token(request._request)
        if not token:
            return None  # No Bearer header — unauthenticated

        payload = JWTAuthMiddleware._decode_token(token)
        if payload is None:
            return None  # Invalid / expired JWT — unauthenticated

        user = JWTAuthMiddleware._get_user(payload)
        if user is None:
            return None  # User deleted or deactivated since token issuance

        return (user, None)
