from __future__ import annotations

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

    def test_expires_hold_past_ttl(
        self, complex_a: Any, facility: Any, resident: Any
    ) -> None:
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

        booking.refresh_from_db()
        assert booking.status == BookingStatus.EXPIRED

    def test_does_not_expire_confirmed_booking(
        self, complex_a: Any, facility: Any, resident: Any
    ) -> None:
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
        assert booking.status == BookingStatus.CONFIRMED

    def test_task_is_idempotent(
        self, complex_a: Any, facility: Any, resident: Any
    ) -> None:
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
        expire_booking_hold(str(booking.id), str(booking.complex_id))

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

        expire_booking_hold(str(booking_b.id), str(complex_a.id))

        booking_b.refresh_from_db()
        assert booking_b.status == BookingStatus.HOLD


@pytest.mark.django_db
class TestExpireStaleHoldsTask:

    def test_sweeps_all_expired_holds(
        self, complex_a: Any, facility: Any, resident: Any, resident_b: Any
    ) -> None:
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
        slot_start = timezone.now() + timedelta(days=1, hours=10)
        active_hold = BookingFactory(
            complex=complex_a,
            facility=facility,
            resident=resident,
            status=BookingStatus.HOLD,
            expires_at=timezone.now() + timedelta(minutes=3),
            slot_start=slot_start,
            slot_end=slot_start + timedelta(hours=1),
        )

        expire_stale_holds()

        active_hold.refresh_from_db()
        assert active_hold.status == BookingStatus.HOLD


@pytest.mark.django_db
class TestSendBookingReminderTask:

    def test_booking_not_found_exits_silently(
        self, complex_a: Any, mocker: Any
    ) -> None:
        import uuid

        mock_push = mocker.patch("apps.notifications.helpers.expo_push_send")

        send_booking_reminder(
            booking_id=str(uuid.uuid4()),
            complex_id=str(complex_a.id),
        )

        mock_push.assert_not_called()

    def test_non_confirmed_booking_exits_silently(
        self, complex_a: Any, facility: Any, resident: Any, mocker: Any
    ) -> None:
        from datetime import timedelta

        from django.utils import timezone

        mock_push = mocker.patch("apps.notifications.helpers.expo_push_send")

        slot_start = timezone.now() + timedelta(minutes=30)
        booking = BookingFactory(
            complex=complex_a,
            facility=facility,
            resident=resident,
            status=BookingStatus.HOLD,
            expires_at=timezone.now() + timedelta(minutes=5),
            slot_start=slot_start,
            slot_end=slot_start + timedelta(hours=1),
        )

        send_booking_reminder(
            booking_id=str(booking.id),
            complex_id=str(booking.complex_id),
        )

        mock_push.assert_not_called()

    def test_reminder_runs_within_tenant_context(
        self, complex_a: Any, facility: Any, resident: Any, mocker: Any
    ) -> None:
        from datetime import timedelta

        from django.utils import timezone

        from apps.core.context import _get_current_complex_id

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

        captured: dict[str, str | None] = {}

        def _capture(**kwargs: object) -> None:
            captured["complex_id"] = _get_current_complex_id()

        mocker.patch("apps.notifications.helpers.expo_push_send", side_effect=_capture)

        send_booking_reminder(
            booking_id=str(booking.id),
            complex_id=str(booking.complex_id),
        )

        assert captured["complex_id"] == str(complex_a.id)

    def test_no_push_token_exits_silently(
        self, complex_a: Any, facility: Any, mocker: Any
    ) -> None:
        from datetime import timedelta

        from django.utils import timezone

        from tests.factories.user_factory import UserFactory

        mock_push = mocker.patch("apps.notifications.helpers.expo_push_send")

        resident_no_token = UserFactory(
            complex=complex_a,
            phone_number="+919300011100",
            expo_push_token="",
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
            complex_id=str(complex_b.id),
        )

        mock_push.assert_not_called()
