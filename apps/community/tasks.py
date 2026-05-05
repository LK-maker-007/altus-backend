from __future__ import annotations

import structlog
from celery import shared_task

logger = structlog.get_logger(__name__)


@shared_task(
    bind=True,
    max_retries=3,
    autoretry_for=(ConnectionError, TimeoutError),
    retry_backoff=True,
    retry_jitter=True,
    soft_time_limit=25,
    time_limit=30,
)
def send_announcement_push(self: object, announcement_id: str, complex_id: str) -> None:
    """Fan-out push notification to all residents when a new announcement is posted.

    Idempotent — exits silently if the announcement or complex is not found.
    Covers US-033 (announcement notification) and US-040 (power outage alert).
    Power outage category gets no special branching here — the mobile client
    handles the distinct visual treatment based on the `category` field in data.

    WHY expo_push_send_batch not per-resident expo_push_send:
      A 500-resident complex fires 500 sequential HTTP round-trips to exp.host
      when using the single-send helper. Each round-trip is ~100ms → 50s task.
      Expo's batch API accepts up to 100 messages per request → 5 requests for
      500 residents → ~600ms total. Also avoids Expo's per-app rate limits.
      Source: audit §Significant §Expo Push — No Batch Send.
    """
    from apps.community.models import Announcement
    from apps.notifications.helpers import PushMessage, expo_push_send_batch
    from apps.users.models import User, UserRole

    try:
        # Unscoped — cross-complex lookup is valid here (task carries explicit id)
        announcement = Announcement.unscoped.get(
            id=announcement_id, complex_id=complex_id
        )
    except Announcement.DoesNotExist:
        return

    # User is not a ComplexScopedModel — no unscoped manager exists on User.
    # User.objects is the UserManager (not scoped). The explicit complex_id
    # filter provides the correct tenant scope for this Celery task.
    tokens = User.objects.filter(
        complex_id=complex_id,
        role=UserRole.RESIDENT,
        expo_push_token__gt="",
        is_active=True,
    ).values_list("expo_push_token", flat=True)

    messages: list[PushMessage] = [
        {
            "to": token,
            "title": announcement.title,
            "body": announcement.body[:100],
            "data": {
                "announcement_id": announcement_id,
                "category": announcement.category,
            },
            "sound": "default",
        }
        for token in tokens
    ]

    expo_push_send_batch(messages)

    logger.info(
        "announcement_push_sent",
        announcement_id=announcement_id,
        complex_id=complex_id,
        recipients=len(messages),
    )
