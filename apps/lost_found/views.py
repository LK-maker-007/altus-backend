"""
apps/lost_found/views.py

WHY views delegate to LostFoundService (not implement logic directly):
  ADR-010 mandates that all business logic lives in the service layer.
  Views are thin HTTP adapters — they validate auth, call the service,
  and serialise the response. Refactored from DRF generics.ListCreateAPIView
  where perform_create() contained tenant-scoping logic directly in the view.
  Source: audit §P2 §lost_found app violates ADR-010.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

from drf_spectacular.utils import extend_schema
from rest_framework.pagination import CursorPagination
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.lost_found.serializers import LostFoundReportSerializer
from apps.lost_found.services import LostFoundService
from apps.users.models import User

_AUTH: Sequence[type[BasePermission]] = (IsAuthenticated,)


class _LostFoundCursorPagination(CursorPagination):
    """Cursor pagination for lost & found reports, newest first.

    Explicit ordering prevents the global CursorPagination default field
    "-created" from being applied — the field is "-created_at".
    Same fix as _AnnouncementCursorPagination in community/views.py.
    """

    ordering = "-created_at"


class LostFoundListCreateView(APIView):
    """GET/POST /lost-found/ — list & create lost and found reports.

    Open to all authenticated roles — residents and security can both post.
    Filtered by `type` query param (lost, found). Cursor pagination.
    """

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
            complex_id=str(user.complex_id or ""),
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
