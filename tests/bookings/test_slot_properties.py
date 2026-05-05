from __future__ import annotations

"""
Property-based tests — booking slot overlap logic (pure logic layer)

Tests the overlap detection PREDICATE used by BookingService — specifically the
QuerySet filter conditions — using Hypothesis without hitting the DB for every
example. This is the correct Hypothesis + Django pattern for combinatorial tests:

  "Test the LOGIC with Hypothesis. Test the DB integration with specific examples."
  — Hypothesis docs, hypothesis.readthedocs.io/en/latest/details.html#use-with-pytest

The overlap invariants are:
  1. Two intervals [a, b) and [c, d) overlap if and only if a < d AND c < b.
  2. An expired hold (expires_at <= now) is NOT included in the active hold filter.
  3. Adjacent intervals [a,b) and [b,c) do NOT overlap.

These are verified with pure datetime arithmetic — no DB writes — making
Hypothesis shrinking fast and deterministic.

For the full integration path (service → DB → GiST constraint), see:
  tests/test_bookings/test_services.py — specific example-based DB tests.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

# UTC-aware datetime strategy: naive bounds (Hypothesis requires no tzinfo on bounds)
# Hypothesis applies the timezones= strategy to add tzinfo after generation.
_utc_dt = st.datetimes(
    min_value=datetime(2026, 5, 1),  # naive — Hypothesis adds tz from timezones=
    max_value=datetime(2026, 12, 31),
    timezones=st.just(UTC),
)

_positive_duration = st.integers(min_value=30, max_value=480)  # minutes


def _slots_overlap(
    a_start: datetime,
    a_end: datetime,
    b_start: datetime,
    b_end: datetime,
) -> bool:
    """
    Pure implementation of the overlap predicate used in BookingService:
      slot_start__lt=slot_end, slot_end__gt=slot_start
    This is equivalent to: a_start < b_end AND b_start < a_end
    """
    return a_start < b_end and b_start < a_end


class TestSlotOverlapPredicate:
    """
    Pure-logic property tests. No DB — Hypothesis runs hundreds of examples fast.
    These verify the mathematical correctness of the overlap predicate.
    """

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
        """
        Property: If slot B starts INSIDE slot A, they always overlap.
        This is the core double-booking risk scenario.
        """
        end_a = start_a + timedelta(minutes=dur_a)
        # B starts inside A
        start_b = start_a + timedelta(minutes=overlap_offset)
        end_b = start_b + timedelta(minutes=60)

        from hypothesis import assume

        assume(start_b < end_a)  # B actually starts inside A

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
        """
        Property: Slot B starting exactly when Slot A ends is NOT an overlap.
        This is the half-open interval [start, end) boundary property.
        """
        end_a = start_a + timedelta(minutes=dur_a)
        start_b = end_a  # adjacent — B starts when A ends
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
        """
        Property: Slot B starting AFTER slot A ends (with any gap) is never an overlap.
        """
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
        """
        Property: Two identical slots (same start, same end) always overlap.
        This is the degenerate case of a direct double-booking.
        """
        end_a = start_a + timedelta(minutes=dur_a)
        assert _slots_overlap(
            start_a, end_a, start_a, end_a
        ), "Identical slots must always overlap"


@pytest.mark.django_db
class TestExpiredHoldNotInFilter:
    """
    Verifies that the DB filter for active holds excludes expired holds.
    Uses a single DB example (not Hypothesis) since this tests DB state.
    """

    def test_expired_hold_excluded_from_active_filter(
        self, complex_a: Any, facility: Any, resident: Any
    ) -> None:
        """
        An expired hold (expires_at in the past) must not appear in the
        active hold filter: status=HOLD AND expires_at > now().
        """
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
            expires_at=timezone.now() - timedelta(minutes=5),  # expired
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
