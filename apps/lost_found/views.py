from __future__ import annotations

from collections.abc import Sequence
from typing import cast

from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import PermissionDenied
from rest_framework.pagination import CursorPagination
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.lost_found.serializers import LostFoundReportSerializer
from apps.lost_found.services import LostFoundService
from apps.users.models import User

_AUTH: Sequence[type[BasePermission]] = (IsAuthenticated,)


def _require_complex_id(user: User) -> str:
    if user.complex_id is None:
        raise PermissionDenied("This endpoint is scoped to a complex.")
    return str(user.complex_id)


class _LostFoundCursorPagination(CursorPagination):

    ordering = "-created_at"


class LostFoundListCreateView(APIView):

    permission_classes = _AUTH

    @extend_schema(
        responses={200: LostFoundReportSerializer(many=True)},
        summary="List lost & found reports for the complex",
        tags=["lost-found"],
    )
    def get(self, request: Request) -> Response:
        user = cast(User, request.user)
        report_type = request.query_params.get("type")

        qs = LostFoundService.list_reports(
            complex_id=_require_complex_id(user),
            report_type=report_type,
        )

        paginator = _LostFoundCursorPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        serializer = LostFoundReportSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    @extend_schema(
        request=LostFoundReportSerializer,
        responses={201: LostFoundReportSerializer},
        summary="Create a lost or found report",
        tags=["lost-found"],
    )
    def post(self, request: Request) -> Response:
        user = cast(User, request.user)
        _require_complex_id(user)
        serializer = LostFoundReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        report = LostFoundService.create_report(
            reporter=user,
            data=serializer.validated_data,
        )

        return Response(
            LostFoundReportSerializer(report).data,
            status=201,
        )
