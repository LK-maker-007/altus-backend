from __future__ import annotations

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

    def test_create_hold_returns_hold_status(
        self, facility: Any, resident: Any
    ) -> None:
        slot_start = timezone.now().replace(
            hour=10, minute=0, second=0, microsecond=0
        ) + timedelta(days=1)
        slot_end = slot_start + timedelta(hours=1)

        booking = BookingService.create_hold(
            resident, facility.id, slot_start, slot_end
        )

        assert booking.status == BookingStatus.HOLD
        assert booking.expires_at is not None
        assert booking.expires_at > timezone.now()

    def test_inactive_facility_raises_not_found(
        self, complex_a: Any, resident: Any
    ) -> None:
        inactive = FacilityFactory(complex=complex_a, is_active=False)
        slot_start = timezone.now() + timedelta(days=1, hours=10)

        with pytest.raises(FacilityNotFoundError):
            BookingService.create_hold(
                resident, inactive.id, slot_start, slot_start + timedelta(hours=1)
            )

    def test_booking_limit_per_category_enforced(
        self, complex_a: Any, facility: Any, resident: Any
    ) -> None:
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

    def test_expired_hold_cannot_be_confirmed(
        self, facility: Any, resident: Any
    ) -> None:
        slot_start = timezone.now().replace(
            hour=10, minute=0, second=0, microsecond=0
        ) + timedelta(days=1)
        slot_end = slot_start + timedelta(hours=1)

        with freeze_time("2026-04-22 10:00:00"):
            hold = BookingService.create_hold(
                resident, facility.id, slot_start, slot_end
            )

        with freeze_time("2026-04-22 10:06:00"):
            with pytest.raises(HoldExpiredError):
                BookingService.confirm_hold(hold.id, resident)

    def test_hold_within_ttl_can_be_confirmed(
        self, facility: Any, resident: Any
    ) -> None:
        slot_start = timezone.now().replace(
            hour=14, minute=0, second=0, microsecond=0
        ) + timedelta(days=1)
        slot_end = slot_start + timedelta(hours=1)

        with freeze_time("2026-04-22 10:00:00"):
            hold = BookingService.create_hold(
                resident, facility.id, slot_start, slot_end
            )

        with freeze_time("2026-04-22 10:04:00"):
            confirmed = BookingService.confirm_hold(hold.id, resident)

        assert confirmed.status == BookingStatus.CONFIRMED
        assert confirmed.expires_at is None

    def test_confirm_nonexistent_hold_raises_not_found(self, resident: Any) -> None:
        import uuid

        with pytest.raises(HoldNotFoundError):
            BookingService.confirm_hold(uuid.uuid4(), resident)


@pytest.mark.django_db
class TestCancellation:

    def test_cancel_confirmed_booking(
        self, complex_a: Any, facility: Any, resident: Any
    ) -> None:
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

    def test_only_one_concurrent_hold_succeeds(
        self, facility: Any, resident: Any, resident_b: Any
    ) -> None:
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
