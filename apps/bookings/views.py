from __future__ import annotations

from collections.abc import Sequence
from typing import cast
from uuid import UUID

import structlog
from django.db import models
from rest_framework.pagination import CursorPagination
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle
from rest_framework.views import APIView

from apps.bookings.exceptions import HoldNotFoundError
from apps.bookings.models import Booking
from apps.bookings.serializers import (
    BookingCancelSerializer,
    BookingHoldResponseSerializer,
    BookingHoldSerializer,
    BookingReadSerializer,
)
from apps.bookings.services import BookingService
from apps.core.throttles import BookingHoldRateThrottle
from apps.users.models import User
from apps.users.permissions import IsResident

logger = structlog.get_logger(__name__)

# Tuples: immutable → no RUF012; Sequence satisfies DRF stubs
_RESIDENT: Sequence[type[BasePermission]] = (IsAuthenticated, IsResident)
_AUTH: Sequence[type[BasePermission]] = (IsAuthenticated,)
_BOOKING_HOLD_THROTTLES: Sequence[type[BaseThrottle]] = (BookingHoldRateThrottle,)


def _get_resident_bookings(resident: User) -> models.QuerySet[Booking]:
    return (
        Booking.objects.select_related("facility")
        .filter(resident=resident)
        .order_by("-slot_start")
    )


class BookingHoldView(APIView):
    """POST /bookings/hold/ — create a 5-minute hold.

    WHY BookingHoldRateThrottle (10/minute per resident):
      Without a throttle, an automated client can hammer this endpoint to hold
      every available slot across all facilities, denying access to all other
      residents. The GiST exclusion constraint is the data-integrity backstop;
      this throttle is the abuse-prevention layer.
      Source: audit §MEDIUM §BookingHoldView no throttle.
    """

    permission_classes = _RESIDENT
    throttle_classes = _BOOKING_HOLD_THROTTLES

    def post(self, request: Request) -> Response:
        serializer = BookingHoldSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        booking = BookingService.create_hold(
            resident=cast(User, request.user),
            facility_id=data["facility_id"],
            slot_start=data["slot_start"],
            slot_end=data["slot_end"],
        )
        return Response(BookingHoldResponseSerializer(booking).data, status=201)


class BookingConfirmView(APIView):
    """POST /bookings/{id}/confirm/ — convert hold to confirmed."""

    permission_classes = _RESIDENT

    def post(self, request: Request, booking_id: UUID) -> Response:
        booking = BookingService.confirm_hold(
            booking_id=booking_id,
            resident=cast(User, request.user),
        )
        return Response(BookingHoldResponseSerializer(booking).data)


class BookingCancelView(APIView):
    """POST /bookings/{id}/cancel/ — cancel hold or confirmed booking.
    Ownership enforced in BookingService; all authenticated roles allowed here.
    """

    permission_classes = _AUTH

    def post(self, request: Request, booking_id: UUID) -> Response:
        serializer = BookingCancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        actor = cast(User, request.user)
        booking = BookingService.cancel_booking(
            booking_id=booking_id,
            actor=actor,
            complex_id=str(actor.complex_id),
            reason=serializer.validated_data.get("reason", ""),
        )
        return Response(
            {
                "id": str(booking.id),
                "status": booking.status,
                "cancelled_at": booking.cancelled_at,
                "cancellation_source": booking.cancellation_source,
            }
        )


class BookingListView(APIView):
    """GET /bookings/ — list authenticated resident's bookings with cursor pagination.

    WHY CursorPagination not PageNumberPagination:
      Cursor is stable under concurrent writes (new bookings don't shift pages).
      A resident creating a new booking while paginating wouldn't see duplicates
      or miss items. PageNumber pagination is unstable under live data.
      Source: DRF docs; DEFAULT_PAGINATION_CLASS = CursorPagination in base settings.

    WHY ordering="-slot_start" (not created_at):
      Residents expect bookings sorted by appointment time, not submission order.
      Most recent upcoming booking appears first.
    """

    permission_classes = _RESIDENT

    def get(self, request: Request) -> Response:
        qs = _get_resident_bookings(cast(User, request.user))
        paginator = CursorPagination()
        paginator.ordering = "-slot_start"
        page = paginator.paginate_queryset(qs, request, view=self)
        serializer = BookingReadSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class BookingDetailView(APIView):
    """GET /bookings/{id}/ — single booking detail."""

    permission_classes = _RESIDENT

    def get(self, request: Request, booking_id: UUID) -> Response:
        try:
            booking = Booking.objects.select_related("facility").get(
                id=booking_id,
                resident=cast(User, request.user),
            )
        except Booking.DoesNotExist as exc:
            raise HoldNotFoundError() from exc
        return Response(BookingReadSerializer(booking).data)
