from __future__ import annotations

from typing import ClassVar

from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import RangeOperators
from django.contrib.postgres.indexes import OpClass
from django.db import models
from django.db.models import DateTimeField, F, Func, Q

from apps.core.models import ComplexScopedModel, TimestampedModel


class _TsTzRange(Func):
    """PostgreSQL tstzrange(slot_start, slot_end, '[)') — half-open interval.

    '[)' means: inclusive lower bound, exclusive upper bound.
    Booking from 10:00-11:00 does NOT block an 11:00-12:00 slot.
    This matches how humans think about non-overlapping consecutive slots.
    """

    function = "TSTZRANGE"
    output_field = DateTimeField()


class BookingStatus(models.TextChoices):
    HOLD = "hold", "Hold"
    CONFIRMED = "confirmed", "Confirmed"
    CANCELLED = "cancelled", "Cancelled"
    EXPIRED = "expired", "Expired"


class CancellationSource(models.TextChoices):
    RESIDENT = "resident", "Resident"
    ADMIN = "admin", "Admin"


class Booking(ComplexScopedModel, TimestampedModel):
    facility = models.ForeignKey(
        "facilities.Facility",
        on_delete=models.RESTRICT,
        related_name="bookings",
    )
    resident = models.ForeignKey(
        "users.User",
        on_delete=models.RESTRICT,
        related_name="bookings",
    )
    slot_start = models.DateTimeField()
    slot_end = models.DateTimeField()
    status = models.CharField(
        max_length=20,
        choices=BookingStatus.choices,
        default=BookingStatus.HOLD,
    )
    # Set only while status='hold'. Null for confirmed, cancelled, expired.
    expires_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(blank=True, default="")
    cancellation_source = models.CharField(
        max_length=20,
        choices=CancellationSource.choices,
        blank=True,
        default="",
    )
    # WHY client_idempotency_key (audit §Missing for Scale §Booking idempotency):
    #   MaintenanceTicket has this field; Booking did not. A mobile client that
    #   fires POST /bookings/ and gets a network timeout has no way to know if
    #   the hold was created. On retry, a duplicate hold is created for the same
    #   slot — the user is charged twice if both reach CONFIRMED status.
    #   The client generates a UUID before sending the request and retries with
    #   the same key; the server catches IntegrityError on the unique constraint
    #   and returns the already-created booking (idempotent response).
    #   Pattern: identical to MaintenanceTicket.client_idempotency_key.
    #   Source: audit §Missing for Scale; api-contract.md §3 §Idempotency.
    client_idempotency_key = models.UUIDField(
        null=True,
        blank=True,
        unique=False,  # uniqueness enforced via partial UniqueConstraint below
        editable=False,
    )

    class Meta:
        indexes: ClassVar[list[models.Index]] = [
            # Slot availability query — the hottest read path in the system
            models.Index(fields=["facility", "slot_start", "slot_end", "status"]),
            # "My bookings" list + booking quota check per resident
            models.Index(fields=["resident", "status", "slot_start"]),
            # Admin view of all bookings for a complex
            models.Index(fields=["complex", "status", "created_at"]),
            # Partial: hold expiry sweep — scanned only for HOLD rows, not all bookings
            models.Index(
                fields=["expires_at"],
                condition=models.Q(status=BookingStatus.HOLD),
                name="booking_hold_expiry_idx",
            ),
        ]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=models.Q(slot_end__gt=models.F("slot_start")),
                name="booking_slot_end_after_start",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=BookingStatus.values),
                name="booking_status_valid",
            ),
            # GiST exclusion — DB-level backstop against double-booking.
            # Fires at COMMIT for status='confirmed' rows with overlapping tstzrange.
            # Application-layer locks (select_for_update on facility) prevent most
            # conflicts before they reach the DB; this constraint is the last line
            # of defence if application code is bypassed (e.g., direct SQL, admin).
            #
            # Requires: btree_gist extension (installed in template1 via
            # docker/postgres/init/01_extensions.sql).
            #
            # '[)' = half-open interval: 10:00-11:00 does NOT block 11:00-12:00.
            ExclusionConstraint(
                name="booking_no_overlap_confirmed",
                expressions=[
                    # facility_id WITH = requires gist_uuid_ops (from btree_gist)
                    (
                        OpClass(F("facility"), name="gist_uuid_ops"),
                        RangeOperators.EQUAL,
                    ),
                    (
                        _TsTzRange("slot_start", "slot_end"),
                        RangeOperators.OVERLAPS,
                    ),
                ],
                index_type="GIST",
                condition=Q(status=BookingStatus.CONFIRMED),
            ),
            # WHY partial UniqueConstraint (WHERE IS NOT NULL) not unique=True on field:
            #   PostgreSQL treats NULL != NULL — multiple NULL values are allowed in a
            #   unique index. This means non-idempotent bookings (key=NULL) coexist
            #   without constraint violations. Unique=True on the field would require
            #   null=False, making client_idempotency_key mandatory — wrong.
            #   Source: PostgreSQL docs §unique-indexes; MaintenanceTicket pattern.
            models.UniqueConstraint(
                fields=["client_idempotency_key"],
                condition=Q(client_idempotency_key__isnull=False),
                name="booking_idempotency_key_unique",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.resident_id} @ {self.facility_id} [{self.status}]"
