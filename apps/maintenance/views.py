from __future__ import annotations

from collections.abc import Sequence
from typing import cast
from uuid import UUID

import structlog
from drf_spectacular.utils import extend_schema
from rest_framework.pagination import CursorPagination
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.maintenance.models import MaintenanceTicket, TicketStatus
from apps.maintenance.serializers import (
    TicketCreateSerializer,
    TicketDetailSerializer,
    TicketReadSerializer,
)
from apps.maintenance.services import MaintenanceService
from apps.users.models import User
from apps.users.permissions import IsResident

logger = structlog.get_logger(__name__)

_RESIDENT: Sequence[type[BasePermission]] = (IsAuthenticated, IsResident)


class _TicketCursorPagination(CursorPagination):

    ordering = "-created_at"


class TicketListCreateView(APIView):

    permission_classes = _RESIDENT

    @extend_schema(
        responses={200: TicketReadSerializer(many=True)},
        summary="List the resident's maintenance tickets",
        tags=["maintenance"],
    )
    def get(self, request: Request) -> Response:
        resident = cast(User, request.user)
        qs = (
            MaintenanceTicket.objects.filter(raised_by=resident)
            .prefetch_related("photos")
            .order_by("-created_at")
        )
        status_filter = request.query_params.get("status")
        if status_filter:
            if status_filter not in TicketStatus.values:
                from rest_framework.exceptions import ValidationError

                raise ValidationError(
                    f"Invalid status. Valid values: {TicketStatus.values}"
                )
            qs = qs.filter(status=status_filter)

        paginator = _TicketCursorPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        serializer = TicketReadSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    @extend_schema(
        request=TicketCreateSerializer,
        responses={201: TicketReadSerializer},
        summary="Submit a new maintenance ticket (multipart/form-data)",
        tags=["maintenance"],
    )
    def post(self, request: Request) -> Response:
        resident = cast(User, request.user)
        serializer = TicketCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        photos = request.FILES.getlist("photos")

        ticket = MaintenanceService.create_ticket(
            resident=resident,
            category=str(d["category"]),
            description=str(d["description"]),
            photos=list(photos),
            client_idempotency_key=d.get("client_idempotency_key"),
            queued_at=d.get("queued_at"),
        )
        return Response(
            TicketReadSerializer(ticket).data,
            status=201,
        )


class TicketDetailView(APIView):

    permission_classes = _RESIDENT

    @extend_schema(
        responses={200: TicketDetailSerializer},
        summary="Get maintenance ticket detail with status history",
        tags=["maintenance"],
    )
    def get(self, request: Request, ticket_id: UUID) -> Response:
        resident = cast(User, request.user)
        ticket = MaintenanceService.get_ticket_detail(
            ticket_id=str(ticket_id),
            resident=resident,
        )
        return Response(TicketDetailSerializer(ticket).data)
