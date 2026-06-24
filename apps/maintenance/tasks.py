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
def send_maintenance_status_notification(
    self: object, ticket_id: str, complex_id: str
) -> None:
    from apps.maintenance.models import MaintenanceTicket, TicketStatus
    from apps.notifications.helpers import expo_push_send

    with tenant_context(complex_id):
        try:
            ticket = MaintenanceTicket.unscoped.select_related("raised_by").get(
                id=ticket_id, complex_id=complex_id
            )
        except MaintenanceTicket.DoesNotExist:
            return

        push_token = ticket.raised_by.expo_push_token
        if not push_token:
            return

        status_labels: dict[str, str] = {
            TicketStatus.OPEN: "opened",
            TicketStatus.IN_PROGRESS: "in progress",
            TicketStatus.RESOLVED: "resolved",
            TicketStatus.CLOSED: "closed",
        }
        label = status_labels.get(ticket.status, ticket.status)

        expo_push_send(
            token=push_token,
            title="Maintenance update",
            body=f'Your ticket "{ticket.title[:60]}" is now {label}.',
            data={"ticket_id": ticket_id},
        )
        logger.info(
            "maintenance_status_notification_sent",
            ticket_id=ticket_id,
            status=ticket.status,
        )
