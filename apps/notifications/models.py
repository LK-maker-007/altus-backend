"""
NotificationLog — Expo push delivery audit trail.

WHY this model exists:
  Expo's push API is two-phase:
    Phase 1: POST /v2/push/send → returns per-message ticket IDs
             (queued, not delivered).
    Phase 2: POST /v2/push/getReceipts (15-30 min later) → per-ticket delivery status.

  Without this model there is no answer to "why didn't user X receive their
  booking reminder?" — structlog output is not queryable, not persistent across
  log rotations, and carries no per-user delivery status. This model provides:
    - A queryable delivery audit trail per user and per complex.
    - The ticket IDs needed for Phase 2 receipt polling.
    - DEVICE_NOT_REGISTERED status to drive stale push token cleanup.

  Source: audit §P1 §notifications App has No Models; Expo docs §sending-notifications.
"""

from __future__ import annotations

import uuid
from typing import ClassVar

from django.db import models

from apps.core.models import TimestampedModel


class NotificationStatus(models.TextChoices):
    QUEUED = "QUEUED", "Queued"
    # Expo accepted the message and returned a ticket ID. Delivery not confirmed.
    SENT = "SENT", "Sent"
    # Receipt poll confirmed delivery to APNs/FCM gateway.
    DELIVERED = "DELIVERED", "Delivered"
    # Receipt poll confirmed a delivery error (Expo-level failure).
    FAILED = "FAILED", "Failed"
    # Receipt indicated DeviceNotRegistered — token should be cleared from User.
    DEVICE_NOT_REGISTERED = "DEVICE_NOT_REGISTERED", "Device Not Registered"


class NotificationLog(TimestampedModel):
    """Immutable record of a single push notification send attempt.

    One row per push message. Created when expo_push_send_batch() is called.
    Updated by the check_push_receipts Celery task with the final delivery status.

    Append-only for INSERT and receipt UPDATE only — never deleted except by
    a maintenance purge task (retain 90 days per GDPR minimisation).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # FK nullable — user may be deleted (GDPR) while we need to retain the log.
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
    # Store token at send time — it may be cleared after DeviceNotRegistered.
    push_token = models.CharField(max_length=200)
    title = models.CharField(max_length=200)
    body = models.CharField(max_length=500)
    data = models.JSONField(default=dict)
    status = models.CharField(
        max_length=25,
        choices=NotificationStatus.choices,
        default=NotificationStatus.QUEUED,
    )
    # Populated after Phase 1 (batch send) if Expo returns a ticket.
    expo_ticket_id = models.CharField(max_length=200, blank=True)
    # Populated after Phase 2 (receipt poll).
    checked_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)

    class Meta:
        indexes: ClassVar[list[models.Index]] = [
            # Receipt poll query: find SENT records with ticket IDs
            models.Index(fields=["status", "created_at"]),
            # Per-user delivery audit
            models.Index(fields=["recipient", "created_at"]),
            # Per-complex analytics
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
