from __future__ import annotations

from datetime import timedelta
from typing import cast

import structlog
from celery import shared_task
from django.utils import timezone

logger = structlog.get_logger(__name__)

_EXPO_RECEIPTS_URL = "https://exp.host/--/api/v2/push/getReceipts"
_RECEIPT_BATCH_SIZE = 300


@shared_task(
    bind=True,
    max_retries=3,
    autoretry_for=(ConnectionError, TimeoutError),
    retry_backoff=True,
    retry_jitter=True,
    soft_time_limit=55,
    time_limit=60,
)
def check_push_receipts(self: object) -> None:
    import httpx

    from apps.notifications.models import NotificationLog, NotificationStatus
    from apps.users.models import User

    cutoff = timezone.now() - timedelta(minutes=15)
    pending_qs = NotificationLog.objects.filter(
        status=NotificationStatus.SENT,
        created_at__lte=cutoff,
    ).exclude(expo_ticket_id="")

    ticket_token_map: dict[str, str] = {
        row["expo_ticket_id"]: row["push_token"]
        for row in pending_qs.values("expo_ticket_id", "push_token")
    }
    ticket_ids = list(ticket_token_map.keys())
    if not ticket_ids:
        return

    num_batches = (len(ticket_ids) + _RECEIPT_BATCH_SIZE - 1) // _RECEIPT_BATCH_SIZE

    for batch_idx in range(num_batches):
        batch = ticket_ids[
            batch_idx * _RECEIPT_BATCH_SIZE : (batch_idx + 1) * _RECEIPT_BATCH_SIZE
        ]
        try:
            response = httpx.post(
                _EXPO_RECEIPTS_URL,
                json={"ids": batch},
                timeout=15,
            )
        except httpx.HTTPError as exc:
            logger.warning(
                "expo_receipts_http_error",
                batch_idx=batch_idx,
                batch_size=len(batch),
                error=str(exc),
            )
            continue

        if response.status_code != 200:
            logger.warning(
                "expo_receipts_non_200",
                batch_idx=batch_idx,
                status_code=response.status_code,
            )
            continue

        try:
            receipts: dict[str, dict[str, object]] = response.json().get("data", {})
        except ValueError:
            logger.warning("expo_receipts_parse_failed", batch_idx=batch_idx)
            continue

        now = timezone.now()
        stale_tokens: list[str] = []

        for ticket_id, receipt in receipts.items():
            receipt_status = str(receipt.get("status", ""))
            details = cast("dict[str, object]", receipt.get("details") or {})
            error = str(receipt.get("message", ""))

            if receipt_status == "ok":
                new_status = NotificationStatus.DELIVERED
            elif details.get("error") == "DeviceNotRegistered":
                new_status = NotificationStatus.DEVICE_NOT_REGISTERED
                token = ticket_token_map.get(ticket_id, "")
                if token:
                    stale_tokens.append(token)
            else:
                new_status = NotificationStatus.FAILED

            NotificationLog.objects.filter(expo_ticket_id=ticket_id).update(
                status=new_status,
                checked_at=now,
                error_message=error,
            )

        if stale_tokens:
            cleared = User.objects.filter(expo_push_token__in=stale_tokens).update(
                expo_push_token=""
            )
            logger.info(
                "expo_stale_tokens_cleared",
                count=cleared,
                batch_idx=batch_idx,
            )

    logger.info(
        "expo_receipts_checked",
        total_tickets=len(ticket_ids),
        batches=num_batches,
    )
