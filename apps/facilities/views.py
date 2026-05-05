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

# Tuples: immutable → no RUF012; Sequence[type[BasePermission]] satisfies DRF stubs
_RESIDENT_OR_ADMIN: Sequence[type[BasePermission]] = (
    IsAuthenticated,
    IsResidentOrAdmin,
)

_MAX_BOOKING_WINDOW_DAYS = 7
# WHY _MAX_SSE_ITERATIONS (SSE thread lifetime limit):
#   Each SSE client occupies one gthread worker thread for the connection lifetime.
#   Without a max iteration, a thread is held until the TCP connection drops —
#   which could be hours (keep-alive, mobile app backgrounded). With 5 workers x
#   4 threads = 20 capacity, 20 idle clients with open SSE connections exhaust
#   all threads. 12 iterations x 25s = 5 minutes max. The client receives a
#   stream-end signal and reconnects automatically via EventSource retry logic.
#   Source: MDN EventSource §reconnection; audit §Critical §SSE.
_MAX_SSE_ITERATIONS = 12  # 12 x 25 s = 5-minute max connection lifetime


def _parse_and_validate_date(date_str: str) -> date:
    """Parse and validate the ?date= query param. Raises ValidationError on failure."""
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
    """GET /facilities/ — list all active facilities for the resident's complex."""

    permission_classes = _RESIDENT_OR_ADMIN

    def get(self, request: Request) -> Response:
        qs = Facility.objects.filter(is_active=True).order_by("category", "name")
        category = request.query_params.get("category")
        if category:
            qs = qs.filter(category=category)
        return Response({"results": FacilityReadSerializer(qs, many=True).data})


class FacilityDetailView(APIView):
    """GET /facilities/{id}/ — single facility detail."""

    permission_classes = _RESIDENT_OR_ADMIN

    def get(self, request: Request, facility_id: str) -> Response:
        try:
            facility = Facility.objects.get(id=facility_id, is_active=True)
        except Facility.DoesNotExist as exc:
            raise FacilityNotFoundError() from exc
        return Response(FacilityReadSerializer(facility).data)


class FacilitySlotsView(APIView):
    """GET /facilities/{id}/slots/?date=YYYY-MM-DD — computed slot grid.
    Cached in Redis at 30-second TTL per api-contract §3.
    """

    permission_classes = _RESIDENT_OR_ADMIN

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
    """POST /facilities/sse-ticket/

    Issues a 60-second, single-use SSE authentication ticket.

    WHY this exists (the SSE auth problem):
      The native EventSource API cannot set custom headers (e.g.
      Authorization: Bearer). Passing a JWT in ?token= exposes it in server
      logs, nginx access logs, browser history, and Referer headers permanently.
      The ticket exchange pattern solves this:

        1. Client POSTs here with their normal Authorization: Bearer JWT.
        2. Server creates a 60s single-use UUID ticket in Redis.
        3. Client opens SSE stream with ?ticket=<uuid>.
        4. JWTAuthMiddleware burns the ticket and sets request.user.
        5. Even if ?ticket=... appears in a log, it is already consumed.

    Ticket TTL: 60 seconds — enough to open an EventSource connection on a
    mobile network; harmless if captured in a log after expiry.

    Source: 2026 SSE auth best practice; audit §P0 §SSE Token in Query Param.
    """

    permission_classes: Sequence[type[BasePermission]] = (IsAuthenticated,)

    def post(self, request: Request) -> Response:
        user = cast(User, request.user)
        ticket = str(uuid.uuid4())
        cache.set(
            f"{_SSE_TICKET_PREFIX}{ticket}",
            {
                "user_id": str(user.id),
                # WHY str(complex_id or ""): Redis serialisation treats None as
                # the string 'None'. An empty string is safe for downstream checks.
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
    """GET /facilities/{id}/slots/stream/?date=YYYY-MM-DD&ticket=<uuid>

    SSE stream for real-time slot availability updates.

    Auth flow (ticket exchange):
      EventSource cannot set Authorization headers. Clients must first POST
      /facilities/sse-ticket/ to exchange their JWT for a 60s single-use
      ticket, then pass ?ticket=<uuid> here. JWTAuthMiddleware resolves the
      ticket to request.user and burns it on first use.

      The ?token=<jwt> pattern described in earlier versions of this docstring
      was INCORRECT — JWTAuthMiddleware never read ?token=. Ticket exchange
      is the correct and secure implementation.

    Source: audit §P0 §SSE Token in Query Param; 2026 SSE auth best practice.
    """

    permission_classes = _RESIDENT_OR_ADMIN

    def get(
        self, request: Request, facility_id: str
    ) -> StreamingHttpResponse | Response:
        # Capture complex_id before entering the generator — RLS middleware
        # does not run inside StreamingHttpResponse iteration.
        complex_id = str(getattr(request, "complex_id", ""))
        target_date = _parse_and_validate_date(request.query_params.get("date", ""))

        # Must use unscoped manager here — RLS is not active in the generator.
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
        response["X-Accel-Buffering"] = "no"  # Nginx must not buffer SSE chunks
        return response


def _slot_event_stream(
    facility: Facility,
    target_date: date,
    complex_id: str,
) -> Generator[str]:
    """SSE generator. Yields initial availability, then diffs on booking changes.
    Must be module-level — Django iterates this outside the request lifecycle.
    """
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

        # Unscoped manager with explicit filters — RLS is not active here.
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

    # Stream closed after _MAX_SSE_ITERATIONS. The EventSource client will
    # automatically reconnect (default retry: 3s). Reconnection fetches a fresh
    # slot state, so no stale data is displayed during the reconnect window.
    yield 'event: stream-end\ndata: {"reason": "reconnect"}\n\n'
