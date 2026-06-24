from __future__ import annotations

from datetime import timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone

from apps.notifications.models import NotificationLog, NotificationStatus
from apps.notifications.tasks import check_push_receipts


def _make_log(
    *,
    status: str = NotificationStatus.SENT,
    ticket_id: str = "ticket-abc",
    minutes_old: int = 20,
    push_token: str = "ExponentPushToken[test]",
) -> NotificationLog:
    log = NotificationLog(
        push_token=push_token,
        title="Test",
        body="Test body",
        status=status,
        expo_ticket_id=ticket_id,
    )
    log.save()
    NotificationLog.objects.filter(pk=log.pk).update(
        created_at=timezone.now() - timedelta(minutes=minutes_old)
    )
    return NotificationLog.objects.get(pk=log.pk)


@pytest.mark.django_db
class TestCheckPushReceipts:

    def test_delivered_status_updated_on_ok_receipt(self) -> None:
        log = _make_log(ticket_id="ticket-delivered")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "ticket-delivered": {"status": "ok"},
            }
        }

        with patch("httpx.post", return_value=mock_response):
            check_push_receipts.apply()

        log.refresh_from_db()
        assert log.status == NotificationStatus.DELIVERED
        assert log.checked_at is not None

    def test_device_not_registered_updates_status_and_clears_token(
        self,
        django_user_model: Any,
    ) -> None:

        user = django_user_model.objects.create_user(
            phone_number="+919000000099",
            expo_push_token="ExponentPushToken[stale-token]",
        )

        log = _make_log(
            ticket_id="ticket-stale",
            push_token="ExponentPushToken[stale-token]",
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "ticket-stale": {
                    "status": "error",
                    "message": "DeviceNotRegistered error",
                    "details": {"error": "DeviceNotRegistered"},
                },
            }
        }

        with patch("httpx.post", return_value=mock_response):
            check_push_receipts.apply()

        log.refresh_from_db()
        assert log.status == NotificationStatus.DEVICE_NOT_REGISTERED

        user.refresh_from_db()
        assert (
            user.expo_push_token == ""
        ), "Stale push token must be cleared on DeviceNotRegistered receipt."

    def test_error_receipt_sets_failed_status(self) -> None:
        log = _make_log(ticket_id="ticket-failed")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "ticket-failed": {
                    "status": "error",
                    "message": "MessageRateExceeded",
                    "details": {"error": "MessageRateExceeded"},
                },
            }
        }

        with patch("httpx.post", return_value=mock_response):
            check_push_receipts.apply()

        log.refresh_from_db()
        assert log.status == NotificationStatus.FAILED

    def test_http_error_skips_batch_without_raising(self) -> None:
        import httpx

        _make_log(ticket_id="ticket-http-error")

        with patch("httpx.post", side_effect=httpx.HTTPError("Connection refused")):
            check_push_receipts.apply()

    def test_too_recent_logs_not_polled(self) -> None:
        log = _make_log(ticket_id="ticket-too-recent", minutes_old=5)

        with patch("httpx.post") as mock_post:
            check_push_receipts.apply()

        mock_post.assert_not_called()

        log.refresh_from_db()
        assert log.status == NotificationStatus.SENT

    def test_already_delivered_logs_not_re_polled(self) -> None:
        _make_log(ticket_id="ticket-already-done", status=NotificationStatus.DELIVERED)

        with patch("httpx.post") as mock_post:
            check_push_receipts.apply()

        mock_post.assert_not_called()

    def test_non_200_response_skips_batch_without_raising(self) -> None:
        _make_log(ticket_id="ticket-503")

        mock_response = MagicMock()
        mock_response.status_code = 503

        with patch("httpx.post", return_value=mock_response):
            check_push_receipts.apply()
