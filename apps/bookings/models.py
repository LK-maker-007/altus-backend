from __future__ import annotations

from typing import ClassVar

from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import RangeOperators
from django.contrib.postgres.indexes import OpClass
from django.db import models
from django.db.models import DateTimeField, F, Func, Q

from apps.core.models import ComplexScopedModel, TimestampedModel


class _TsTzRange(Func):

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
    expires_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(blank=True, default="")
    cancellation_source = models.CharField(
        max_length=20,
        choices=CancellationSource.choices,
        blank=True,
        default="",
    )
    client_idempotency_key = models.UUIDField(
        null=True,
        blank=True,
        unique=False,
        editable=False,
    )

    class Meta:
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["facility", "slot_start", "slot_end", "status"]),
            models.Index(fields=["resident", "status", "slot_start"]),
            models.Index(fields=["complex", "status", "created_at"]),
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
            ExclusionConstraint(
                name="booking_no_overlap_confirmed",
                expressions=[
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
            models.UniqueConstraint(
                fields=["client_idempotency_key"],
                condition=Q(client_idempotency_key__isnull=False),
                name="booking_idempotency_key_unique",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.resident_id} @ {self.facility_id} [{self.status}]"
