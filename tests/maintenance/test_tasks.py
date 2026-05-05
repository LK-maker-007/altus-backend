from __future__ import annotations

"""
Maintenance task unit tests — US-028 (send_maintenance_status_notification).

Tasks are called directly — not via .delay().
Source: Celery 5.x official docs — preferred method is direct call + mock for unit tests.
        TASK_ALWAYS_EAGER is explicitly not recommended for unit tests.

Patch target for expo_push_send:
  "apps.notifications.helpers.expo_push_send"  ← where it is defined (not deferred here)
  The task resolves it via deferred import inside the function body, but the final
  call resolves to the same object — patch the canonical location.

Verified against Celery 5.x docs (2026) and project pattern in
tests/test_visitors/test_tasks.py (same bind=True, same deferred-import approach).
"""

import uuid
from typing import Any

import pytest

from apps.maintenance.models import TicketStatus
from apps.maintenance.tasks import send_maintenance_status_notification
from tests.factories.maintenance_factory import MaintenanceTicketFactory
from tests.factories.user_factory import UserFactory

# ── send_maintenance_status_notification ──────────────────────────────────────


@pytest.mark.django_db
class TestSendMaintenanceStatusNotificationTask:
    """
    Tests for send_maintenance_status_notification — notifies the resident
    when their ticket status changes (US-028).

    Key invariants (from task docstring):
    - Idempotent: exits silently if ticket not found or resident has no push token.
    - Triggered from MaintenanceTicketAdmin.save_model on status change.
    - Uses MaintenanceTicket.unscoped (no request context in Celery workers).
    """

    def test_ticket_not_found_exits_silently(self, complex_a: Any, mocker: Any) -> None:
        """
        Ticket deleted between the admin save and the task executing.
        Task must exit silently — idempotency guarantee.
        """
        mock_push = mocker.patch("apps.notifications.helpers.expo_push_send")

        send_maintenance_status_notification(
            ticket_id=str(uuid.uuid4()),  # non-existent
            complex_id=str(complex_a.id),
        )

        mock_push.assert_not_called()

    def test_no_push_token_exits_silently(
        self, complex_a: Any, unit_a: Any, mocker: Any
    ) -> None:
        """
        Resident raised the ticket but has no Expo push token.
        raised_by.expo_push_token is empty → task exits silently.
        """
        mock_push = mocker.patch("apps.notifications.helpers.expo_push_send")

        resident = UserFactory(
            complex=complex_a,
            phone_number="+919100011100",
            expo_push_token="",  # no token
        )
        ticket = MaintenanceTicketFactory(
            complex=complex_a,
            unit=unit_a,
            raised_by=resident,
            status=TicketStatus.IN_PROGRESS,
        )

        send_maintenance_status_notification(
            ticket_id=str(ticket.id),
            complex_id=str(ticket.complex_id),
        )

        mock_push.assert_not_called()

    def test_wrong_complex_id_exits_silently(
        self, complex_a: Any, complex_b: Any, unit_a: Any, mocker: Any
    ) -> None:
        """
        Task called with wrong complex_id — cross-tenant filter must prevent
        notification being sent for a ticket in another complex.
        MaintenanceTicket.unscoped.get(id=..., complex_id=complex_b.id) → DoesNotExist.
        """
        mock_push = mocker.patch("apps.notifications.helpers.expo_push_send")

        resident = UserFactory(
            complex=complex_a,
            phone_number="+919100011101",
            expo_push_token="ExponentPushToken[wrong-complex-test]",
        )
        ticket = MaintenanceTicketFactory(
            complex=complex_a,
            unit=unit_a,
            raised_by=resident,
            status=TicketStatus.RESOLVED,
        )

        send_maintenance_status_notification(
            ticket_id=str(ticket.id),
            complex_id=str(complex_b.id),  # wrong complex — DoesNotExist
        )

        mock_push.assert_not_called()

    def test_push_sent_for_open_status(
        self, complex_a: Any, unit_a: Any, mocker: Any
    ) -> None:
        """
        Happy path — ticket OPEN, resident has push token.
        expo_push_send must be called with the correct title, body, and data payload.
        """
        mock_push = mocker.patch("apps.notifications.helpers.expo_push_send")

        resident = UserFactory(
            complex=complex_a,
            phone_number="+919100011102",
            expo_push_token="ExponentPushToken[maintenance-open-test]",
        )
        ticket = MaintenanceTicketFactory(
            complex=complex_a,
            unit=unit_a,
            raised_by=resident,
            title="Leaking pipe in bathroom",
            status=TicketStatus.OPEN,
        )

        send_maintenance_status_notification(
            ticket_id=str(ticket.id),
            complex_id=str(ticket.complex_id),
        )

        mock_push.assert_called_once_with(
            token="ExponentPushToken[maintenance-open-test]",
            title="Maintenance update",
            body='Your ticket "Leaking pipe in bathroom" is now opened.',
            data={"ticket_id": str(ticket.id)},
        )

    def test_push_sent_for_in_progress_status(
        self, complex_a: Any, unit_a: Any, mocker: Any
    ) -> None:
        """
        Ticket moved to IN_PROGRESS — body must say "in progress" (not the enum value).
        Tests the status_labels dict mapping (MED-007 enum safety).
        """
        mock_push = mocker.patch("apps.notifications.helpers.expo_push_send")

        resident = UserFactory(
            complex=complex_a,
            phone_number="+919100011103",
            expo_push_token="ExponentPushToken[maintenance-progress-test]",
        )
        ticket = MaintenanceTicketFactory(
            complex=complex_a,
            unit=unit_a,
            raised_by=resident,
            title="Broken door hinge",
            status=TicketStatus.IN_PROGRESS,
        )

        send_maintenance_status_notification(
            ticket_id=str(ticket.id),
            complex_id=str(ticket.complex_id),
        )

        mock_push.assert_called_once_with(
            token="ExponentPushToken[maintenance-progress-test]",
            title="Maintenance update",
            body='Your ticket "Broken door hinge" is now in progress.',
            data={"ticket_id": str(ticket.id)},
        )

    def test_push_sent_for_resolved_status(
        self, complex_a: Any, unit_a: Any, mocker: Any
    ) -> None:
        """
        Ticket RESOLVED — the most important status change for a resident.
        Body must say "resolved".
        """
        mock_push = mocker.patch("apps.notifications.helpers.expo_push_send")

        resident = UserFactory(
            complex=complex_a,
            phone_number="+919100011104",
            expo_push_token="ExponentPushToken[maintenance-resolved-test]",
        )
        ticket = MaintenanceTicketFactory(
            complex=complex_a,
            unit=unit_a,
            raised_by=resident,
            title="Electrical fault in hallway",
            status=TicketStatus.RESOLVED,
        )

        send_maintenance_status_notification(
            ticket_id=str(ticket.id),
            complex_id=str(ticket.complex_id),
        )

        mock_push.assert_called_once_with(
            token="ExponentPushToken[maintenance-resolved-test]",
            title="Maintenance update",
            body='Your ticket "Electrical fault in hallway" is now resolved.',
            data={"ticket_id": str(ticket.id)},
        )

    def test_push_sent_for_closed_status(
        self, complex_a: Any, unit_a: Any, mocker: Any
    ) -> None:
        """
        Ticket CLOSED — body must say "closed".
        Covers all four TicketStatus enum values from MED-007 status_labels dict.
        """
        mock_push = mocker.patch("apps.notifications.helpers.expo_push_send")

        resident = UserFactory(
            complex=complex_a,
            phone_number="+919100011105",
            expo_push_token="ExponentPushToken[maintenance-closed-test]",
        )
        ticket = MaintenanceTicketFactory(
            complex=complex_a,
            unit=unit_a,
            raised_by=resident,
            title="Water damage repair",
            status=TicketStatus.CLOSED,
        )

        send_maintenance_status_notification(
            ticket_id=str(ticket.id),
            complex_id=str(ticket.complex_id),
        )

        mock_push.assert_called_once_with(
            token="ExponentPushToken[maintenance-closed-test]",
            title="Maintenance update",
            body='Your ticket "Water damage repair" is now closed.',
            data={"ticket_id": str(ticket.id)},
        )

    def test_title_truncated_at_60_chars_in_body(
        self, complex_a: Any, unit_a: Any, mocker: Any
    ) -> None:
        """
        Task truncates ticket.title to 60 chars in the push body (ticket.title[:60]).
        Ensures the body string never becomes unreadably long on a push notification.
        """
        mock_push = mocker.patch("apps.notifications.helpers.expo_push_send")

        resident = UserFactory(
            complex=complex_a,
            phone_number="+919100011106",
            expo_push_token="ExponentPushToken[maintenance-truncate-test]",
        )
        long_title = "A" * 80  # 80 chars, truncated to 60 in body
        ticket = MaintenanceTicketFactory(
            complex=complex_a,
            unit=unit_a,
            raised_by=resident,
            title=long_title,
            status=TicketStatus.OPEN,
        )

        send_maintenance_status_notification(
            ticket_id=str(ticket.id),
            complex_id=str(ticket.complex_id),
        )

        call_kwargs = mock_push.call_args.kwargs
        # Body uses title[:60] — 60 A's, not 80
        assert call_kwargs["body"] == f'Your ticket "{"A" * 60}" is now opened.'

    def test_task_is_idempotent(self, complex_a: Any, unit_a: Any, mocker: Any) -> None:
        """
        Calling the task twice with the same args must not raise or corrupt state.
        Each call sends one push (the task has no deduplication guard — callers
        must ensure they don't fire it twice, but the task itself must not crash).
        """
        mock_push = mocker.patch("apps.notifications.helpers.expo_push_send")

        resident = UserFactory(
            complex=complex_a,
            phone_number="+919100011107",
            expo_push_token="ExponentPushToken[maintenance-idempotent-test]",
        )
        ticket = MaintenanceTicketFactory(
            complex=complex_a,
            unit=unit_a,
            raised_by=resident,
            status=TicketStatus.RESOLVED,
        )

        send_maintenance_status_notification(
            ticket_id=str(ticket.id),
            complex_id=str(ticket.complex_id),
        )
        send_maintenance_status_notification(  # second call — must not raise
            ticket_id=str(ticket.id),
            complex_id=str(ticket.complex_id),
        )

        assert mock_push.call_count == 2  # called once per invocation — no silent drop
