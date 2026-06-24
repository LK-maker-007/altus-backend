from __future__ import annotations

from collections.abc import Sequence
from typing import cast

from drf_spectacular.utils import extend_schema
from rest_framework.pagination import CursorPagination
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.packages.serializers import (
    PackageLogResponseSerializer,
    PackageLogSerializer,
    PackageReadSerializer,
)
from apps.packages.services import PackageService
from apps.users.models import User
from apps.users.permissions import IsResident, IsSecurityGuard

_RESIDENT: Sequence[type[BasePermission]] = (IsAuthenticated, IsResident)
_SECURITY: Sequence[type[BasePermission]] = (IsAuthenticated, IsSecurityGuard)
_ANY_AUTH: Sequence[type[BasePermission]] = (IsAuthenticated,)


class _PackageCursorPagination(CursorPagination):
    ordering = "-created_at"


class PackageListView(APIView):

    permission_classes = _RESIDENT

    @extend_schema(
        responses={200: PackageReadSerializer(many=True)},
        summary="List packages for the resident's unit",
        tags=["packages"],
    )
    def get(self, request: Request) -> Response:
        from apps.packages.models import Package

        resident = cast(User, request.user)
        if resident.unit_id is None:
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("No unit is linked to your account.")
        status_filter = request.query_params.get("status")

        qs = Package.objects.filter(unit_id=resident.unit_id).order_by("-created_at")
        if status_filter:
            qs = qs.filter(status=status_filter)

        paginator = _PackageCursorPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        serializer = PackageReadSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class PackageLogView(APIView):

    permission_classes = _SECURITY

    @extend_schema(
        request=PackageLogSerializer,
        responses={201: PackageLogResponseSerializer},
        summary="Log an incoming package for a unit (security only)",
        tags=["packages"],
    )
    def post(self, request: Request) -> Response:
        guard = cast(User, request.user)
        serializer = PackageLogSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        package = PackageService.log_package(
            security_guard=guard,
            unit_number=str(d["unit_number"]),
            building_block=str(d["building_block"]),
            complex_id=str(guard.complex_id),
            description=str(d["description"]),
            notes=str(d.get("notes") or ""),
        )
        return Response(PackageLogResponseSerializer(package).data, status=201)


class PackageCollectView(APIView):

    permission_classes = _ANY_AUTH

    @extend_schema(
        request=None,
        responses={
            200: {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "status": {"type": "string"},
                    "collected_at": {"type": "string", "format": "date-time"},
                },
            }
        },
        summary="Mark a package as collected",
        tags=["packages"],
    )
    def post(self, request: Request, package_id: str) -> Response:
        collector = cast(User, request.user)
        package = PackageService.mark_collected(
            package_id=package_id,
            complex_id=str(collector.complex_id),
            collector=collector,
        )
        return Response(
            {
                "id": str(package.id),
                "status": package.status,
                "collected_at": package.collected_at,
            }
        )
