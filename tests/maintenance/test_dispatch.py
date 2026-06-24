from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from apps.maintenance.admin import MaintenanceTicketAdmin
from apps.maintenance.models import MaintenanceTicket, TicketStatus


@pytest.mark.django_db
class TestMaintenanceAdminDispatch:

    def _make_request(self, admin_user: Any) -> Any:
        from django.test import RequestFactory

        rf = RequestFactory()
        request = rf.post("/admin/maintenance/maintenanceticket/1/change/")
        request.user = admin_user
        return request

    def _get_admin(self) -> MaintenanceTicketAdmin:
        from django.contrib.admin.sites import AdminSite

        return MaintenanceTicketAdmin(MaintenanceTicket, AdminSite())

    def test_status_change_dispatches_task(
        self,
        complex_a: Any,
        unit_a: Any,
        resident: Any,
        admin_user: Any,
        django_capture_on_commit_callbacks: Any,
        mocker: Any,
    ) -> None:
        from tests.factories.maintenance_factory import MaintenanceTicketFactory

        mock_notify = mocker.patch(
            "apps.maintenance.tasks.send_maintenance_status_notification.apply_async"
        )

        ticket = MaintenanceTicketFactory(
            complex=complex_a,
            unit=unit_a,
            raised_by=resident,
            status=TicketStatus.OPEN,
        )

        ticket.status = TicketStatus.IN_PROGRESS
        request = self._make_request(admin_user)
        admin = self._get_admin()
        form = MagicMock()

        with django_capture_on_commit_callbacks(execute=True):
            admin.save_model(request, ticket, form, change=True)

        mock_notify.assert_called_once_with(
            args=(
                str(ticket.id),
                str(ticket.complex_id),
            ),
        )

    def test_same_status_does_not_dispatch_task(
        self,
        complex_a: Any,
        unit_a: Any,
        resident: Any,
        admin_user: Any,
        django_capture_on_commit_callbacks: Any,
        mocker: Any,
    ) -> None:
        from tests.factories.maintenance_factory import MaintenanceTicketFactory

        mock_notify = mocker.patch(
            "apps.maintenance.tasks.send_maintenance_status_notification.apply_async"
        )

        ticket = MaintenanceTicketFactory(
            complex=complex_a,
            unit=unit_a,
            raised_by=resident,
            status=TicketStatus.OPEN,
        )

        ticket.description = "Updated description"
        request = self._make_request(admin_user)
        admin = self._get_admin()
        form = MagicMock()

        with django_capture_on_commit_callbacks(execute=True):
            admin.save_model(request, ticket, form, change=True)

        mock_notify.assert_not_called()

    def test_new_ticket_does_not_dispatch_task(
        self,
        complex_a: Any,
        unit_a: Any,
        resident: Any,
        admin_user: Any,
        django_capture_on_commit_callbacks: Any,
        mocker: Any,
    ) -> None:
        mock_notify = mocker.patch(
            "apps.maintenance.tasks.send_maintenance_status_notification.apply_async"
        )

        ticket = MaintenanceTicket(
            complex=complex_a,
            unit=unit_a,
            raised_by=resident,
            title="Leaky tap",
            description="Kitchen tap dripping.",
            category="plumbing",
            status=TicketStatus.OPEN,
        )

        request = self._make_request(admin_user)
        admin = self._get_admin()
        form = MagicMock()

        with django_capture_on_commit_callbacks(execute=True):
            admin.save_model(request, ticket, form, change=False)

        mock_notify.assert_not_called()
