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

    # ── Event-specific fields — only populated when category=EVENT ──────────
    # WHY nullable: non-event announcements (general, maintenance, power_outage)
    #   have no meaningful date/venue. Null = "not an event" for those rows.
    # WHY CheckConstraint below: event_date must be set when category=EVENT.
    #   Prevents malformed event records at the DB level — service layer still
    #   validates this but the DB is the last line of defence.
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
            # Resident announcements list — newest first, active only
            models.Index(fields=["complex", "is_active", "created_at"]),
            # Filtered by category — power outage uses this for immediate fan-out
            models.Index(fields=["complex", "category", "created_at"]),
        ]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=models.Q(category__in=AnnouncementCategory.values),
                name="announcement_category_valid",
            ),
            models.CheckConstraint(
                # WHY AnnouncementCategory.EVENT not "event": using the TextChoices
                # constant makes this refactor-safe. A raw string silently enforces
                # the wrong value if the choice is ever renamed.
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
    """Records that a resident explicitly marked an announcement as read.

    WHY separate model not a ManyToManyField on Announcement:
        Announcements are complex-scoped and may be read by hundreds of residents.
        A M2M on the announcement itself creates a join table without created_at
        or user-level metadata. A separate model gives us a created_at timestamp,
        clean admin visibility, and a UniqueConstraint for idempotent mark-read.

    WHY no complex FK: read records are already implicitly scoped via
        the announcement FK — announcement.complex == user's complex.

    WHY TimestampedModel not used: AnnouncementRead only needs created_at
        (there is no updated_at — a read record is immutable). Using
        models.Model with a single DateTimeField is the minimal correct choice.
    """

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
                # WHY: mark-read is idempotent. A resident tapping "Mark as Read"
                # twice must not create duplicate rows. Enforced at DB level to
                # survive concurrent requests (use get_or_create in the view).
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user} read {self.announcement}"
