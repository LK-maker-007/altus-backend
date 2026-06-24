from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone

from apps.visitors.models import Visitor, VisitorStatus
from apps.visitors.tasks import expire_stale_visitors, notify_visitor_arrived
from tests.factories.user_factory import UserFactory
from tests.factories.visitor_factory import VisitorFactory


@pytest.mark.django_db
class TestNotifyVisitorArrivedTask:

    def test_visitor_not_found_exits_silently(
        self, complex_a: Any, mocker: Any
    ) -> None:
        mock_push = mocker.patch("apps.notifications.helpers.expo_push_send")

        notify_visitor_arrived(
            visitor_id=str(uuid.uuid4()),
            complex_id=str(complex_a.id),
        )

        mock_push.assert_not_called()

    def test_no_push_token_exits_silently(
        self,
        complex_a: Any,
        unit_a: Any,
        security_user: Any,
        mocker: Any,
    ) -> None:
        mock_push = mocker.patch("apps.notifications.helpers.expo_push_send")

        resident = UserFactory(
            complex=complex_a,
            phone_number="+919000033300",
            expo_push_token="",
        )
        unit_a.registered_resident = resident
        unit_a.save(update_fields=["registered_resident_id"])

        visitor = VisitorFactory(
            complex=complex_a,
            unit=unit_a,
            registered_by=resident,
            status=VisitorStatus.ARRIVED,
            arrived_at=timezone.now(),
            expected_from=timezone.now() - timedelta(hours=1),
            expected_until=timezone.now() + timedelta(hours=2),
        )

        notify_visitor_arrived(
            visitor_id=str(visitor.id),
            complex_id=str(complex_a.id),
        )

        mock_push.assert_not_called()

    def test_push_sent_with_visitor_name_in_body(
        self,
        complex_a: Any,
        unit_a: Any,
        security_user: Any,
        mocker: Any,
    ) -> None:
        mock_push = mocker.patch("apps.notifications.helpers.expo_push_send")

        resident = UserFactory(
            complex=complex_a,
            phone_number="+919000033301",
            expo_push_token="ExponentPushToken[resident-visitor-test]",
        )
        unit_a.registered_resident = resident
        unit_a.save(update_fields=["registered_resident_id"])

        visitor = VisitorFactory(
            complex=complex_a,
            unit=unit_a,
            registered_by=resident,
            visitor_name="John Doe",
            status=VisitorStatus.ARRIVED,
            arrived_at=timezone.now(),
            expected_from=timezone.now() - timedelta(hours=1),
            expected_until=timezone.now() + timedelta(hours=2),
        )

        notify_visitor_arrived(
            visitor_id=str(visitor.id),
            complex_id=str(complex_a.id),
        )

        mock_push.assert_called_once_with(
            token="ExponentPushToken[resident-visitor-test]",
            title="Your visitor has arrived",
            body="John Doe has arrived at the gate.",
            data={"visitor_id": str(visitor.id)},
        )

    def test_wrong_complex_id_exits_silently(
        self,
        complex_a: Any,
        complex_b: Any,
        unit_a: Any,
        mocker: Any,
    ) -> None:
        mock_push = mocker.patch("apps.notifications.helpers.expo_push_send")

        resident = UserFactory(
            complex=complex_a,
            phone_number="+919000033302",
            expo_push_token="ExponentPushToken[any-token]",
        )
        unit_a.registered_resident = resident
        unit_a.save(update_fields=["registered_resident_id"])

        visitor = VisitorFactory(
            complex=complex_a,
            unit=unit_a,
            registered_by=resident,
            status=VisitorStatus.ARRIVED,
            arrived_at=timezone.now(),
            expected_from=timezone.now() - timedelta(hours=1),
            expected_until=timezone.now() + timedelta(hours=2),
        )

        notify_visitor_arrived(
            visitor_id=str(visitor.id),
            complex_id=str(complex_b.id),
        )

        mock_push.assert_not_called()


@pytest.mark.django_db
class TestExpireStaleVisitorsTask:

    def test_no_stale_visitors_no_updates(
        self, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
        VisitorFactory(
            complex=complex_a,
            unit=unit_a,
            registered_by=resident,
            status=VisitorStatus.PENDING,
            expected_from=timezone.now() - timedelta(hours=1),
            expected_until=timezone.now() + timedelta(hours=3),
        )

        expire_stale_visitors()

        assert (
            Visitor.unscoped.filter(
                status=VisitorStatus.PENDING,
            ).count()
            == 1
        )

    def test_stale_pending_visitors_expired_in_bulk(
        self,
        complex_a: Any,
        unit_a: Any,
        resident: Any,
        complex_b: Any,
        unit_b: Any,
        resident_complex_b: Any,
    ) -> None:
        stale_a = VisitorFactory(
            complex=complex_a,
            unit=unit_a,
            registered_by=resident,
            status=VisitorStatus.PENDING,
            expected_from=timezone.now() - timedelta(hours=4),
            expected_until=timezone.now() - timedelta(hours=1),
        )
        stale_b = VisitorFactory(
            complex=complex_b,
            unit=unit_b,
            registered_by=resident_complex_b,
            status=VisitorStatus.PENDING,
            expected_from=timezone.now() - timedelta(hours=2),
            expected_until=timezone.now() - timedelta(minutes=30),
        )

        expire_stale_visitors()

        stale_a.refresh_from_db()
        stale_b.refresh_from_db()
        assert stale_a.status == VisitorStatus.EXPIRED
        assert stale_b.status == VisitorStatus.EXPIRED

    def test_active_pending_visitors_not_touched(
        self, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
        active = VisitorFactory(
            complex=complex_a,
            unit=unit_a,
            registered_by=resident,
            status=VisitorStatus.PENDING,
            expected_from=timezone.now() - timedelta(hours=1),
            expected_until=timezone.now() + timedelta(hours=2),
        )

        expire_stale_visitors()

        active.refresh_from_db()
        assert active.status == VisitorStatus.PENDING

    def test_arrived_visitors_not_touched(
        self, complex_a: Any, unit_a: Any, resident: Any, security_user: Any
    ) -> None:
        arrived = VisitorFactory(
            complex=complex_a,
            unit=unit_a,
            registered_by=resident,
            status=VisitorStatus.ARRIVED,
            arrived_at=timezone.now() - timedelta(hours=3),
            expected_from=timezone.now() - timedelta(hours=4),
            expected_until=timezone.now() - timedelta(hours=2),
        )

        expire_stale_visitors()

        arrived.refresh_from_db()
        assert arrived.status == VisitorStatus.ARRIVED

    def test_already_expired_visitors_not_re_expired(
        self, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
        already_expired = VisitorFactory(
            complex=complex_a,
            unit=unit_a,
            registered_by=resident,
            status=VisitorStatus.EXPIRED,
            expected_from=timezone.now() - timedelta(hours=6),
            expected_until=timezone.now() - timedelta(hours=4),
        )

        expire_stale_visitors()

        already_expired.refresh_from_db()
        assert already_expired.status == VisitorStatus.EXPIRED
