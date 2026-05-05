"""
tests/test_notifications/test_check_push_receipts.py

Tests for the check_push_receipts Celery task (Phase 2 Expo delivery API).

Coverage target: the four status paths (ok→DELIVERED, DeviceNotRegistered,
other-error→FAILED, HTTP error → skip batch) and stale token cleanup.
"""

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
    """Create a NotificationLog with the given parameters."""
    log = NotificationLog(
        push_token=push_token,
        title="Test",
        body="Test body",
        status=status,
        expo_ticket_id=ticket_id,
    )
    log.save()
    # Back-date created_at so the task treats it as old enough
    NotificationLog.objects.filter(pk=log.pk).update(
        created_at=timezone.now() - timedelta(minutes=minutes_old)
    )
    return NotificationLog.objects.get(pk=log.pk)


@pytest.mark.django_db
class TestCheckPushReceipts:
    """Tests for check_push_receipts — Phase 2 Expo receipt polling."""

    def test_delivered_status_updated_on_ok_receipt(self) -> None:
        """Expo 'ok' receipt → NotificationLog.status = DELIVERED."""
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
        """DeviceNotRegistered receipt → DEVICE_NOT_REGISTERED + push token cleared."""

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
        """Non-DeviceNotRegistered error receipt → FAILED status."""
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
        """HTTPError from Expo must not crash the task — skip that batch."""
        import httpx

        _make_log(ticket_id="ticket-http-error")

        with patch("httpx.post", side_effect=httpx.HTTPError("Connection refused")):
            # Must not raise — fire-and-forget batch
            check_push_receipts.apply()

    def test_too_recent_logs_not_polled(self) -> None:
        """Logs created < 15 minutes ago must be skipped (receipts not ready yet)."""
        log = _make_log(ticket_id="ticket-too-recent", minutes_old=5)

        mock_post = MagicMock()
        with patch("httpx.post", return_value=mock_post):
            check_push_receipts.apply()

        # httpx.post must NOT be called — no SENT records old enough
        mock_post.assert_not_called()

        # Status must remain SENT
        log.refresh_from_db()
        assert log.status == NotificationStatus.SENT

    def test_already_delivered_logs_not_re_polled(self) -> None:
        """DELIVERED logs must not be included in the receipt poll batch."""
        _make_log(ticket_id="ticket-already-done", status=NotificationStatus.DELIVERED)

        mock_post = MagicMock()
        with patch("httpx.post", return_value=mock_post):
            check_push_receipts.apply()

        mock_post.assert_not_called()

    def test_non_200_response_skips_batch_without_raising(self) -> None:
        """Non-200 HTTP response must be silently skipped."""
        _make_log(ticket_id="ticket-503")

        mock_response = MagicMock()
        mock_response.status_code = 503

        with patch("httpx.post", return_value=mock_response):
            check_push_receipts.apply()  # must not raise
