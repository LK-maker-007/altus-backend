from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

import structlog
from django.db import IntegrityError, OperationalError, models, transaction
from django.utils import timezone

from apps.bookings.exceptions import (
    BookingAlreadyCancelledError,
    BookingLimitReachedError,
    BookingLockContendedError,
    BookingPermissionError,
    HoldExpiredError,
    HoldNotFoundError,
    SlotUnavailableError,
)
from apps.bookings.models import Booking, BookingStatus, CancellationSource
from apps.facilities.exceptions import FacilityNotFoundError
from apps.facilities.models import Facility
from apps.facilities.services import SlotComputeService
from apps.users.models import User, UserRole

logger = structlog.get_logger(__name__)

_BOOKING_LIMIT_PER_CATEGORY = 2
_HOLD_TTL_MINUTES = 5


class BookingService:
    @staticmethod
    def create_hold(
        resident: User,
        facility_id: UUID,
        slot_start: datetime,
        slot_end: datetime,
        client_idempotency_key: UUID | None = None,
    ) -> Booking:
        with transaction.atomic():
            # Lock the parent Facility row, not the booking rows. Locking bookings
            # can't prevent a double-book: SELECT FOR UPDATE over an empty range
            # acquires nothing, so two concurrent requests both see "free" and both
            # insert. Serializing on the facility closes that window. nowait=True
            # fails fast instead of queueing under contention.
            try:
                facility = (
                    Facility.objects.select_for_update(nowait=True)
                    .filter(id=facility_id, is_active=True)
                    .first()
                )
            except OperationalError as exc:
                raise SlotUnavailableError() from exc

            if facility is None:
                raise FacilityNotFoundError()

            confirmed_count = Booking.unscoped.filter(
                resident=resident,
                facility__category=facility.category,
                status=BookingStatus.CONFIRMED,
            ).count()
            if confirmed_count >= _BOOKING_LIMIT_PER_CATEGORY:
                raise BookingLimitReachedError()

            overlapping = Booking.unscoped.filter(
                facility=facility,
                slot_start__lt=slot_end,
                slot_end__gt=slot_start,
            ).filter(
                models.Q(status=BookingStatus.CONFIRMED)
                | models.Q(
                    status=BookingStatus.HOLD,
                    expires_at__gt=timezone.now(),
                )
            )
            if overlapping.exists():
                raise SlotUnavailableError()

            try:
                booking = Booking.objects.create(
                    complex=facility.complex,
                    facility=facility,
                    resident=resident,
                    slot_start=slot_start,
                    slot_end=slot_end,
                    status=BookingStatus.HOLD,
                    expires_at=timezone.now() + timedelta(minutes=_HOLD_TTL_MINUTES),
                    client_idempotency_key=client_idempotency_key,
                )
            except IntegrityError:
                if client_idempotency_key is None:
                    raise
                booking = Booking.objects.get(
                    client_idempotency_key=client_idempotency_key
                )
                logger.info(
                    "booking_hold_idempotent",
                    booking_id=str(booking.id),
                    key=str(client_idempotency_key),
                )
                return booking

            from apps.bookings.tasks import expire_booking_hold

            # Dispatch only after the transaction commits, so the task never runs
            # against a hold that was rolled back.
            transaction.on_commit(
                lambda: expire_booking_hold.apply_async(
                    args=(
                        str(booking.id),
                        str(booking.complex_id),
                    ),
                    countdown=_HOLD_TTL_MINUTES * 60,
                )
            )

        logger.info(
            "booking_hold_created",
            booking_id=str(booking.id),
            facility_id=str(facility.id),
            resident_id=str(resident.id),
        )
        return booking

    @staticmethod
    def confirm_hold(booking_id: UUID, resident: User) -> Booking:
        with transaction.atomic():
            try:
                booking = Booking.objects.select_for_update(nowait=True).get(
                    id=booking_id,
                    resident=resident,
                    status=BookingStatus.HOLD,
                )
            except Booking.DoesNotExist as exc:
                raise HoldNotFoundError() from exc
            except OperationalError as exc:
                raise SlotUnavailableError() from exc

            if booking.expires_at is not None and booking.expires_at <= timezone.now():
                raise HoldExpiredError()

            booking.status = BookingStatus.CONFIRMED
            booking.expires_at = None
            booking.save(update_fields=["status", "expires_at", "updated_at"])

            from apps.bookings.tasks import send_booking_reminder

            reminder_eta = booking.slot_start - timedelta(minutes=30)
            now_ts = timezone.now()

            if reminder_eta > now_ts:
                transaction.on_commit(
                    lambda: send_booking_reminder.apply_async(
                        args=(
                            str(booking.id),
                            str(booking.complex_id),
                        ),
                        eta=reminder_eta,
                    )
                )

        logger.info(
            "booking_confirmed",
            booking_id=str(booking.id),
            facility_id=str(booking.facility_id),
            resident_id=str(resident.id),
        )
        return booking

    @staticmethod
    def cancel_booking(
        booking_id: UUID, actor: User, complex_id: str, reason: str = ""
    ) -> Booking:
        with transaction.atomic():
            try:
                booking = Booking.unscoped.select_for_update(nowait=True).get(
                    id=booking_id,
                    complex_id=complex_id,
                )
            except Booking.DoesNotExist as exc:
                raise HoldNotFoundError() from exc
            except OperationalError as exc:
                raise BookingLockContendedError() from exc

            if actor.role == UserRole.RESIDENT and booking.resident_id != actor.id:
                raise BookingPermissionError()

            if booking.status in (BookingStatus.CANCELLED, BookingStatus.EXPIRED):
                raise BookingAlreadyCancelledError()

            source = (
                CancellationSource.ADMIN
                if actor.role in (UserRole.COMPLEX_ADMIN, UserRole.PLATFORM_ADMIN)
                else CancellationSource.RESIDENT
            )
            booking.status = BookingStatus.CANCELLED
            booking.cancelled_at = timezone.now()
            booking.cancellation_reason = reason
            booking.cancellation_source = source
            booking.save(
                update_fields=[
                    "status",
                    "cancelled_at",
                    "cancellation_reason",
                    "cancellation_source",
                    "updated_at",
                ]
            )

        SlotComputeService.invalidate_slot_cache(
            str(booking.facility_id), booking.slot_start.date()
        )
        logger.info(
            "booking_cancelled",
            booking_id=str(booking.id),
            actor_id=str(actor.id),
            source=source,
        )
        return booking
