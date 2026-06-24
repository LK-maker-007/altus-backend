from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone

from apps.visitors.models import VisitorStatus
from apps.visitors.services import VisitorService


@pytest.mark.django_db
class TestVisitorDispatch:

    def _make_pending_visitor(self, complex_a: Any, unit_a: Any, resident: Any) -> Any:
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
