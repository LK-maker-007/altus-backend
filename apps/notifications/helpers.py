from __future__ import annotations

import math
from typing import TypedDict

import structlog
from django.conf import settings

logger = structlog.get_logger(__name__)

_EXPO_BATCH_SIZE = 100


class PushMessage(TypedDict, total=False):

    to: str
    title: str
    body: str
    data: dict[str, str]
    sound: str
    recipient_id: str
    complex_id: str


def expo_push_send(
    *,
    token: str,
    title: str,
    body: str,
    data: dict[str, str],
) -> None:
    import httpx

    payload = {
        "to": token,
        "title": title,
        "body": body,
        "data": data,
        "sound": "default",
    }

    try:
        response = httpx.post(
            settings.EXPO_PUSH_URL,
            json=payload,
            timeout=10,
        )
    except httpx.HTTPError as exc:
        logger.warning(
            "expo_push_http_error",
            token_prefix=token[:20],
            error=str(exc),
        )
        return

    if response.status_code != 200:
        logger.warning(
            "expo_push_non_200",
            token_prefix=token[:20],
            status_code=response.status_code,
        )
        return

    try:
        result = response.json()
        ticket = result.get("data", {})
        if ticket.get("status") == "error":
            logger.warning(
                "expo_push_ticket_error",
                token_prefix=token[:20],
                details=ticket.get("details", {}),
                message=ticket.get("message", ""),
            )
    except (ValueError, KeyError):
        logger.warning("expo_push_response_parse_failed", token_prefix=token[:20])


def expo_push_send_batch(messages: list[PushMessage]) -> None:
    if not messages:
        return

    import httpx

    total = len(messages)
    num_batches = math.ceil(total / _EXPO_BATCH_SIZE)

    for batch_idx in range(num_batches):
        start = batch_idx * _EXPO_BATCH_SIZE
        batch = messages[start : start + _EXPO_BATCH_SIZE]

        expo_batch = [
            {k: v for k, v in msg.items() if k not in ("recipient_id", "complex_id")}
            for msg in batch
        ]

        try:
            response = httpx.post(
                settings.EXPO_PUSH_URL,
                json=expo_batch,
                timeout=15,
            )
        except httpx.HTTPError as exc:
            logger.warning(
                "expo_push_batch_http_error",
                batch_idx=batch_idx,
                batch_size=len(batch),
                error=str(exc),
            )
            continue

        if response.status_code != 200:
            logger.warning(
                "expo_push_batch_non_200",
                batch_idx=batch_idx,
                batch_size=len(batch),
                status_code=response.status_code,
            )
            continue

        try:
            tickets: list[dict[str, object]] = response.json().get("data", [])
            _persist_notification_logs(batch, tickets, batch_idx)
        except (ValueError, KeyError):
            logger.warning(
                "expo_push_batch_response_parse_failed",
                batch_idx=batch_idx,
                batch_size=len(batch),
            )

    logger.info(
        "expo_push_batch_sent",
        total_messages=total,
        batches=num_batches,
    )


def _persist_notification_logs(
    messages: list[PushMessage],
    tickets: list[dict[str, object]],
    batch_idx: int,
) -> None:
    from apps.notifications.models import NotificationLog, NotificationStatus

    log_objects: list[NotificationLog] = []

    for i, msg in enumerate(messages):
        ticket = tickets[i] if i < len(tickets) else {}
        ticket_status = ticket.get("status", "")
        expo_ticket_id = str(ticket.get("id") or "") if ticket_status == "ok" else ""

        if ticket_status == "error":
            logger.warning(
                "expo_push_batch_ticket_error",
                batch_idx=batch_idx,
                ticket_idx=i,
                details=ticket.get("details", {}),
                message=ticket.get("message", ""),
            )

        log_objects.append(
            NotificationLog(
                push_token=msg.get("to", ""),
                title=msg.get("title", ""),
                body=msg.get("body", ""),
                data=msg.get("data", {}),
                status=(
                    NotificationStatus.SENT
                    if ticket_status == "ok"
                    else NotificationStatus.FAILED
                ),
                expo_ticket_id=expo_ticket_id,
                recipient_id=msg.get("recipient_id") or None,
                complex_id=msg.get("complex_id") or None,
            )
        )

    try:
        NotificationLog.objects.bulk_create(log_objects, ignore_conflicts=False)
    except Exception:
        logger.warning(
            "notification_log_bulk_create_failed",
            batch_idx=batch_idx,
            count=len(log_objects),
        )
