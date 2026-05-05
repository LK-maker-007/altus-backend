from __future__ import annotations

"""
Celery task tests for booking-domain tasks.

Coverage target: 85% of apps/bookings/tasks.py (testing-strategy.md §12).

Key patterns:
- Always use Booking.unscoped (not Booking.objects) in task assertions
- Mock expo_push_send at the HTTP boundary — never make real HTTP calls
- Tasks must be idempotent — safe to call twice with same args
"""

from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone

from apps.bookings.models import BookingStatus
from apps.bookings.tasks import (
    expire_booking_hold,
    expire_stale_holds,
    send_booking_reminder,
)
from tests.factories.booking_factory import BookingFactory


@pytest.mark.django_db
class TestExpireBookingHoldTask:
    """Tests for the single-booking hold expiry task."""

    def test_expires_hold_past_ttl(
        self, complex_a: Any, facility: Any, resident: Any
    ) -> None:
        """Task marks an expired hold as EXPIRED."""
        slot_start = timezone.now() + timedelta(days=1, hours=10)
        booking = BookingFactory(
            complex=complex_a,
            facility=facility,
            resident=resident,
            status=BookingStatus.HOLD,
            expires_at=timezone.now() - timedelta(minutes=1),  # already past TTL
            slot_start=slot_start,
            slot_end=slot_start + timedelta(hours=1),
        )

        expire_booking_hold(str(booking.id), str(booking.complex_id))

        booking.refresh_from_db()
        assert booking.status == BookingStatus.EXPIRED

    def test_does_not_expire_confirmed_booking(
        self, complex_a: Any, facility: Any, resident: Any
    ) -> None:
        """Task must not touch a booking that has already been confirmed."""
        slot_start = timezone.now() + timedelta(days=1, hours=10)
        booking = BookingFactory(
            complex=complex_a,
            facility=facility,
            resident=resident,
            status=BookingStatus.CONFIRMED,
            expires_at=None,
            slot_start=slot_start,
            slot_end=slot_start + timedelta(hours=1),
        )

        expire_booking_hold(str(booking.id), str(booking.complex_id))

        booking.refresh_from_db()
        assert booking.status == BookingStatus.CONFIRMED  # unchanged

    def test_task_is_idempotent(
        self, complex_a: Any, facility: Any, resident: Any
    ) -> None:
        """Calling the task twice with the same args must not raise or corrupt state."""
        slot_start = timezone.now() + timedelta(days=1, hours=10)
        booking = BookingFactory(
            complex=complex_a,
            facility=facility,
            resident=resident,
            status=BookingStatus.HOLD,
            expires_at=timezone.now() - timedelta(minutes=1),
            slot_start=slot_start,
            slot_end=slot_start + timedelta(hours=1),
        )

        expire_booking_hold(str(booking.id), str(booking.complex_id))
        expire_booking_hold(str(booking.id), str(booking.complex_id))  # second call

        booking.refresh_from_db()
        assert booking.status == BookingStatus.EXPIRED

    def test_task_uses_correct_complex_id_filter(
        self,
        complex_a: Any,
        complex_b: Any,
        facility: Any,
        facility_b: Any,
        resident: Any,
        resident_complex_b: Any,
    ) -> None:
        """
        Task must use explicit complex_id filter — never rely on RLS
        (which is empty in Celery workers — no request context).
        """
        slot_start = timezone.now() + timedelta(days=1, hours=10)
        booking_b = BookingFactory(
            complex=complex_b,
            facility=facility_b,
            resident=resident_complex_b,
            status=BookingStatus.HOLD,
            expires_at=timezone.now() - timedelta(minutes=1),
            slot_start=slot_start,
            slot_end=slot_start + timedelta(hours=1),
        )

        # Pass complex_b's booking ID but complex_a's complex_id — wrong complex
        expire_booking_hold(str(booking_b.id), str(complex_a.id))

        # Booking must NOT be touched — wrong complex_id filtered it out
        booking_b.refresh_from_db()
        assert booking_b.status == BookingStatus.HOLD


@pytest.mark.django_db
class TestExpireStaleHoldsTask:
    """Tests for the Beat-scheduled bulk hold expiry sweep task."""

    def test_sweeps_all_expired_holds(
        self, complex_a: Any, facility: Any, resident: Any, resident_b: Any
    ) -> None:
        """Bulk task must expire ALL holds past their TTL in one call."""
        slot_1 = timezone.now() + timedelta(days=1, hours=8)
        slot_2 = timezone.now() + timedelta(days=1, hours=9)

        expired_1 = BookingFactory(
            complex=complex_a,
            facility=facility,
            resident=resident,
            status=BookingStatus.HOLD,
            expires_at=timezone.now() - timedelta(minutes=10),
            slot_start=slot_1,
            slot_end=slot_1 + timedelta(hours=1),
        )
        expired_2 = BookingFactory(
            complex=complex_a,
            facility=facility,
            resident=resident_b,
            status=BookingStatus.HOLD,
            expires_at=timezone.now() - timedelta(minutes=1),
            slot_start=slot_2,
            slot_end=slot_2 + timedelta(hours=1),
        )

        expire_stale_holds()

        expired_1.refresh_from_db()
        expired_2.refresh_from_db()
        assert expired_1.status == BookingStatus.EXPIRED
        assert expired_2.status == BookingStatus.EXPIRED

    def test_does_not_sweep_active_holds(
        self, complex_a: Any, facility: Any, resident: Any
    ) -> None:
        """Holds within TTL must not be touched by the sweep task."""
        slot_start = timezone.now() + timedelta(days=1, hours=10)
        active_hold = BookingFactory(
            complex=complex_a,
            facility=facility,
            resident=resident,
            status=BookingStatus.HOLD,
            expires_at=timezone.now() + timedelta(minutes=3),  # still active
            slot_start=slot_start,
            slot_end=slot_start + timedelta(hours=1),
        )

        expire_stale_holds()

        active_hold.refresh_from_db()
        assert active_hold.status == BookingStatus.HOLD


# ── send_booking_reminder ──────────────────────────────────────────────────────


@pytest.mark.django_db
class TestSendBookingReminderTask:
    """
    Tests for send_booking_reminder — 30-minute pre-booking push notification.

    Covers lines 44-61 of apps/bookings/tasks.py.

    Key invariants (from task docstring):
    - Silent exit if booking not found (cancelled, expired, or wrong complex_id).
    - Silent exit if resident has no expo_push_token.
    - Push body interpolates facility.name — requires select_related("resident", "facility").
    """

    def test_booking_not_found_exits_silently(
        self, complex_a: Any, mocker: Any
    ) -> None:
        """
        Booking deleted or not in CONFIRMED state before task fires.
        get() with status=CONFIRMED raises DoesNotExist → task exits silently.
        """
        import uuid

        mock_push = mocker.patch("apps.notifications.helpers.expo_push_send")

        send_booking_reminder(
            booking_id=str(uuid.uuid4()),  # non-existent
            complex_id=str(complex_a.id),
        )

        mock_push.assert_not_called()

    def test_non_confirmed_booking_exits_silently(
        self, complex_a: Any, facility: Any, resident: Any, mocker: Any
    ) -> None:
        """
        Booking exists but is in HOLD status (not CONFIRMED).
        Filter includes status=CONFIRMED → DoesNotExist → silent exit.
        Covers the case where the user cancels between dispatch and execution.
        """
        from datetime import timedelta

        from django.utils import timezone

        mock_push = mocker.patch("apps.notifications.helpers.expo_push_send")

        slot_start = timezone.now() + timedelta(minutes=30)
        booking = BookingFactory(
            complex=complex_a,
            facility=facility,
            resident=resident,
            status=BookingStatus.HOLD,  # not CONFIRMED — filter excludes it
            expires_at=timezone.now() + timedelta(minutes=5),
            slot_start=slot_start,
            slot_end=slot_start + timedelta(hours=1),
        )

        send_booking_reminder(
            booking_id=str(booking.id),
            complex_id=str(booking.complex_id),
        )

        mock_push.assert_not_called()

    def test_no_push_token_exits_silently(
        self, complex_a: Any, facility: Any, mocker: Any
    ) -> None:
        """
        Resident has a confirmed booking but no Expo push token.
        booking.resident.expo_push_token is empty → task exits silently.
        """
        from datetime import timedelta

        from django.utils import timezone

        from tests.factories.user_factory import UserFactory

        mock_push = mocker.patch("apps.notifications.helpers.expo_push_send")

        resident_no_token = UserFactory(
            complex=complex_a,
            phone_number="+919300011100",
            expo_push_token="",  # no token
        )
        slot_start = timezone.now() + timedelta(minutes=30)
        booking = BookingFactory(
            complex=complex_a,
            facility=facility,
            resident=resident_no_token,
            status=BookingStatus.CONFIRMED,
            expires_at=None,
            slot_start=slot_start,
            slot_end=slot_start + timedelta(hours=1),
        )

        send_booking_reminder(
            booking_id=str(booking.id),
            complex_id=str(booking.complex_id),
        )

        mock_push.assert_not_called()

    def test_push_sent_with_facility_name_in_body(
        self, complex_a: Any, facility: Any, resident: Any, mocker: Any
    ) -> None:
        """
        Happy path — confirmed booking, resident has push token.
        expo_push_send must be called with facility.name interpolated in the body.
        Verifies select_related("resident", "facility") is working correctly.
        """
        from datetime import timedelta

        from django.utils import timezone

        from tests.factories.user_factory import UserFactory

        mock_push = mocker.patch("apps.notifications.helpers.expo_push_send")

        resident_with_token = UserFactory(
            complex=complex_a,
            phone_number="+919300011101",
            expo_push_token="ExponentPushToken[booking-reminder-test]",
        )
        slot_start = timezone.now() + timedelta(minutes=30)
        booking = BookingFactory(
            complex=complex_a,
            facility=facility,
            resident=resident_with_token,
            status=BookingStatus.CONFIRMED,
            expires_at=None,
            slot_start=slot_start,
            slot_end=slot_start + timedelta(hours=1),
        )

        send_booking_reminder(
            booking_id=str(booking.id),
            complex_id=str(booking.complex_id),
        )

        mock_push.assert_called_once_with(
            token="ExponentPushToken[booking-reminder-test]",
            title="Upcoming booking",
            body=f"Your {facility.name} booking starts in 30 minutes.",
            data={"booking_id": str(booking.id)},
        )

    def test_wrong_complex_id_exits_silently(
        self, complex_a: Any, complex_b: Any, facility: Any, resident: Any, mocker: Any
    ) -> None:
        """
        Task called with wrong complex_id — cross-tenant filter prevents notification.
        Booking.unscoped.get(id=..., complex_id=complex_b.id, status=CONFIRMED)
        → DoesNotExist → silent exit.
        """
        from datetime import timedelta

        from django.utils import timezone

        mock_push = mocker.patch("apps.notifications.helpers.expo_push_send")

        slot_start = timezone.now() + timedelta(minutes=30)
        booking = BookingFactory(
            complex=complex_a,
            facility=facility,
            resident=resident,
            status=BookingStatus.CONFIRMED,
            expires_at=None,
            slot_start=slot_start,
            slot_end=slot_start + timedelta(hours=1),
        )

        send_booking_reminder(
            booking_id=str(booking.id),
            complex_id=str(complex_b.id),  # wrong complex → DoesNotExist
        )

        mock_push.assert_not_called()
