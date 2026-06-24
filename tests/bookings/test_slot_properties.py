from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

_utc_dt = st.datetimes(
    min_value=datetime(2026, 5, 1),
    max_value=datetime(2026, 12, 31),
    timezones=st.just(UTC),
)

_positive_duration = st.integers(min_value=30, max_value=480)


def _slots_overlap(
    a_start: datetime,
    a_end: datetime,
    b_start: datetime,
    b_end: datetime,
) -> bool:
    return a_start < b_end and b_start < a_end


class TestSlotOverlapPredicate:

    @given(
        start_a=_utc_dt,
        dur_a=_positive_duration,
        overlap_offset=st.integers(min_value=1, max_value=60),
    )
    @settings(max_examples=200, deadline=None)
    def test_partial_overlap_always_detected(
        self,
        start_a: datetime,
        dur_a: int,
        overlap_offset: int,
    ) -> None:
        end_a = start_a + timedelta(minutes=dur_a)
        start_b = start_a + timedelta(minutes=overlap_offset)
        end_b = start_b + timedelta(minutes=60)

        from hypothesis import assume

        assume(start_b < end_a)

        assert _slots_overlap(
            start_a, end_a, start_b, end_b
        ), f"Overlap not detected: A=[{start_a}, {end_a}), B=[{start_b}, {end_b})"

    @given(
        start_a=_utc_dt,
        dur_a=_positive_duration,
    )
    @settings(max_examples=200, deadline=None)
    def test_adjacent_slots_never_overlap(
        self,
        start_a: datetime,
        dur_a: int,
    ) -> None:
        end_a = start_a + timedelta(minutes=dur_a)
        start_b = end_a
        end_b = start_b + timedelta(minutes=60)

        assert not _slots_overlap(
            start_a, end_a, start_b, end_b
        ), f"Adjacent slots falsely flagged as overlap: A ends={end_a}, B starts={start_b}"

    @given(
        start_a=_utc_dt,
        dur_a=_positive_duration,
        gap_minutes=st.integers(min_value=1, max_value=240),
    )
    @settings(max_examples=200, deadline=None)
    def test_non_overlapping_future_slot_never_conflicts(
        self,
        start_a: datetime,
        dur_a: int,
        gap_minutes: int,
    ) -> None:
        end_a = start_a + timedelta(minutes=dur_a)
        start_b = end_a + timedelta(minutes=gap_minutes)
        end_b = start_b + timedelta(minutes=60)

        assert not _slots_overlap(
            start_a, end_a, start_b, end_b
        ), f"Non-overlapping slots falsely flagged: A ends={end_a}, B starts={start_b}"

    @given(
        start_a=_utc_dt,
        dur_a=_positive_duration,
    )
    @settings(max_examples=200, deadline=None)
    def test_identical_slots_always_overlap(
        self,
        start_a: datetime,
        dur_a: int,
    ) -> None:
        end_a = start_a + timedelta(minutes=dur_a)
        assert _slots_overlap(
            start_a, end_a, start_a, end_a
        ), "Identical slots must always overlap"


@pytest.mark.django_db
class TestExpiredHoldNotInFilter:

    def test_expired_hold_excluded_from_active_filter(
        self, complex_a: Any, facility: Any, resident: Any
    ) -> None:
        from django.utils import timezone

        from apps.bookings.models import Booking, BookingStatus
        from tests.factories.booking_factory import BookingFactory

        slot_start = timezone.now() + timedelta(days=2)
        slot_end = slot_start + timedelta(hours=2)

        BookingFactory(
            complex=complex_a,
            facility=facility,
            resident=resident,
            status=BookingStatus.HOLD,
            expires_at=timezone.now() - timedelta(minutes=5),
            slot_start=slot_start,
            slot_end=slot_end,
        )

        active_holds = Booking.unscoped.filter(
            facility=facility,
            slot_start__lt=slot_end,
            slot_end__gt=slot_start,
            status=BookingStatus.HOLD,
            expires_at__gt=timezone.now(),
        )
        assert (
            active_holds.count() == 0
        ), "Expired hold must not appear in the active hold filter"
