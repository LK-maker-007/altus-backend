"""
apps/notifications/helpers.py

Expo push notification helpers.

WHY expo_push_send (single) and expo_push_send_batch (fan-out) are separate:
  Single-recipient events (visitor arrived, booking confirmed, package ready)
  need per-notification logging with the specific token in context.
  Fan-out events (announcements) send the same payload to N residents — batching
  up to 100 per HTTP request reduces latency from O(N) round-trips to O(N/100).
  Expo's batch API is the documented pattern for fan-out.
  Source: docs.expo.dev/push-notifications/sending-notifications/#http2-api
          audit §Significant §Expo Push — No Batch Send

WHY NotificationLog persistence in expo_push_send_batch:
  Expo's push API is two-phase. Phase 1 (this function) returns ticket IDs —
  not delivery confirmations. Phase 2 (check_push_receipts Celery task, run
  15-30 min later) fetches delivery status per ticket. Without persisting ticket
  IDs here, Phase 2 has nothing to poll. Source: audit §P1 §notifications App.
"""

from __future__ import annotations

import math
from typing import TypedDict

import structlog
from django.conf import settings

logger = structlog.get_logger(__name__)

_EXPO_BATCH_SIZE = 100  # Expo's documented maximum per request


class PushMessage(TypedDict, total=False):
    """Single push notification payload for the Expo Push API.

    Required keys: to, title, body, data, sound.
    Optional keys: recipient_id, complex_id (used for NotificationLog only,
                   not forwarded to Expo).
    """

    to: str
    title: str
    body: str
    data: dict[str, str]
    sound: str
    # WHY optional recipient_id / complex_id:
    #   expo_push_send_batch() creates NotificationLog records for delivery
    #   auditing. These IDs link the log to the user and complex without
    #   requiring callers to create log entries themselves. Not forwarded to Expo.
    recipient_id: str
    complex_id: str


def expo_push_send(
    *,
    token: str,
    title: str,
    body: str,
    data: dict[str, str],
) -> None:
    """Fire-and-forget Expo push notification for a single recipient.

    Best-effort delivery — never raises on HTTP or push-service failure.
    Logs a warning on non-200 or network error so that failures are visible
    in Sentry/structlog without crashing the Celery task.

    For fan-out to many recipients, use expo_push_send_batch() instead.

    Args:
        token: Expo push token (e.g. "ExponentPushToken[xxx]").
        title: Notification title shown in the system tray.
        body:  Notification body text.
        data:  Key-value extras forwarded to the app's notification handler.
               Values must be strings — Expo serialises this as JSON.

    Reference: https://docs.expo.dev/push-notifications/sending-notifications/
    """
    import httpx  # deferred — only workers importing this module need httpx

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

    # Expo returns 200 even for per-token errors — check the inner data field.
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
    except ValueError, KeyError:
        # WHY (ValueError, KeyError) not bare Exception:
        #   response.json() raises ValueError on malformed JSON body.
        #   dict[] raises KeyError (belt-and-suspenders for unexpected shapes).
        #   A bare except Exception would swallow DB connection failures or OOM
        #   errors that should propagate. Narrow to the actual failure modes.
        logger.warning("expo_push_response_parse_failed", token_prefix=token[:20])


def expo_push_send_batch(messages: list[PushMessage]) -> None:
    """Fan-out push notifications in batches of up to 100 per HTTP request.

    Expo's batch API accepts a JSON array of up to 100 push messages per POST.
    For a 500-resident complex announcement, this reduces 500 sequential HTTP
    round-trips to 5 — a 100x improvement in Celery task latency and a fix for
    Expo's per-app rate limits under high load.

    Creates NotificationLog records for Phase 1 ticket IDs. The
    check_push_receipts Celery task (Phase 2) updates these records with
    final delivery status 15-30 minutes later.

    Best-effort — never raises. Per-batch HTTP failures are logged and skipped.

    Args:
        messages: List of PushMessage dicts. Each must have 'to', 'title',
                  'body', 'data', 'sound' keys (use PushMessage TypedDict).
                  Optional 'recipient_id' and 'complex_id' keys are used for
                  NotificationLog persistence and stripped before Expo send.

    Reference: https://docs.expo.dev/push-notifications/sending-notifications/#http2-api
               audit §Significant §Expo Push — No Batch Send
               audit §P1 §notifications App has No Models
    """
    if not messages:
        return

    import httpx  # deferred — only workers importing this module need httpx

    total = len(messages)
    num_batches = math.ceil(total / _EXPO_BATCH_SIZE)

    for batch_idx in range(num_batches):
        start = batch_idx * _EXPO_BATCH_SIZE
        batch = messages[start : start + _EXPO_BATCH_SIZE]

        # Strip internal-only keys before sending to Expo.
        expo_batch = [
            {k: v for k, v in msg.items() if k not in ("recipient_id", "complex_id")}
            for msg in batch
        ]

        try:
            response = httpx.post(
                settings.EXPO_PUSH_URL,
                json=expo_batch,
                timeout=15,  # slightly longer for batch — network write is larger
            )
        except httpx.HTTPError as exc:
            logger.warning(
                "expo_push_batch_http_error",
                batch_idx=batch_idx,
                batch_size=len(batch),
                error=str(exc),
            )
            continue  # best-effort: log and proceed with next batch

        if response.status_code != 200:
            logger.warning(
                "expo_push_batch_non_200",
                batch_idx=batch_idx,
                batch_size=len(batch),
                status_code=response.status_code,
            )
            continue

        # Persist NotificationLog records with Expo ticket IDs for Phase 2 polling.
        try:
            tickets: list[dict[str, object]] = response.json().get("data", [])
            _persist_notification_logs(batch, tickets, batch_idx)
        except ValueError, KeyError:
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
    """Create NotificationLog rows for a batch of sent messages.

    Each message is paired with the corresponding Expo ticket by position.
    Expo returns one ticket per message in the same order as the input list.
    Status is set to SENT if Expo returned a valid ticket ID, FAILED otherwise.

    WHY best-effort (try/except):
      Notification log creation is a diagnostic aid, not a critical path.
      If the DB write fails (e.g. connection blip), the push was already sent —
      we must not raise and cause the Celery task to retry the Expo send.
      The error is logged for visibility via Sentry/structlog.
    """
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
                # recipient_id and complex_id are optional caller-provided metadata.
                recipient_id=msg.get("recipient_id") or None,
                complex_id=msg.get("complex_id") or None,
            )
        )

    try:
        NotificationLog.objects.bulk_create(log_objects, ignore_conflicts=False)
    except Exception:
        # WHY broad except: diagnostic write must never crash the send path.
        logger.warning(
            "notification_log_bulk_create_failed",
            batch_idx=batch_idx,
            count=len(log_objects),
        )
