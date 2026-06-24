from __future__ import annotations

import uuid
from typing import ClassVar

from django.db import models

from apps.core.models import TimestampedModel


class NotificationStatus(models.TextChoices):
    QUEUED = "QUEUED", "Queued"
    SENT = "SENT", "Sent"
    DELIVERED = "DELIVERED", "Delivered"
    FAILED = "FAILED", "Failed"
    DEVICE_NOT_REGISTERED = "DEVICE_NOT_REGISTERED", "Device Not Registered"


class NotificationLog(TimestampedModel):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    recipient = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notification_logs",
    )
    complex = models.ForeignKey(
        "core.Complex",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notification_logs",
    )
    push_token = models.CharField(max_length=200)
    title = models.CharField(max_length=200)
    body = models.CharField(max_length=500)
    data = models.JSONField(default=dict)
    status = models.CharField(
        max_length=25,
        choices=NotificationStatus.choices,
        default=NotificationStatus.QUEUED,
    )
    expo_ticket_id = models.CharField(max_length=200, blank=True)
    checked_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)

    class Meta:
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["recipient", "created_at"]),
            models.Index(fields=["complex", "created_at"]),
        ]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=models.Q(status__in=NotificationStatus.values),
                name="notification_log_status_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"[{self.status}] {self.title} → {self.push_token[:20]}"
