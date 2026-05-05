from __future__ import annotations

"""
Booking concurrency and business rule tests — hold, confirm, cancel, concurrency.

Coverage target: 95% of apps/bookings/services.py (testing-strategy.md §12).

Verified service signatures (2026-04-23):
  BookingService.create_hold(resident, facility_id: UUID, slot_start, slot_end)
  BookingService.confirm_hold(booking_id: UUID, resident)
  BookingService.cancel_booking(booking_id: UUID, actor, complex_id: str, reason="")

  NOTE: create_hold takes facility_id (UUID), NOT the Facility object.
  All calls must use facility.id, not facility.

CRITICAL: Concurrency tests MUST use @pytest.mark.django_db(transaction=True).
Without it, pytest-django wraps tests in a savepoint — two threads cannot
acquire real row-level locks, so select_for_update(nowait=True) tests
silently pass without actually testing concurrency.
"""

import threading
from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone
from freezegun import freeze_time

from apps.bookings.exceptions import (
    BookingLimitReachedError,
    BookingPermissionError,
    HoldExpiredError,
    HoldNotFoundError,
    SlotUnavailableError,
)
from apps.bookings.models import Booking, BookingStatus
from apps.bookings.services import BookingService
from apps.facilities.exceptions import FacilityNotFoundError
from tests.factories.booking_factory import BookingFactory
from tests.factories.facility_factory import FacilityFactory


@pytest.mark.django_db
class TestHoldCreation:
    """US-008 — Slot hold creation and quota enforcement."""

    def test_create_hold_returns_hold_status(
        self, facility: Any, resident: Any
    ) -> None:
        """Happy path — create_hold returns a HOLD booking with a non-null expires_at."""
        slot_start = timezone.now().replace(
            hour=10, minute=0, second=0, microsecond=0
        ) + timedelta(days=1)
        slot_end = slot_start + timedelta(hours=1)

        # create_hold takes facility.id (UUID), not the facility object
        booking = BookingService.create_hold(
            resident, facility.id, slot_start, slot_end
        )

        assert booking.status == BookingStatus.HOLD
        assert booking.expires_at is not None
        assert booking.expires_at > timezone.now()

    def test_inactive_facility_raises_not_found(
        self, complex_a: Any, resident: Any
    ) -> None:
        """An inactive facility must raise FacilityNotFoundError — not a silent failure."""
        inactive = FacilityFactory(complex=complex_a, is_active=False)
        slot_start = timezone.now() + timedelta(days=1, hours=10)

        with pytest.raises(FacilityNotFoundError):
            BookingService.create_hold(
                resident, inactive.id, slot_start, slot_start + timedelta(hours=1)
            )

    def test_booking_limit_per_category_enforced(
        self, complex_a: Any, facility: Any, resident: Any
    ) -> None:
        """2 confirmed bookings in same category → third attempt raises BookingLimitReachedError."""
        slot_1 = timezone.now().replace(
            hour=8, minute=0, second=0, microsecond=0
        ) + timedelta(days=1)
        for i in range(2):
            s = slot_1 + timedelta(hours=i)
            BookingFactory(
                complex=complex_a,
                facility=facility,
                resident=resident,
                status=BookingStatus.CONFIRMED,
                slot_start=s,
                slot_end=s + timedelta(hours=1),
                expires_at=None,
            )

        next_slot = slot_1 + timedelta(hours=2)
        with pytest.raises(BookingLimitReachedError):
            BookingService.create_hold(
                resident, facility.id, next_slot, next_slot + timedelta(hours=1)
            )

    def test_holds_do_not_count_toward_limit(
        self, complex_a: Any, facility: Any, resident: Any
    ) -> None:
        """A HOLD does not count toward the 2-confirmed limit — only CONFIRMED does."""
        slot_1 = timezone.now().replace(
            hour=8, minute=0, second=0, microsecond=0
        ) + timedelta(days=1)
        BookingFactory(
            complex=complex_a,
            facility=facility,
            resident=resident,
            status=BookingStatus.CONFIRMED,
            slot_start=slot_1,
            slot_end=slot_1 + timedelta(hours=1),
            expires_at=None,
        )
        BookingFactory(
            complex=complex_a,
            facility=facility,
            resident=resident,
            status=BookingStatus.HOLD,
            slot_start=slot_1 + timedelta(hours=1),
            slot_end=slot_1 + timedelta(hours=2),
        )

        new_slot = slot_1 + timedelta(hours=2)
        booking = BookingService.create_hold(
            resident, facility.id, new_slot, new_slot + timedelta(hours=1)
        )
        assert booking.status == BookingStatus.HOLD

    def test_limit_is_per_category_not_global(
        self, complex_a: Any, facility: Any, resident: Any
    ) -> None:
        """2 gym bookings do NOT block a SOCIAL_SPACES booking — limit is per-category."""
        from apps.facilities.models import FacilityCategory

        pool = FacilityFactory(
            complex=complex_a, category=FacilityCategory.SOCIAL_SPACES
        )
        slot_1 = timezone.now().replace(
            hour=8, minute=0, second=0, microsecond=0
        ) + timedelta(days=1)
        for i in range(2):
            s = slot_1 + timedelta(hours=i)
            BookingFactory(
                complex=complex_a,
                facility=facility,
                resident=resident,
                status=BookingStatus.CONFIRMED,
                slot_start=s,
                slot_end=s + timedelta(hours=1),
                expires_at=None,
            )

        pool_slot = slot_1 + timedelta(hours=4)
        hold = BookingService.create_hold(
            resident, pool.id, pool_slot, pool_slot + timedelta(hours=1)
        )
        assert hold.status == BookingStatus.HOLD


@pytest.mark.django_db
class TestHoldExpiry:
    """US-010 — Hold TTL and expiry enforcement."""

    def test_expired_hold_cannot_be_confirmed(
        self, facility: Any, resident: Any
    ) -> None:
        """A hold past its 5-minute TTL must raise HoldExpiredError on confirm."""
        slot_start = timezone.now().replace(
            hour=10, minute=0, second=0, microsecond=0
        ) + timedelta(days=1)
        slot_end = slot_start + timedelta(hours=1)

        with freeze_time("2026-04-22 10:00:00"):
            hold = BookingService.create_hold(
                resident, facility.id, slot_start, slot_end
            )

        with freeze_time("2026-04-22 10:06:00"):  # 6 min — past 5-min TTL
            with pytest.raises(HoldExpiredError):
                BookingService.confirm_hold(hold.id, resident)

    def test_hold_within_ttl_can_be_confirmed(
        self, facility: Any, resident: Any
    ) -> None:
        """A hold within 5-minute TTL → CONFIRMED with expires_at = None."""
        slot_start = timezone.now().replace(
            hour=14, minute=0, second=0, microsecond=0
        ) + timedelta(days=1)
        slot_end = slot_start + timedelta(hours=1)

        with freeze_time("2026-04-22 10:00:00"):
            hold = BookingService.create_hold(
                resident, facility.id, slot_start, slot_end
            )

        with freeze_time("2026-04-22 10:04:00"):  # 4 min — within TTL
            confirmed = BookingService.confirm_hold(hold.id, resident)

        assert confirmed.status == BookingStatus.CONFIRMED
        assert confirmed.expires_at is None

    def test_confirm_nonexistent_hold_raises_not_found(self, resident: Any) -> None:
        """Confirming a UUID that doesn't exist must raise HoldNotFoundError."""
        import uuid

        with pytest.raises(HoldNotFoundError):
            BookingService.confirm_hold(uuid.uuid4(), resident)


@pytest.mark.django_db
class TestCancellation:
    """US-011 — Booking cancellation."""

    def test_cancel_confirmed_booking(
        self, complex_a: Any, facility: Any, resident: Any
    ) -> None:
        """A resident can cancel their own confirmed booking — status becomes CANCELLED."""
        slot_start = timezone.now().replace(
            hour=16, minute=0, second=0, microsecond=0
        ) + timedelta(days=2)
        slot_end = slot_start + timedelta(hours=1)
        booking = BookingFactory(
            complex=complex_a,
            facility=facility,
            resident=resident,
            status=BookingStatus.CONFIRMED,
            slot_start=slot_start,
            slot_end=slot_end,
            expires_at=None,
        )

        cancelled = BookingService.cancel_booking(
            booking.id, resident, str(complex_a.id)
        )

        assert cancelled.status == BookingStatus.CANCELLED
        assert cancelled.cancelled_at is not None
        assert cancelled.cancellation_source == "resident"

    def test_resident_cannot_cancel_others_booking(
        self, complex_a: Any, facility: Any, resident: Any, resident_b: Any
    ) -> None:
        """A resident trying to cancel another resident's booking must get BookingPermissionError.

        WHY BookingPermissionError (not DRF PermissionDenied):
          The service layer is framework-agnostic per ADR-010. Domain exceptions
          (not HTTP-layer DRF exceptions) are raised here. DRF's handler
          reads exception.status_code=403 and returns the correct HTTP response.
        """
        slot_start = timezone.now() + timedelta(days=2, hours=10)
        booking = BookingFactory(
            complex=complex_a,
            facility=facility,
            resident=resident,
            status=BookingStatus.CONFIRMED,
            slot_start=slot_start,
            slot_end=slot_start + timedelta(hours=1),
            expires_at=None,
        )

        with pytest.raises(BookingPermissionError):
            BookingService.cancel_booking(booking.id, resident_b, str(complex_a.id))


@pytest.mark.django_db(transaction=True)
class TestConcurrency:
    """
    Critical path: double-booking prevention under concurrent load.

    transaction=True is MANDATORY. Without it, select_for_update(nowait=True)
    tests deadlock or silently succeed — the real behaviour is never verified.
    Source: testing-strategy.md §4.1
    """

    def test_only_one_concurrent_hold_succeeds(
        self, facility: Any, resident: Any, resident_b: Any
    ) -> None:
        """Two simultaneous holds on the same slot — exactly one succeeds.

        transaction.on_commit fires after COMMIT and dispatches apply_async
        (needs RabbitMQ — not in test env). Mock transaction.on_commit BEFORE
        spawning threads — unittest.mock.patch is not thread-safe when used
        inside each thread individually. Both threads must share the same
        mocked reference for the full duration of the test.
        """
        from unittest.mock import patch

        slot_start = timezone.now().replace(
            hour=9, minute=0, second=0, microsecond=0
        ) + timedelta(days=3)
        slot_end = slot_start + timedelta(hours=1)
        results: list[Booking] = []
        errors: list[Exception] = []

        def attempt(res: Any) -> None:
            try:
                results.append(
                    BookingService.create_hold(res, facility.id, slot_start, slot_end)
                )
            except SlotUnavailableError as e:
                errors.append(e)

        # Patch BEFORE threads start — both threads share the same mocked on_commit.
        with patch(
            "apps.bookings.services.transaction.on_commit",
            side_effect=lambda fn: None,
        ):
            t1 = threading.Thread(target=attempt, args=(resident,))
            t2 = threading.Thread(target=attempt, args=(resident_b,))
            t1.start()
            t2.start()
            t1.join()
            t2.join()

        assert len(results) == 1, f"Expected 1 success, got {len(results)}"
        assert len(errors) == 1, f"Expected 1 SlotUnavailableError, got {len(errors)}"

    def test_gist_exclusion_is_db_backstop(
        self, facility: Any, resident: Any, resident_b: Any
    ) -> None:
        """GiST constraint must reject overlapping CONFIRMED bookings even bypassing service.

        This verifies the DB-level safety net (bookings.0003 migration).
        The constraint fires at COMMIT for status='confirmed' rows with overlapping
        tstzrange — no amount of application-layer bugs can allow a double-booking.
        """
        from django.db import IntegrityError

        slot_start = timezone.now().replace(
            hour=15, minute=0, second=0, microsecond=0
        ) + timedelta(days=3)
        slot_end = slot_start + timedelta(hours=1)

        Booking.objects.create(
            complex=facility.complex,
            facility=facility,
            resident=resident,
            slot_start=slot_start,
            slot_end=slot_end,
            status=BookingStatus.CONFIRMED,
        )

        with pytest.raises(IntegrityError):
            Booking.objects.create(
                complex=facility.complex,
                facility=facility,
                resident=resident_b,
                slot_start=slot_start,
                slot_end=slot_end,
                status=BookingStatus.CONFIRMED,
            )
