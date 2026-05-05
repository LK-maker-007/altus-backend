from __future__ import annotations

from typing import ClassVar

from django.db import models

from apps.core.models import ComplexScopedModel, TimestampedModel


class VisitorStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    ARRIVED = "arrived", "Arrived"
    EXPIRED = "expired", "Expired"


class Visitor(ComplexScopedModel, TimestampedModel):
    unit = models.ForeignKey(
        "core.Unit",
        on_delete=models.RESTRICT,
        related_name="visitors",
    )
    registered_by = models.ForeignKey(
        "users.User",
        on_delete=models.RESTRICT,
        related_name="registered_visitors",
    )
    visitor_name = models.CharField(max_length=200)
    visitor_phone = models.CharField(max_length=20, blank=True, default="")
    expected_from = models.DateTimeField()
    expected_until = models.DateTimeField()
    otp_code = models.CharField(max_length=6)
    status = models.CharField(
        max_length=20,
        choices=VisitorStatus.choices,
        default=VisitorStatus.PENDING,
    )
    arrived_at = models.DateTimeField(null=True, blank=True)
    marked_by = models.ForeignKey(
        "users.User",
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="verified_visitors",
    )

    class Meta:
        indexes: ClassVar[list[models.Index]] = [
            # Gate verification lookup — must be sub-100ms per US-021
            models.Index(fields=["complex", "otp_code", "status"]),
            # Visitor history for a unit, newest first
            models.Index(fields=["unit", "created_at"]),
            # Expiry cleanup sweep
            models.Index(fields=["status", "expected_until"]),
        ]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            # WHY condition=Q(status=VisitorStatus.PENDING):
            #   Without a partial condition, ARRIVED and EXPIRED visitor records
            #   permanently consume their OTP code, depleting the 1,000,000-code space
            #   over time. A busy complex with 100 visitors/day exhausts its code space
            #   in ~27 years — which is a real operational cliff.
            #   With the partial condition, only PENDING codes are unique-constrained;
            #   completed/expired codes are free to be reused for new visitors.
            #   The service layer's _generate_unique_otp already filters status=PENDING
            #   — this constraint now matches that application-layer logic exactly.
            #   Source: Google Principal Architect review — "SIGNIFICANT" §visitor-otp
            models.UniqueConstraint(
                fields=["complex", "otp_code"],
                condition=models.Q(status=VisitorStatus.PENDING),
                name="visitor_otp_unique_per_complex_pending",
            ),
            models.CheckConstraint(
                condition=models.Q(expected_until__gt=models.F("expected_from")),
                name="visitor_window_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=VisitorStatus.values),
                name="visitor_status_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.visitor_name} → {self.unit_id} [{self.status}]"
