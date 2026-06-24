from __future__ import annotations

import structlog
from celery import shared_task

from apps.core.context import tenant_context

logger = structlog.get_logger(__name__)


@shared_task(
    bind=True,
    max_retries=3,
    autoretry_for=(ConnectionError, TimeoutError),
    retry_backoff=True,
    retry_jitter=True,
    soft_time_limit=25,
    time_limit=30,
)
def expire_booking_hold(self: object, booking_id: str, complex_id: str) -> None:
    from apps.bookings.models import Booking, BookingStatus

    with tenant_context(complex_id):
        updated = Booking.unscoped.filter(
            id=booking_id,
            complex_id=complex_id,
            status=BookingStatus.HOLD,
        ).update(status=BookingStatus.EXPIRED, expires_at=None)
    if updated:
        logger.info("booking_hold_expired", booking_id=booking_id)


@shared_task(
    bind=True,
    max_retries=3,
    autoretry_for=(ConnectionError, TimeoutError),
    retry_backoff=True,
    retry_jitter=True,
    soft_time_limit=25,
    time_limit=30,
)
def send_booking_reminder(self: object, booking_id: str, complex_id: str) -> None:
    from apps.bookings.models import Booking, BookingStatus

    with tenant_context(complex_id):
        try:
            booking = Booking.unscoped.select_related("resident", "facility").get(
                id=booking_id,
                complex_id=complex_id,
                status=BookingStatus.CONFIRMED,
            )
        except Booking.DoesNotExist:
            return

        push_token = booking.resident.expo_push_token
        if not push_token:
            return

        from apps.notifications.helpers import expo_push_send

        expo_push_send(
            token=push_token,
            title="Upcoming booking",
            body=f"Your {booking.facility.name} booking starts in 30 minutes.",
            data={"booking_id": booking_id},
        )


@shared_task(
    bind=True,
    max_retries=1,
    soft_time_limit=55,
    time_limit=60,
)
def expire_stale_holds(self: object) -> None:
    from django.utils import timezone

    from apps.bookings.models import Booking, BookingStatus

    count = Booking.unscoped.filter(
        status=BookingStatus.HOLD,
        expires_at__lte=timezone.now(),
    ).update(status=BookingStatus.EXPIRED, expires_at=None)
    if count:
        logger.info("stale_holds_expired", count=count)
