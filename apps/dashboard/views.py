from __future__ import annotations

from collections.abc import Sequence
from typing import cast

from django.utils import timezone
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
    """GET /dashboard/ — aggregated home screen for the resident (api-contract §11).

    Returns:
    - upcoming_bookings: next 2 confirmed bookings after now, soonest first.
    - recent_announcements: latest 3 active announcements with 120-char preview.
    - open_ticket_count: count of resident's open/in-progress maintenance tickets.

    3 queries total. No caching — response is resident-specific.
    """

    permission_classes = _RESIDENT

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
            # WHY select_related("created_by"):
            #   AnnouncementDashboardSerializer accesses created_by.name.
            #   Without this, each announcement fires one extra query — N+1 on
            #   the hottest read path in the system. AnnouncementListView already
            #   does this correctly; the dashboard was the only missing callsite.
            #   Source: audit §P1 §Dashboard N+1.
            .select_related("created_by").order_by("-created_at")[:3]
        )

        open_ticket_count = MaintenanceTicket.objects.filter(
            raised_by=resident,
            # CRIT-001: use enum values — never hardcoded strings
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
