from __future__ import annotations

from typing import ClassVar

from django.db import models

from apps.core.models import ComplexScopedModel, TimestampedModel


class AnnouncementCategory(models.TextChoices):
    GENERAL = "general", "General"
    MAINTENANCE = "maintenance", "Maintenance"
    EVENT = "event", "Event"
    POWER_OUTAGE = "power_outage", "Power Outage"


class Announcement(ComplexScopedModel, TimestampedModel):
    created_by = models.ForeignKey(
        "users.User",
        on_delete=models.RESTRICT,
        related_name="announcements",
    )
    title = models.CharField(max_length=300)
    body = models.TextField()
    category = models.CharField(
        max_length=20,
        choices=AnnouncementCategory.choices,
        default=AnnouncementCategory.GENERAL,
    )
    is_active = models.BooleanField(default=True)

    event_date = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Event start date/time (ISO 8601). Required when category=event.",
    )
    event_venue = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="Venue / location of the event. Optional even for events.",
    )

    class Meta:
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["complex", "is_active", "created_at"]),
            models.Index(fields=["complex", "category", "created_at"]),
        ]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=models.Q(category__in=AnnouncementCategory.values),
                name="announcement_category_valid",
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(category=AnnouncementCategory.EVENT)
                    | models.Q(event_date__isnull=False)
                ),
                name="announcement_event_date_required_for_event",
            ),
        ]

    def __str__(self) -> str:
        return self.title


class AnnouncementRead(models.Model):

    announcement = models.ForeignKey(
        Announcement,
        on_delete=models.CASCADE,
        related_name="reads",
    )
    user = models.ForeignKey(
        "users.User",
        on_delete=models.CASCADE,
        related_name="announcement_reads",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["announcement", "user"],
                name="unique_announcement_read",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user} read {self.announcement}"
