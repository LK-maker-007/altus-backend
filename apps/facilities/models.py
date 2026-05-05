from __future__ import annotations

from typing import ClassVar, TypedDict

from django.db import models

from apps.core.models import ComplexScopedModel, TimestampedModel


class OperatingHours(TypedDict):
    """Shape of the operating_hours JSONB column.
    Days use ISO weekday numbering: 0=Monday, 6=Sunday."""

    start: str
    end: str
    slot_duration_minutes: int
    days: list[int]


class FacilityCategory(models.TextChoices):
    SPORTS_FITNESS = "sports_fitness", "Sports & Fitness"
    SOCIAL_SPACES = "social_spaces", "Social Spaces"
    CHILDREN_FAMILY = "children_family", "Children & Family"
    INFRASTRUCTURE = "infrastructure", "Infrastructure"


class Facility(ComplexScopedModel, TimestampedModel):
    name = models.CharField(max_length=200)
    category = models.CharField(max_length=30, choices=FacilityCategory.choices)
    requires_booking = models.BooleanField(default=True)
    # Null = open-access facility (Library, Outdoor Play Area). See PRD §4.3.
    capacity = models.SmallIntegerField(null=True, blank=True)
    operating_hours = models.JSONField()
    is_active = models.BooleanField(default=True)

    class Meta:
        indexes: ClassVar[list[models.Index]] = [
            # Facility list by category — primary read path for the facilities screen
            models.Index(fields=["complex", "category", "is_active"]),
            # Split bookable vs open-access facilities
            models.Index(fields=["complex", "requires_booking"]),
        ]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=models.Q(category__in=FacilityCategory.values),
                name="facility_category_valid",
            )
        ]

    def __str__(self) -> str:
        return self.name
