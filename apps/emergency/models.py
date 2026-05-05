from __future__ import annotations

from typing import ClassVar

from django.db import models

from apps.core.models import ComplexScopedModel, TimestampedModel


class EmergencyContact(ComplexScopedModel, TimestampedModel):
    name = models.CharField(max_length=200)
    role = models.CharField(max_length=200)
    phone_number = models.CharField(max_length=20)
    display_order = models.SmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        indexes: ClassVar[list[models.Index]] = [
            # Contacts list — ordered by display_order, active only
            models.Index(fields=["complex", "is_active", "display_order"]),
        ]
        ordering: ClassVar[list[str]] = ["display_order"]

    def __str__(self) -> str:
        return f"{self.name} ({self.role})"
