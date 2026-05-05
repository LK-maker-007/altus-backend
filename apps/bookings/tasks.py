from __future__ import annotations

import structlog
from celery import shared_task

logger = structlog.get_logger(__name__)


@shared_task(
    bind=True,
    max_retries=3,
    autoretry_for=(ConnectionError, TimeoutError),
    retry_backoff=True,
    retry_jitter=True,
    soft_time_limit=25,  # SoftTimeLimitExceeded gives the task a chance to clean up
    time_limit=30,
)
def expire_booking_hold(self: object, booking_id: str, complex_id: str) -> None:
    """Expire a hold still in HOLD status after TTL. Idempotent via .update()."""
    from apps.bookings.models import Booking, BookingStatus

    # Unscoped manager — Celery workers have no request context
    updated = Booking.unscoped.filter(
        id=booking_id,
        complex_id=complex_id,
        status=BookingStatus.HOLD,
    ).update(status=BookingStatus.EXPIRED, expires_at=None)
    if updated:
        logger.info("booking_hold_expired", booking_id=booking_id)
    # updated == 0: hold was already confirmed or cancelled — nothing to do


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
    """Push 30-min reminder for a confirmed booking. Silent exit if cancelled."""
    from apps.bookings.models import Booking, BookingStatus

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
    """Bulk-expire holds past their TTL. Registered with Celery Beat every 2 minutes."""
    from django.utils import timezone

    from apps.bookings.models import Booking, BookingStatus

    # Intentionally cross-complex — this sweep runs across ALL tenants.
    # No complex_id filter: every expired hold in every complex is expired together.
    count = Booking.unscoped.filter(
        status=BookingStatus.HOLD,
        expires_at__lte=timezone.now(),
    ).update(status=BookingStatus.EXPIRED, expires_at=None)
    if count:
        logger.info("stale_holds_expired", count=count)
