from __future__ import annotations

"""
Layer 2 dispatch tests — apps/visitors/services.py

Verifies VisitorService.mark_arrived() correctly enqueues notify_visitor_arrived
via transaction.on_commit() when the registering resident has a push token,
and does NOT enqueue when the token is absent.

Pattern (research-rule.md §10 / Django 6.0 official / Celery 5.6.3):
  django_capture_on_commit_callbacks(execute=True) + mock .apply_async()
"""

from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone

from apps.visitors.models import VisitorStatus
from apps.visitors.services import VisitorService


@pytest.mark.django_db
class TestVisitorDispatch:
    """
    Layer 2 — dispatch tests for VisitorService.mark_arrived().

    `resident` (conftest) is the registered_by user — their push token controls
    whether the Celery task is enqueued.
    `security_user` (conftest) is the actor calling mark_arrived().
    """

    def _make_pending_visitor(self, complex_a: Any, unit_a: Any, resident: Any) -> Any:
        """Create a PENDING visitor registered by `resident` in complex_a."""
        from tests.factories.visitor_factory import VisitorFactory

        return VisitorFactory(
            complex=complex_a,
            unit=unit_a,
            registered_by=resident,
            status=VisitorStatus.PENDING,
            expected_from=timezone.now() - timedelta(minutes=10),
            expected_until=timezone.now() + timedelta(hours=2),
        )

    def test_mark_arrived_dispatches_task_when_resident_has_token(
        self,
        complex_a: Any,
        unit_a: Any,
        resident: Any,
        security_user: Any,
        django_capture_on_commit_callbacks: Any,
        mocker: Any,
    ) -> None:
        """
        Resident (registered_by) has an expo_push_token.
        notify_visitor_arrived.apply_async must be called once with:
        args=(str(visitor.id), str(complex_id),)
        """
        resident.expo_push_token = "ExponentPushToken[dispatch-test-visitor]"
        resident.save(update_fields=["expo_push_token"])

        visitor = self._make_pending_visitor(complex_a, unit_a, resident)

        mock_notify = mocker.patch(
            "apps.visitors.tasks.notify_visitor_arrived.apply_async"
        )

        with django_capture_on_commit_callbacks(execute=True):
            VisitorService.mark_arrived(
                visitor_id=str(visitor.id),
                complex_id=str(complex_a.id),
                security_guard=security_user,
            )

        mock_notify.assert_called_once_with(
            args=(
                str(visitor.id),
                str(complex_a.id),
            ),
        )

    def test_mark_arrived_does_not_dispatch_when_resident_has_no_token(
        self,
        complex_a: Any,
        unit_a: Any,
        resident: Any,
        security_user: Any,
        django_capture_on_commit_callbacks: Any,
        mocker: Any,
    ) -> None:
        """
        Resident has no expo_push_token (opted out or not registered).
        No task must be enqueued — silent no-op.
        """
        resident.expo_push_token = ""
        resident.save(update_fields=["expo_push_token"])

        visitor = self._make_pending_visitor(complex_a, unit_a, resident)

        mock_notify = mocker.patch(
            "apps.visitors.tasks.notify_visitor_arrived.apply_async"
        )

        with django_capture_on_commit_callbacks(execute=True):
            VisitorService.mark_arrived(
                visitor_id=str(visitor.id),
                complex_id=str(complex_a.id),
                security_guard=security_user,
            )

        mock_notify.assert_not_called()
