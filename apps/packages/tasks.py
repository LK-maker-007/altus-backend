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
def notify_package_arrived(self: object, package_id: str, complex_id: str) -> None:
    from apps.packages.models import Package

    with tenant_context(complex_id):
        try:
            package = Package.unscoped.select_related("unit__registered_resident").get(
                id=package_id, complex_id=complex_id
            )
        except Package.DoesNotExist:
            return

        resident = package.unit.registered_resident
        if not resident:
            return

        push_token = resident.expo_push_token
        if not push_token:
            return

        from apps.notifications.helpers import expo_push_send

        expo_push_send(
            token=push_token,
            title="Package arrived",
            body="A package has arrived at the security desk.",
            data={"package_id": package_id},
        )
        logger.info("package_arrived_notification_sent", package_id=package_id)
