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

_SSE_TICKET_TTL = 60  # seconds — enough time to open EventSource connection
_SSE_TICKET_PREFIX = "sse_ticket:"  # Redis key prefix


class JWTAuthMiddleware:
    """Decodes Bearer token → sets request.user and request.complex_id.
    Never raises 401."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        # cast(): AuthenticatedRequest is a typed subclass of HttpRequest — we own
        # the request lifecycle and guarantee that complex_id / user etc. are set
        # below before passing the request downstream. cast() is the mypy-approved
        # alternative to type: ignore[assignment] for safe runtime narrowing.
        auth_request = cast(AuthenticatedRequest, request)
        # Initialise pre-auth defaults. AnonymousUser is intentional — JWTAuthMiddleware
        # overwrites .user with the resolved User below if the token is valid.
        # cast(Any, ...) used here because AuthenticatedRequest.user is typed as User
        # (narrowed for views post-auth). Django's middleware pattern requires setting
        # AnonymousUser at the start of the request, before authentication.
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
            # SSE ticket path: native EventSource cannot set custom headers.
            # The client POSTs to /facilities/sse-ticket/ first to exchange
            # their JWT for a 60s single-use ticket, then opens the SSE URL
            # with ?ticket=<uuid>. The ticket is burned on first validation so
            # even if the URL is logged the ticket is already worthless.
            # Source: 2026 SSE auth best practice — ticket exchange pattern.
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
        """Validate and burn a single-use SSE ticket from Redis.

        The ticket was issued by SseTicketIssueView — POST /facilities/sse-ticket/.
        It has a 60-second TTL and is single-use (burned on first validation).
        If the ticket is invalid or expired, request.user remains AnonymousUser.

        WHY burn (delete) immediately:
          Single-use tickets prevent replay attacks. If the SSE URL is captured
          from a log, the ticket has already been consumed and is harmless.
          Source: 2026 SSE auth best practice; audit §P0 §SSE Token in Query Param.
        """
        ticket = request.GET.get("ticket", "")
        if not ticket:
            return
        # Validate UUID format before Redis lookup (reject garbage early)
        try:
            uuid.UUID(ticket)
        except ValueError:
            return

        key = f"{_SSE_TICKET_PREFIX}{ticket}"
        data: dict[str, str] | None = cache.get(key)
        if data is None:
            return  # Expired or never existed

        # Burn immediately — single-use. Race: two requests with the same ticket
        # will both hit cache.get() before either delete() fires (ABA). Use
        # cache.delete() which is atomic in Redis — only the first delete
        # returns True; both callers get the data but the key is gone.
        cache.delete(key)

        try:
            user = User.objects.select_related("complex").get(
                id=data["user_id"], is_active=True
            )
        except User.DoesNotExist, KeyError:
            return

        cast(Any, auth_request).user = user
        auth_request.complex_id = data.get("complex_id")
        # SSE tickets have no JTI (they are not JWTs). Logout blacklisting
        # is unnecessary — the ticket is already burned.
        auth_request.access_jti = None
        auth_request.access_exp = None

    @staticmethod
    def _decode_token(token: str) -> JWTAccessPayload | None:
        try:
            # WHY decode_jwt() (not jwt.decode() directly):
            #   decode_jwt() is the single decode point that supports zero-downtime
            #   JWT_SECRET_KEY rotation via JWT_PREVIOUS_SECRET_KEY fallback.
            #   See apps/core/jwt_utils.py and docs/runbooks/secrets-rotation.md.
            raw = decode_jwt(
                token,
                options={
                    "require": ["exp", "user_id", "complex_id", "role", "token_type"]
                },
            )
            # WHY blacklist check after decode (not before):
            #   We need the JTI from the decoded payload. Checking before decode
            #   would require a second decode. One decode, one cache lookup.
            # WHY Redis not DB: O(1) lookup, sub-millisecond, no query overhead.
            #   Key pattern: jti:bl:{jti} — auto-expires at token's natural exp.
            if cache.get(f"jti:bl:{raw['jti']}"):
                return None  # Explicitly revoked: logout or rotation replay detected
            return cast(JWTAccessPayload, raw)
        except jwt.InvalidTokenError:
            return None

    @staticmethod
    def _get_user(payload: JWTAccessPayload) -> User | None:
        try:
            # WHY select_related("complex") only — NOT "unit":
            #   complex_id, role, is_profile_complete come from the JWT payload claims.
            #   User.complex is needed for ComplexContextMiddleware fallback.
            #   User.unit is a reverse OneToOne JOIN needed ONLY in GET /auth/me/.
            #   Adding it here pays a JOIN cost on 100% of requests for 1% of endpoints.
            #   MeView re-fetches with select_related("unit") when it needs unit fields.
            #   Source: Google Principal Architect review — "SIGNIFICANT"
            #           § select_related "JOIN on every authenticated request"
            return User.objects.select_related("complex").get(
                id=payload["user_id"], is_active=True
            )
        except User.DoesNotExist:
            return None
