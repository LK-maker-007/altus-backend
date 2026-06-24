from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import pytest
from django.utils import timezone
from freezegun import freeze_time

from apps.bookings.models import BookingStatus
from apps.facilities.services import SlotComputeService
from tests.factories.booking_factory import BookingFactory
from tests.factories.facility_factory import FacilityFactory


@pytest.mark.django_db
class TestComputeSlots:

    def test_returns_correct_slot_count_for_full_day(self, complex_a: Any) -> None:
        facility = FacilityFactory(
            complex=complex_a,
            operating_hours={
                "start": "06:00",
                "end": "22:00",
                "slot_duration_minutes": 60,
                "days": [0, 1, 2, 3, 4, 5, 6],
            },
        )

        slots = SlotComputeService.compute_slots(facility, date(2026, 4, 23))

        assert len(slots) == 16
        assert "06:00" in slots[0]["slot_start"]
        assert "22:00" in slots[-1]["slot_end"]

    def test_closed_day_returns_empty_list(self, complex_a: Any) -> None:
        facility = FacilityFactory(
            complex=complex_a,
            operating_hours={
                "start": "06:00",
                "end": "22:00",
                "slot_duration_minutes": 60,
                "days": [0, 1, 2, 3, 4],
            },
        )

        slots = SlotComputeService.compute_slots(facility, date(2026, 4, 26))

        assert slots == []

    def test_confirmed_booking_marks_slot_unavailable(self, complex_a: Any) -> None:
        facility = FacilityFactory(
            complex=complex_a,
            operating_hours={
                "start": "06:00",
                "end": "22:00",
                "slot_duration_minutes": 60,
                "days": [0, 1, 2, 3, 4, 5, 6],
            },
        )
        from apps.users.models import UserRole
        from tests.factories.user_factory import UserFactory

        resident = UserFactory(complex=complex_a, role=UserRole.RESIDENT)

        from zoneinfo import ZoneInfo

        from django.utils.timezone import make_aware

        ist = ZoneInfo("Asia/Kolkata")
        slot_start = make_aware(datetime(2026, 4, 23, 7, 0), ist)
        slot_end = make_aware(datetime(2026, 4, 23, 8, 0), ist)

        BookingFactory(
            complex=complex_a,
            facility=facility,
            resident=resident,
            slot_start=slot_start,
            slot_end=slot_end,
            status=BookingStatus.CONFIRMED,
            expires_at=None,
        )

        slots = SlotComputeService.compute_slots(facility, date(2026, 4, 23))
        slot_7am = next(s for s in slots if "T07:00" in s["slot_start"])
        assert slot_7am["status"] == "unavailable"

    def test_expired_hold_does_not_block_slot(self, complex_a: Any) -> None:
        facility = FacilityFactory(
            complex=complex_a,
            operating_hours={
                "start": "06:00",
                "end": "22:00",
                "slot_duration_minutes": 60,
                "days": [0, 1, 2, 3, 4, 5, 6],
            },
        )
        from apps.users.models import UserRole
        from tests.factories.user_factory import UserFactory

        resident = UserFactory(complex=complex_a, role=UserRole.RESIDENT)

        from zoneinfo import ZoneInfo

        from django.utils.timezone import make_aware

        ist = ZoneInfo("Asia/Kolkata")
        slot_start = make_aware(datetime(2026, 4, 23, 7, 0), ist)
        slot_end = make_aware(datetime(2026, 4, 23, 8, 0), ist)

        with freeze_time("2026-04-22 10:00:00"):
            BookingFactory(
                complex=complex_a,
                facility=facility,
                resident=resident,
                slot_start=slot_start,
                slot_end=slot_end,
                status=BookingStatus.HOLD,
                expires_at=timezone.now() + timedelta(minutes=5),
            )

        with freeze_time("2026-04-22 10:06:00"):
            slots = SlotComputeService.compute_slots(facility, date(2026, 4, 23))

        slot_7am = next(s for s in slots if "T07:00" in s["slot_start"])
        assert slot_7am["status"] == "available"
