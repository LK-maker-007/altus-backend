from __future__ import annotations

from rest_framework.authentication import BaseAuthentication
from rest_framework.request import Request

from apps.core.middleware.jwt_auth import JWTAuthMiddleware
from apps.users.models import User


class MiddlewareJWTAuthentication(BaseAuthentication):

    def authenticate(self, request: Request) -> tuple[User, None] | None:
        token = JWTAuthMiddleware._extract_token(request._request)
        if not token:
            return None

        payload = JWTAuthMiddleware._decode_token(token)
        if payload is None:
            return None

        user = JWTAuthMiddleware._get_user(payload)
        if user is None:
            return None

        return (user, None)
