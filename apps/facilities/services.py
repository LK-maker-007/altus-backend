from __future__ import annotations

import json
import zoneinfo
from datetime import date, datetime, time, timedelta
from typing import cast

import structlog
from django.core.cache import cache
from django.db import models
from django.utils import timezone

from apps.bookings.models import Booking, BookingStatus
from apps.facilities.models import Facility
from apps.facilities.schemas import OperatingHours, SlotData

logger = structlog.get_logger(__name__)

_IST = zoneinfo.ZoneInfo("Asia/Kolkata")
_SLOT_CACHE_TTL_SECONDS = 30


class SlotComputeService:
    @staticmethod
    def compute_slots(facility: Facility, target_date: date) -> list[SlotData]:
        """Return slot availability grid. Cached in Redis at 30-second TTL."""
        cache_key = f"facility:{facility.id}:date:{target_date.isoformat()}:slots"
        cached = cache.get(cache_key)
        if cached is not None:
            # json.loads returns Any — cast to list[SlotData] we serialised below.
            return cast(list[SlotData], json.loads(cached))
        slots = SlotComputeService._build_slots(facility, target_date)
        cache.set(cache_key, json.dumps(slots), timeout=_SLOT_CACHE_TTL_SECONDS)
        return slots

    @staticmethod
    def invalidate_slot_cache(facility_id: str, target_date: date) -> None:
        cache_key = f"facility:{facility_id}:date:{target_date.isoformat()}:slots"
        cache.delete(cache_key)

    @staticmethod
    def _build_slots(facility: Facility, target_date: date) -> list[SlotData]:
        # operating_hours is a JSON field — cast to our typed schema.
        hours = cast(OperatingHours, facility.operating_hours)
        if target_date.weekday() not in hours["days"]:
            return []

        slot_duration = timedelta(minutes=int(hours["slot_duration_minutes"]))
        start_dt = datetime.combine(
            target_date, time.fromisoformat(hours["start"]), tzinfo=_IST
        )
        end_dt = datetime.combine(
            target_date, time.fromisoformat(hours["end"]), tzinfo=_IST
        )

        # Single query covering the (facility, slot_start, slot_end, status) index.
        occupied_qs = (
            Booking.unscoped.filter(facility=facility, slot_start__date=target_date)
            .filter(
                models.Q(status=BookingStatus.CONFIRMED)
                | models.Q(status=BookingStatus.HOLD, expires_at__gt=timezone.now())
            )
            .values_list("slot_start", "slot_end")
        )
        occupied: set[tuple[datetime, datetime]] = {(s, e) for s, e in occupied_qs}

        slots: list[SlotData] = []
        current = start_dt
        while current + slot_duration <= end_dt:
            next_slot = current + slot_duration
            slots.append(
                SlotData(
                    slot_start=current.isoformat(),
                    slot_end=next_slot.isoformat(),
                    status=(
                        "unavailable"
                        if (current, next_slot) in occupied
                        else "available"
                    ),
                )
            )
            current = next_slot

        return slots
