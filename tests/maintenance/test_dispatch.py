from __future__ import annotations

"""
Layer 2 dispatch tests — apps/maintenance/admin.py MaintenanceTicketAdmin.save_model()

Verifies that saving a MaintenanceTicket with a status CHANGE dispatches
send_maintenance_status_notification via transaction.on_commit(), and that
saves without a status change do NOT dispatch.

Pattern (research-rule.md §10 / Django 6.0 official / Celery 5.6.3):
  django_capture_on_commit_callbacks(execute=True) + mock .apply_async()

Admin save_model() is called directly — no full HTTP stack needed.
Django RequestFactory provides the minimal request with an authenticated user.
"""

from typing import Any
from unittest.mock import MagicMock

import pytest

from apps.maintenance.admin import MaintenanceTicketAdmin
from apps.maintenance.models import MaintenanceTicket, TicketStatus


@pytest.mark.django_db
class TestMaintenanceAdminDispatch:
    """
    Layer 2 — dispatch tests for MaintenanceTicketAdmin.save_model().

    Conditions tested:
    - Status change (OPEN → IN_PROGRESS) → task dispatched ✅
    - Same status (OPEN → OPEN) → task NOT dispatched ✅
    - New ticket (change=False) → task NOT dispatched ✅
    """

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
        """
        Changing a ticket's status (OPEN → IN_PROGRESS) must dispatch
        send_maintenance_status_notification with:
        args=(str(obj.id), str(obj.complex_id),)
        """
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

        # Simulate admin changing status to IN_PROGRESS
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
        """
        Saving a ticket with the SAME status (e.g., updating description only)
        must NOT dispatch — residents must not receive spurious notifications.
        """
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

        # Status unchanged — only description edited
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
        """
        Creating a NEW ticket (change=False) must NOT dispatch.
        The task is only for status TRANSITIONS on existing tickets.
        """
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
            admin.save_model(request, ticket, form, change=False)  # NEW

        mock_notify.assert_not_called()
