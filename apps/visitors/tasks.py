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
def notify_visitor_arrived(self: object, visitor_id: str, complex_id: str) -> None:
    """Push notification to resident when their visitor is marked arrived (US-022).

    Idempotent: if the visitor does not exist or the resident has no push token,
    the task exits silently without error. Deduplication is handled by the caller
    (VisitorService.mark_arrived checks expo_push_token before dispatching).
    """
    from apps.visitors.models import Visitor

    try:
        # Unscoped manager — Celery workers have no request context
        visitor = Visitor.unscoped.select_related("registered_by").get(
            id=visitor_id,
            complex_id=complex_id,
        )
    except Visitor.DoesNotExist:
        # Visitor was deleted before task ran — silent exit
        return

    push_token = visitor.registered_by.expo_push_token
    if not push_token:
        return

    from apps.notifications.helpers import expo_push_send

    expo_push_send(
        token=push_token,
        title="Your visitor has arrived",
        body=f"{visitor.visitor_name} has arrived at the gate.",
        data={"visitor_id": visitor_id},
    )
    logger.info("visitor_arrived_notification_sent", visitor_id=visitor_id)


@shared_task(
    bind=True,
    max_retries=1,
    soft_time_limit=55,
    time_limit=60,
)
def expire_stale_visitors(self: object) -> None:
    """Bulk-expire PENDING visitor passes past their expected_until window.

    Registered with Celery Beat (every 5 minutes). Cross-complex sweep —
    no complex_id filter: every expired pass in every complex is swept together.
    """
    from django.utils import timezone

    from apps.visitors.models import Visitor, VisitorStatus

    count = Visitor.unscoped.filter(
        status=VisitorStatus.PENDING,
        expected_until__lte=timezone.now(),
    ).update(status=VisitorStatus.EXPIRED)
    if count:
        logger.info("stale_visitors_expired", count=count)
