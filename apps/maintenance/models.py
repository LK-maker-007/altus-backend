from __future__ import annotations

import uuid
from typing import ClassVar

from django.db import models

from apps.core.models import ComplexScopedModel, TimestampedModel


class TicketCategory(models.TextChoices):
    ELECTRICAL = "electrical", "Electrical"
    PLUMBING = "plumbing", "Plumbing"
    CARPENTRY = "carpentry", "Carpentry"
    OTHER = "other", "Other"


class TicketStatus(models.TextChoices):
    OPEN = "open", "Open"
    IN_PROGRESS = "in_progress", "In Progress"
    RESOLVED = "resolved", "Resolved"
    CLOSED = "closed", "Closed"


class MaintenanceTicket(ComplexScopedModel, TimestampedModel):
    unit = models.ForeignKey(
        "core.Unit",
        on_delete=models.RESTRICT,
        related_name="maintenance_tickets",
    )
    raised_by = models.ForeignKey(
        "users.User",
        on_delete=models.RESTRICT,
        related_name="raised_tickets",
    )
    category = models.CharField(max_length=30, choices=TicketCategory.choices)
    title = models.CharField(max_length=200)
    description = models.TextField()
    status = models.CharField(
        max_length=20,
        choices=TicketStatus.choices,
        default=TicketStatus.OPEN,
    )
    client_idempotency_key = models.UUIDField(null=True, blank=True, unique=True)
    queued_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["unit", "status", "created_at"]),
            models.Index(fields=["complex", "status", "created_at"]),
            models.Index(fields=["complex", "created_at"]),
        ]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=models.Q(category__in=TicketCategory.values),
                name="ticket_category_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=TicketStatus.values),
                name="ticket_status_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.title} [{self.status}]"


class TicketPhoto(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ticket = models.ForeignKey(
        MaintenanceTicket,
        on_delete=models.CASCADE,
        related_name="photos",
    )
    photo_url = models.CharField(max_length=1000)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["ticket"]),
        ]

    def __str__(self) -> str:
        return f"Photo for {self.ticket_id}"


class TicketStatusHistory(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ticket = models.ForeignKey(
        MaintenanceTicket,
        on_delete=models.CASCADE,
        related_name="status_history",
    )
    status = models.CharField(max_length=20, choices=TicketStatus.choices)
    changed_at = models.DateTimeField(auto_now_add=True)
    changed_by = models.ForeignKey(
        "users.User",
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="ticket_status_changes",
    )

    class Meta:
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["ticket", "changed_at"]),
        ]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=models.Q(status__in=TicketStatus.values),
                name="ticket_status_history_status_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.ticket_id} → {self.status}"
