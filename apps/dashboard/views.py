from __future__ import annotations

from collections.abc import Sequence
from typing import cast

from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.bookings.models import Booking, BookingStatus
from apps.bookings.serializers import BookingReadSerializer
from apps.community.models import Announcement
from apps.community.serializers import AnnouncementDashboardSerializer
from apps.maintenance.models import MaintenanceTicket, TicketStatus
from apps.users.models import User
from apps.users.permissions import IsResident

_RESIDENT: Sequence[type[BasePermission]] = (IsAuthenticated, IsResident)


class DashboardView(APIView):

    permission_classes = _RESIDENT

    @extend_schema(
        responses={
            200: {
                "type": "object",
                "properties": {
                    "upcoming_bookings": {"type": "array", "items": {"type": "object"}},
                    "recent_announcements": {
                        "type": "array",
                        "items": {"type": "object"},
                    },
                    "open_ticket_count": {"type": "integer"},
                },
            }
        },
        summary="Resident home screen aggregation",
        tags=["dashboard"],
    )
    def get(self, request: Request) -> Response:
        resident = cast(User, request.user)
        now = timezone.now()

        upcoming_bookings = (
            Booking.objects.filter(
                resident=resident,
                status=BookingStatus.CONFIRMED,
                slot_start__gt=now,
            )
            .select_related("facility")
            .order_by("slot_start")[:2]
        )

        recent_announcements = (
            Announcement.objects.filter(is_active=True)
            .select_related("created_by")
            .order_by("-created_at")[:3]
        )

        open_ticket_count = MaintenanceTicket.objects.filter(
            raised_by=resident,
            status__in=[TicketStatus.OPEN, TicketStatus.IN_PROGRESS],
        ).count()

        return Response(
            {
                "upcoming_bookings": BookingReadSerializer(
                    upcoming_bookings, many=True
                ).data,
                "recent_announcements": AnnouncementDashboardSerializer(
                    recent_announcements, many=True
                ).data,
                "open_ticket_count": open_ticket_count,
            }
        )
