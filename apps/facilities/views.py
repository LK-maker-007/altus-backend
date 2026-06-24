from __future__ import annotations

import json
import time
import uuid
from collections.abc import Generator, Sequence
from datetime import date
from typing import cast

import structlog
from django.core.cache import cache
from django.http import StreamingHttpResponse
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.bookings.models import Booking
from apps.core.middleware.jwt_auth import _SSE_TICKET_PREFIX, _SSE_TICKET_TTL
from apps.facilities.exceptions import FacilityNotFoundError
from apps.facilities.models import Facility
from apps.facilities.serializers import FacilityReadSerializer
from apps.facilities.services import SlotComputeService
from apps.users.models import User
from apps.users.permissions import IsResidentOrAdmin

logger = structlog.get_logger(__name__)

_RESIDENT_OR_ADMIN: Sequence[type[BasePermission]] = (
    IsAuthenticated,
    IsResidentOrAdmin,
)

_MAX_BOOKING_WINDOW_DAYS = 7
_MAX_SSE_ITERATIONS = 12


def _parse_and_validate_date(date_str: str) -> date:
    if not date_str:
        raise ValidationError("date query parameter is required (YYYY-MM-DD).")
    try:
        target_date = date.fromisoformat(date_str)
    except ValueError as exc:
        raise ValidationError("date must be in YYYY-MM-DD format.") from exc
    today = date.today()
    if target_date < today:
        raise ValidationError("Cannot view slots for a date in the past.")
    if (target_date - today).days > _MAX_BOOKING_WINDOW_DAYS:
        raise ValidationError(
            f"Slot is outside the {_MAX_BOOKING_WINDOW_DAYS}-day booking window."
        )
    return target_date


class FacilityListView(APIView):

    permission_classes = _RESIDENT_OR_ADMIN

    @extend_schema(
        responses={200: FacilityReadSerializer(many=True)},
        summary="List active facilities for the resident's complex",
        tags=["facilities"],
    )
    def get(self, request: Request) -> Response:
        qs = Facility.objects.filter(is_active=True).order_by("category", "name")
        category = request.query_params.get("category")
        if category:
            qs = qs.filter(category=category)
        return Response({"results": FacilityReadSerializer(qs, many=True).data})


class FacilityDetailView(APIView):

    permission_classes = _RESIDENT_OR_ADMIN

    @extend_schema(
        responses={200: FacilityReadSerializer},
        summary="Get a single facility detail",
        tags=["facilities"],
    )
    def get(self, request: Request, facility_id: str) -> Response:
        try:
            facility = Facility.objects.get(id=facility_id, is_active=True)
        except Facility.DoesNotExist as exc:
            raise FacilityNotFoundError() from exc
        return Response(FacilityReadSerializer(facility).data)


class FacilitySlotsView(APIView):

    permission_classes = _RESIDENT_OR_ADMIN

    @extend_schema(
        responses={
            200: {
                "type": "object",
                "properties": {
                    "facility_id": {"type": "string"},
                    "date": {"type": "string"},
                    "slots": {"type": "array", "items": {"type": "object"}},
                },
            }
        },
        summary="Get computed slot grid for a facility date",
        tags=["facilities"],
    )
    def get(self, request: Request, facility_id: str) -> Response:
        target_date = _parse_and_validate_date(request.query_params.get("date", ""))
        try:
            facility = Facility.objects.get(id=facility_id, is_active=True)
        except Facility.DoesNotExist as exc:
            raise FacilityNotFoundError() from exc
        slots = SlotComputeService.compute_slots(facility, target_date)
        return Response(
            {
                "facility_id": str(facility.id),
                "date": target_date.isoformat(),
                "slots": slots,
            }
        )


class SseTicketIssueView(APIView):

    permission_classes: Sequence[type[BasePermission]] = (IsAuthenticated,)

    @extend_schema(
        request=None,
        responses={
            201: {
                "type": "object",
                "properties": {"ticket": {"type": "string", "format": "uuid"}},
            }
        },
        summary="Issue a single-use SSE auth ticket (60s TTL)",
        tags=["facilities"],
    )
    def post(self, request: Request) -> Response:
        user = cast(User, request.user)
        ticket = str(uuid.uuid4())
        cache.set(
            f"{_SSE_TICKET_PREFIX}{ticket}",
            {
                "user_id": str(user.id),
                "complex_id": str(user.complex_id or ""),
            },
            timeout=_SSE_TICKET_TTL,
        )
        logger.info(
            "sse_ticket_issued",
            user_id=str(user.id),
            complex_id=str(user.complex_id or ""),
        )
        return Response({"ticket": ticket}, status=status.HTTP_201_CREATED)


class FacilitySlotStreamView(APIView):

    permission_classes = _RESIDENT_OR_ADMIN

    @extend_schema(
        exclude=True,
    )
    def get(
        self, request: Request, facility_id: str
    ) -> StreamingHttpResponse | Response:
        complex_id = str(getattr(request, "complex_id", ""))
        target_date = _parse_and_validate_date(request.query_params.get("date", ""))

        facility = Facility.unscoped.filter(
            id=facility_id, complex_id=complex_id, is_active=True
        ).first()
        if not facility:
            raise FacilityNotFoundError()

        response = StreamingHttpResponse(
            _slot_event_stream(facility, target_date, complex_id),
            content_type="text/event-stream",
        )
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response


def _slot_event_stream(
    facility: Facility,
    target_date: date,
    complex_id: str,
) -> Generator[str]:
    from django.utils import timezone as tz

    slots = SlotComputeService.compute_slots(facility, target_date)
    payload = json.dumps(
        {
            "facility_id": str(facility.id),
            "date": target_date.isoformat(),
            "slots": slots,
        }
    )
    yield f"event: availability\ndata: {payload}\n\n"

    last_check = tz.now()
    for _ in range(_MAX_SSE_ITERATIONS):
        time.sleep(25)
        yield "event: ping\ndata: {}\n\n"

        changed = Booking.unscoped.filter(
            facility_id=facility.id,
            complex_id=complex_id,
            slot_start__date=target_date,
            updated_at__gte=last_check,
        ).exists()
        last_check = tz.now()

        if changed:
            slots = SlotComputeService.compute_slots(facility, target_date)
            payload = json.dumps(
                {
                    "facility_id": str(facility.id),
                    "date": target_date.isoformat(),
                    "slots": slots,
                }
            )
            yield f"event: availability\ndata: {payload}\n\n"

    yield 'event: stream-end\ndata: {"reason": "reconnect"}\n\n'
