from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone

from apps.bookings.models import BookingStatus
from apps.bookings.services import BookingService


@pytest.mark.django_db
class TestBookingDispatch:

    def test_create_hold_dispatches_expire_task_on_commit(
        self,
        complex_a: Any,
        facility: Any,
        resident: Any,
        django_capture_on_commit_callbacks: Any,
        mocker: Any,
    ) -> None:
        mock_expire = mocker.patch(
            "apps.bookings.tasks.expire_booking_hold.apply_async"
        )

        slot_start = timezone.now().replace(
            hour=10, minute=0, second=0, microsecond=0
        ) + timedelta(days=2)
        slot_end = slot_start + timedelta(hours=1)

        with django_capture_on_commit_callbacks(execute=True):
            booking = BookingService.create_hold(
                resident=resident,
                facility_id=facility.id,
                slot_start=slot_start,
                slot_end=slot_end,
            )

        mock_expire.assert_called_once_with(
            args=(
                str(booking.id),
                str(booking.complex_id),
            ),
            countdown=5 * 60,
        )

    def test_confirm_hold_dispatches_reminder_task_on_commit(
        self,
        complex_a: Any,
        facility: Any,
        resident: Any,
        django_capture_on_commit_callbacks: Any,
        mocker: Any,
    ) -> None:
        from tests.factories.booking_factory import BookingFactory

        mock_reminder = mocker.patch(
            "apps.bookings.tasks.send_booking_reminder.apply_async"
        )

        slot_start = timezone.now().replace(
            hour=14, minute=0, second=0, microsecond=0
        ) + timedelta(days=2)
        slot_end = slot_start + timedelta(hours=1)

        booking = BookingFactory(
            complex=complex_a,
            facility=facility,
            resident=resident,
            status=BookingStatus.HOLD,
            expires_at=timezone.now() + timedelta(minutes=5),
            slot_start=slot_start,
            slot_end=slot_end,
        )

        with django_capture_on_commit_callbacks(execute=True):
            BookingService.confirm_hold(
                booking_id=booking.id,
                resident=resident,
            )

        mock_reminder.assert_called_once_with(
            args=(
                str(booking.id),
                str(booking.complex_id),
            ),
            eta=slot_start - timedelta(minutes=30),
        )

    def test_create_hold_does_not_dispatch_on_rollback(
        self,
        complex_a: Any,
        facility: Any,
        resident: Any,
        django_capture_on_commit_callbacks: Any,
        mocker: Any,
    ) -> None:
        mock_expire = mocker.patch(
            "apps.bookings.tasks.expire_booking_hold.apply_async"
        )

        from tests.factories.booking_factory import BookingFactory

        slot_start = timezone.now().replace(
            hour=16, minute=0, second=0, microsecond=0
        ) + timedelta(days=2)
        slot_end = slot_start + timedelta(hours=1)

        BookingFactory(
            complex=complex_a,
            facility=facility,
            resident=resident,
            status=BookingStatus.CONFIRMED,
            expires_at=None,
            slot_start=slot_start,
            slot_end=slot_end,
        )

        from apps.bookings.exceptions import SlotUnavailableError

        with django_capture_on_commit_callbacks(execute=True):
            with pytest.raises(SlotUnavailableError):
                BookingService.create_hold(
                    resident=resident,
                    facility_id=facility.id,
                    slot_start=slot_start,
                    slot_end=slot_end,
                )

        mock_expire.assert_not_called()
