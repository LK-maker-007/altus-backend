from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any, cast

import jwt
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.http import HttpRequest, HttpResponse

from apps.core.http import AuthenticatedRequest
from apps.core.jwt_utils import decode_jwt
from apps.core.schemas import JWTAccessPayload
from apps.users.models import User

_SSE_TICKET_TTL = 60
_SSE_TICKET_PREFIX = "sse_ticket:"


class JWTAuthMiddleware:

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        auth_request = cast(AuthenticatedRequest, request)
        cast(Any, auth_request).user = AnonymousUser()
        auth_request.complex_id = None
        auth_request.access_jti = None
        auth_request.access_exp = None

        token = self._extract_token(request)
        if token:
            payload = self._decode_token(token)
            if payload is not None:
                user = self._get_user(payload)
                if user is not None:
                    auth_request.user = user
                    auth_request.complex_id = payload.get("complex_id")
                    auth_request.access_jti = payload["jti"]
                    auth_request.access_exp = payload["exp"]
        elif request.GET.get("ticket"):
            self._resolve_sse_ticket(request, auth_request)

        return self.get_response(auth_request)

    @staticmethod
    def _extract_token(request: HttpRequest) -> str | None:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            return auth_header[len("Bearer ") :]
        return None

    @staticmethod
    def _resolve_sse_ticket(
        request: HttpRequest, auth_request: AuthenticatedRequest
    ) -> None:
        ticket = request.GET.get("ticket", "")
        if not ticket:
            return
        try:
            uuid.UUID(ticket)
        except ValueError:
            return

        key = f"{_SSE_TICKET_PREFIX}{ticket}"
        data: dict[str, str] | None = cache.get(key)
        if data is None:
            return

        cache.delete(key)

        try:
            user = User.objects.select_related("complex").get(
                id=data["user_id"], is_active=True
            )
        except (User.DoesNotExist, KeyError):
            return

        cast(Any, auth_request).user = user
        auth_request.complex_id = data.get("complex_id")
        auth_request.access_jti = None
        auth_request.access_exp = None

    @staticmethod
    def _decode_token(token: str) -> JWTAccessPayload | None:
        try:
            raw = decode_jwt(
                token,
                options={
                    "require": ["exp", "user_id", "complex_id", "role", "token_type"]
                },
            )
            if cache.get(f"jti:bl:{raw['jti']}"):
                return None
            return cast(JWTAccessPayload, raw)
        except jwt.InvalidTokenError:
            return None

    @staticmethod
    def _get_user(payload: JWTAccessPayload) -> User | None:
        try:
            return User.objects.select_related("complex").get(
                id=payload["user_id"], is_active=True
            )
        except User.DoesNotExist:
            return None
