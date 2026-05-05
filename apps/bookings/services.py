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
        """Create a 5-minute pessimistic hold.

        Idempotency: if client_idempotency_key is provided, the first successful
        hold is created and returned; a retry with the same key catches the
        IntegrityError on booking_idempotency_key_unique and returns the existing
        hold. Prevents duplicate holds on mobile network-timeout retries.
        Pattern: identical to MaintenanceService.create_ticket().
        Source: audit §Missing for Scale §Booking idempotency.

        Locking strategy (MAANG pattern — "parent resource lock"):
          1. Lock the Facility row with SELECT FOR UPDATE NOWAIT inside an atomic
             block. This serializes ALL concurrent hold attempts for that facility,
             regardless of whether any conflicting booking row exists yet.
          2. Check for overlapping active bookings (now safe — no concurrent insert
             can sneak in between the check and our INSERT).
          3. INSERT the new HOLD booking.

        Why not lock booking rows directly?
          SELECT FOR UPDATE on an empty queryset acquires NO locks. Two threads
          both see zero rows, both pass .exists(), both insert → double booking.
          Locking the facility row (the "parent" resource) avoids this entirely.

        Raises SlotUnavailableError if the slot is taken or the lock is contested.
        Raises FacilityNotFoundError if the facility is inactive or missing.
        """
        with transaction.atomic():
            # Step 1: Lock the facility row. This is the serialization point.
            # OperationalError is raised immediately if another transaction holds
            # the lock (nowait=True) — no thread ever blocks indefinitely.
            try:
                facility = (
                    Facility.objects.select_for_update(nowait=True)
                    .filter(id=facility_id, is_active=True)
                    .first()
                )
            except OperationalError as exc:
                # Another transaction is holding the facility lock
                raise SlotUnavailableError() from exc

            if facility is None:
                raise FacilityNotFoundError()

            # Step 2: Quota check — inside the lock so it's consistent.
            confirmed_count = Booking.unscoped.filter(
                resident=resident,
                facility__category=facility.category,
                status=BookingStatus.CONFIRMED,
            ).count()
            if confirmed_count >= _BOOKING_LIMIT_PER_CATEGORY:
                raise BookingLimitReachedError()

            # Step 3: Check for overlapping active bookings (safe — facility is locked).
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

            # Step 4: Safe to insert — facility lock held until transaction commits.
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
                # IntegrityError on booking_idempotency_key_unique:
                # a prior retry with the same key already created the hold.
                # Re-fetch and return it — idempotent response.
                if client_idempotency_key is None:
                    raise  # non-idempotency constraint violation — re-raise
                booking = Booking.objects.get(
                    client_idempotency_key=client_idempotency_key
                )
                logger.info(
                    "booking_hold_idempotent",
                    booking_id=str(booking.id),
                    key=str(client_idempotency_key),
                )
                return booking

            # on_commit defers to outer commit — never fires on rollback.
            # Deferred import breaks services→tasks circular import.
            from apps.bookings.tasks import expire_booking_hold

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
        """Convert an active hold to confirmed. GiST constraint fires at COMMIT."""
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

            # on_commit defers to outer commit — never fires on rollback.
            # Deferred: breaks services→tasks circular import
            from apps.bookings.tasks import send_booking_reminder

            reminder_eta = booking.slot_start - timedelta(minutes=30)
            now_ts = timezone.now()

            # WHY eta guard:
            #   If the user confirms a hold for a slot starting in <30 min,
            #   reminder_eta would be in the past. Celery executes past-eta tasks
            #   immediately — firing "your booking in 30 minutes" at confirmation
            #   time is confusing UX. Skip the reminder entirely if the slot is
            #   within 30 minutes (the user just confirmed, they clearly know).
            #   Source: audit §LOW §send_booking_reminder eta can be in the past.
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
        """Cancel a hold or confirmed booking. Residents own only; admins cancel any.

        WHY complex_id param + unscoped (not Booking.objects):
          Booking.objects is the ComplexScopedManager — it relies on the ContextVar
          being set by ComplexContextMiddleware. This is true in view requests but
          NOT in Celery tasks (which use .unscoped + explicit complex_id by convention).
          For architectural consistency with mark_arrived() and verify_otp(), this
          service method is ContextVar-agnostic: it accepts complex_id explicitly
          and uses .unscoped to guarantee correct behaviour regardless of
          caller context.
          Source: audit §LOW §cancel_booking uses scoped manager inconsistency.
        """
        with transaction.atomic():
            try:
                booking = Booking.unscoped.select_for_update(nowait=True).get(
                    id=booking_id,
                    complex_id=complex_id,
                )
            except Booking.DoesNotExist as exc:
                raise HoldNotFoundError() from exc
            except OperationalError as exc:
                # WHY BookingLockContendedError (not SlotUnavailableError):
                #   OperationalError here means SELECT FOR UPDATE NOWAIT found the
                #   booking row already locked by a concurrent transaction (confirm,
                #   another cancel). This is a transient lock-contention event, not
                #   a business-rule violation. SlotUnavailableError (409 "slot taken")
                #   is semantically wrong for a cancel request. HTTP 503 + Retry-After:1
                #   is the correct signal.
                #   Source: audit §P0 §Mis-mapped OperationalError.
                raise BookingLockContendedError() from exc

            if actor.role == UserRole.RESIDENT and booking.resident_id != actor.id:
                # WHY BookingPermissionError (not DRF PermissionDenied):
                #   ADR-010: services must be framework-agnostic. DRF exceptions
                #   are HTTP-layer; domain exceptions work from views, Celery tasks,
                #   and CLI commands. DRF's handler reads exception.status_code=403.
                raise BookingPermissionError()

            if booking.status in (BookingStatus.CANCELLED, BookingStatus.EXPIRED):
                # WHY BookingAlreadyCancelledError (not DRF ValidationError):
                #   Same ADR-010 rationale. status_code=409 (Conflict) is the
                #   correct HTTP response — same as all other BookingError subclasses.
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
