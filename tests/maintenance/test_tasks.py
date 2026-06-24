from __future__ import annotations

import uuid
from typing import Any

import pytest

from apps.maintenance.models import TicketStatus
from apps.maintenance.tasks import send_maintenance_status_notification
from tests.factories.maintenance_factory import MaintenanceTicketFactory
from tests.factories.user_factory import UserFactory


@pytest.mark.django_db
class TestSendMaintenanceStatusNotificationTask:

    def test_ticket_not_found_exits_silently(self, complex_a: Any, mocker: Any) -> None:
        mock_push = mocker.patch("apps.notifications.helpers.expo_push_send")

        send_maintenance_status_notification(
            ticket_id=str(uuid.uuid4()),
            complex_id=str(complex_a.id),
        )

        mock_push.assert_not_called()

    def test_no_push_token_exits_silently(
        self, complex_a: Any, unit_a: Any, mocker: Any
    ) -> None:
        mock_push = mocker.patch("apps.notifications.helpers.expo_push_send")

        resident = UserFactory(
            complex=complex_a,
            phone_number="+919100011100",
            expo_push_token="",
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
            complex_id=str(complex_b.id),
        )

        mock_push.assert_not_called()

    def test_push_sent_for_open_status(
        self, complex_a: Any, unit_a: Any, mocker: Any
    ) -> None:
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
        mock_push = mocker.patch("apps.notifications.helpers.expo_push_send")

        resident = UserFactory(
            complex=complex_a,
            phone_number="+919100011106",
            expo_push_token="ExponentPushToken[maintenance-truncate-test]",
        )
        long_title = "A" * 80
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
        assert call_kwargs["body"] == f'Your ticket "{"A" * 60}" is now opened.'

    def test_task_is_idempotent(self, complex_a: Any, unit_a: Any, mocker: Any) -> None:
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
        send_maintenance_status_notification(
            ticket_id=str(ticket.id),
            complex_id=str(ticket.complex_id),
        )

        assert mock_push.call_count == 2
