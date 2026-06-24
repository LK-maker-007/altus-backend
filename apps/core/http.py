from __future__ import annotations

from django.http import HttpRequest

from apps.users.models import User


class AuthenticatedRequest(HttpRequest):

    user: User
    complex_id: str | None
    request_id: str
    access_jti: str | None
    access_exp: int | None
