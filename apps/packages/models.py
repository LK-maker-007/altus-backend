from __future__ import annotations

from typing import ClassVar

from django.db import models

from apps.core.models import ComplexScopedModel, TimestampedModel


class PackageStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    COLLECTED = "collected", "Collected"


class Package(ComplexScopedModel, TimestampedModel):
    unit = models.ForeignKey(
        "core.Unit",
        on_delete=models.RESTRICT,
        related_name="packages",
    )
    logged_by = models.ForeignKey(
        "users.User",
        on_delete=models.RESTRICT,
        related_name="logged_packages",
    )
    description = models.CharField(max_length=500)
    notes = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=20,
        choices=PackageStatus.choices,
        default=PackageStatus.PENDING,
    )
    collected_at = models.DateTimeField(null=True, blank=True)
    collected_by = models.ForeignKey(
        "users.User",
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="collected_packages",
    )

    class Meta:
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["unit", "status", "created_at"]),
            models.Index(fields=["complex", "status", "created_at"]),
        ]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=models.Q(status__in=PackageStatus.values),
                name="package_status_valid",
            )
        ]

    def __str__(self) -> str:
        return f"{self.description} → {self.unit_id} [{self.status}]"
