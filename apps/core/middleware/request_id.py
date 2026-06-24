from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import cast

from django.http import HttpRequest, HttpResponse

from apps.core.http import AuthenticatedRequest


class RequestIdMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        request_id = str(uuid.uuid4())
        auth_request = cast(AuthenticatedRequest, request)
        auth_request.request_id = request_id
        response = self.get_response(auth_request)
        response["X-Request-Id"] = request_id
        return response
