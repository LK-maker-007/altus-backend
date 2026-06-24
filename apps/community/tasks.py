from __future__ import annotations

import structlog
from celery import shared_task

from apps.core.context import tenant_context

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
    from apps.community.models import Announcement
    from apps.notifications.helpers import PushMessage, expo_push_send_batch
    from apps.users.models import User, UserRole

    with tenant_context(complex_id):
        try:
            announcement = Announcement.unscoped.get(
                id=announcement_id, complex_id=complex_id
            )
        except Announcement.DoesNotExist:
            return

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
