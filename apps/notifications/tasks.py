"""
Notification Celery tasks.

check_push_receipts — Phase 2 of Expo's two-phase push delivery API.

Expo Push flow:
  Phase 1: expo_push_send_batch() POSTs messages → Expo returns ticket IDs per
           message. Ticket IDs are stored on NotificationLog rows (status=SENT).
  Phase 2: This task (run 15-30 min after Phase 1) POSTs ticket IDs to
           /v2/push/getReceipts → Expo returns delivery status per ticket.
           We update NotificationLog.status and clear stale push tokens for
           DeviceNotRegistered errors.

WHY a separate Phase 2 task (not inline after Phase 1):
  Expo docs: "Check receipts at least 15 minutes after sending. Checking
  immediately will return empty receipts." Receipts reflect APNs/FCM delivery
  confirmation, which is asynchronous to Expo's acceptance (Phase 1 ticket).
  Source: https://docs.expo.dev/push-notifications/sending-notifications/

WHY DeviceNotRegistered token cleanup here (not in Phase 1):
  Phase 1 returns tickets, not final delivery status. Stale token detection
  is only possible in Phase 2 receipt data. Cleaning the token here prevents
  wasted API calls on future sends and avoids Expo rate-limit consumption.
"""

from __future__ import annotations

from datetime import timedelta
from typing import cast

import structlog
from celery import shared_task
from django.utils import timezone

logger = structlog.get_logger(__name__)

_EXPO_RECEIPTS_URL = "https://exp.host/--/api/v2/push/getReceipts"
_RECEIPT_BATCH_SIZE = 300  # Expo max per getReceipts call


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
    """Phase 2: poll Expo getReceipts for all SENT notifications older than 15 minutes.

    Updates NotificationLog.status to DELIVERED, FAILED, or
    DEVICE_NOT_REGISTERED. Clears expo_push_token from User for
    DeviceNotRegistered results (stale token cleanup).

    Run every 30 minutes via Celery Beat. Idempotent — re-running processes only
    SENT records with ticket IDs, so duplicate runs are safe.
    """
    import httpx

    from apps.notifications.models import NotificationLog, NotificationStatus
    from apps.users.models import User

    cutoff = timezone.now() - timedelta(minutes=15)
    pending_qs = NotificationLog.objects.filter(
        status=NotificationStatus.SENT,
        created_at__lte=cutoff,
    ).exclude(expo_ticket_id="")

    # WHY values() not values_list:
    #   We need ticket_id → push_token mapping for DeviceNotRegistered cleanup.
    #   Fetching only these two fields avoids loading full model instances.
    #   This eliminates the N+1 that existed when querying per-ticket inside the loop.
    #   Source: audit §HIGH §N+1 in check_push_receipts.
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
                # WHY ticket_token_map lookup (not a per-receipt DB query):
                #   The old implementation queried NotificationLog.objects.filter(
                #   expo_ticket_id=ticket_id).first() inside the loop — one DB hit
                #   per DeviceNotRegistered receipt. With 300 receipts per batch,
                #   that is up to 300 queries. The map was pre-fetched before the
                #   loop in a single VALUES query.
                #   Source: audit §HIGH §N+1 in check_push_receipts.
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

        # WHY bulk_update not per-token save: clearing stale tokens is a
        # low-urgency maintenance operation. Batch is more efficient.
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
