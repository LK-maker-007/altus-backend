"""
apps/emergency/views.py

WHY views delegate to EmergencyService (not implement logic directly):
  ADR-010 mandates that all business logic lives in the service layer.
  Views are thin HTTP adapters — they validate auth, call the service,
  and serialise the response. This was refactored from a view that contained
  the caching logic directly. Source: audit §P2 §emergency app violates ADR-010.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

from drf_spectacular.utils import extend_schema
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.emergency.services import EmergencyService
from apps.users.models import User

_AUTH: Sequence[type[BasePermission]] = (IsAuthenticated,)


class EmergencyContactListView(APIView):
    """GET /emergency-contacts/ — list active emergency contacts for the complex.

    No pagination — api-contract §9 explicitly states contact count is bounded.
    Response is served from Redis cache (1-hour TTL). Cache is invalidated by
    EmergencyContactAdmin.save_model and delete_model on any admin change.
    """

    permission_classes = _AUTH

    @extend_schema(
        responses={
            200: {
                "type": "object",
                "properties": {
                    "results": {"type": "array", "items": {"type": "object"}}
                },
            }
        },
        summary="List active emergency contacts for the complex",
        tags=["emergency"],
    )
    def get(self, request: Request) -> Response:
        user = cast(User, request.user)
        complex_id = str(user.complex_id or "")
        data = EmergencyService.get_contacts(complex_id)
        return Response({"results": data})
