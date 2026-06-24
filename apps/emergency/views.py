from __future__ import annotations

from collections.abc import Sequence
from typing import cast

from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.emergency.services import EmergencyService
from apps.users.models import User

_AUTH: Sequence[type[BasePermission]] = (IsAuthenticated,)


def _require_complex_id(user: User) -> str:
    if user.complex_id is None:
        raise PermissionDenied("This endpoint is scoped to a complex.")
    return str(user.complex_id)


class EmergencyContactListView(APIView):

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
        complex_id = _require_complex_id(user)
        data = EmergencyService.get_contacts(complex_id)
        return Response({"results": data})
