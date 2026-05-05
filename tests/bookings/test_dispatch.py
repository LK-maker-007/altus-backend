from __future__ import annotations

"""
Layer 2 dispatch tests — apps/bookings/services.py

Verifies that BookingService correctly enqueues Celery tasks via
transaction.on_commit() after a DB commit.

Pattern (per research-rule.md §10, Django 6.0 official docs, Celery 5.6.3 docs):
  - django_capture_on_commit_callbacks(execute=True) simulates the DB commit
    that pytest's test transaction never actually makes.
  - mock .apply_async() — NOT the task function. The service calls .apply_async().
  - assert_called_once_with() verifies exact args passed to the broker.

Sources:
  Django 6.0 — https://docs.djangoproject.com/en/6.0/topics/db/transactions/#use-in-tests
  Celery 5.6.3 — https://docs.celeryq.dev/en/stable/userguide/testing.html
  pytest-django 4.12.0 — django_capture_on_commit_callbacks fixture (added 4.7.0)
"""

from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone

from apps.bookings.models import BookingStatus
from apps.bookings.services import BookingService


@pytest.mark.django_db
class TestBookingDispatch:
    """
    Layer 2 — dispatch tests for BookingService.

    These tests prove the SERVICE CODE correctly registers the on_commit callback
    and passes the right args to apply_async. The task's internal logic is
    separately covered in TestExpireBookingHoldTask / TestSendBookingReminderTask.
    """

    def test_create_hold_dispatches_expire_task_on_commit(
        self,
        complex_a: Any,
        facility: Any,
        resident: Any,
        django_capture_on_commit_callbacks: Any,
        mocker: Any,
    ) -> None:
        """
        BookingService.create_hold() must enqueue expire_booking_hold via
        transaction.on_commit() AFTER the atomic block commits.

        Verifies:
        - .apply_async() is called exactly once
        - args = [str(booking.id), str(booking.complex_id)]
        - countdown = _HOLD_TTL_MINUTES * 60  (= 300 seconds)
        """
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
            countdown=5 * 60,  # _HOLD_TTL_MINUTES = 5
        )

    def test_confirm_hold_dispatches_reminder_task_on_commit(
        self,
        complex_a: Any,
        facility: Any,
        resident: Any,
        django_capture_on_commit_callbacks: Any,
        mocker: Any,
    ) -> None:
        """
        BookingService.confirm_hold() must enqueue send_booking_reminder via
        transaction.on_commit() after the booking status is set to CONFIRMED.

        Verifies:
        - .apply_async() is called exactly once
        - args = [str(booking.id), str(booking.complex_id)]
        - eta = booking.slot_start - timedelta(minutes=30)
        """
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
        """
        If create_hold raises (e.g., slot unavailable), the atomic block rolls
        back and on_commit callbacks must NOT fire. The expire task must never
        be enqueued for a booking that was never committed.
        """
        mock_expire = mocker.patch(
            "apps.bookings.tasks.expire_booking_hold.apply_async"
        )

        # Create a confirmed booking occupying the slot — will trigger SlotUnavailableError
        from tests.factories.booking_factory import BookingFactory

        slot_start = timezone.now().replace(
            hour=16, minute=0, second=0, microsecond=0
        ) + timedelta(days=2)
        slot_end = slot_start + timedelta(hours=1)

        # Pre-occupy the slot
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

        # Transaction rolled back — on_commit callback never registered
        mock_expire.assert_not_called()
