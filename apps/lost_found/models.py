from __future__ import annotations

from typing import ClassVar

from django.db import models

from apps.core.models import ComplexScopedModel, TimestampedModel


class LostFoundReportType(models.TextChoices):
    LOST = "lost", "Lost"
    FOUND = "found", "Found"


class LostFoundStatus(models.TextChoices):
    OPEN = "open", "Open"
    CLAIMED = "claimed", "Claimed"


class LostFoundReport(ComplexScopedModel, TimestampedModel):
    reported_by = models.ForeignKey(
        "users.User",
        on_delete=models.RESTRICT,
        related_name="lost_found_reports",
    )
    report_type = models.CharField(max_length=10, choices=LostFoundReportType.choices)
    description = models.TextField()
    location = models.CharField(max_length=500)
    status = models.CharField(
        max_length=20,
        choices=LostFoundStatus.choices,
        default=LostFoundStatus.OPEN,
    )
    claimed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["complex", "status", "created_at"]),
        ]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=models.Q(report_type__in=LostFoundReportType.values),
                name="lost_found_report_type_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=LostFoundStatus.values),
                name="lost_found_status_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.report_type.upper()} — {self.description[:50]}"
