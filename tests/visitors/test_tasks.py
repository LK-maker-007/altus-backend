from __future__ import annotations

"""
Visitor task unit tests — US-022 (notify_visitor_arrived),
beat task expire_stale_visitors.

Tasks are called directly — not via .delay().
Source: Celery 5.6.3 official docs — "preferred method is mocking" for unit tests.

Patch target for expo_push_send:
  "apps.visitors.tasks.expo_push_send"   ← where it's imported (deferred)
  NOT "apps.notifications.helpers.expo_push_send"  ← where it's defined
"""

import uuid
from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone

from apps.visitors.models import Visitor, VisitorStatus
from apps.visitors.tasks import expire_stale_visitors, notify_visitor_arrived
from tests.factories.user_factory import UserFactory
from tests.factories.visitor_factory import VisitorFactory

# ── notify_visitor_arrived ─────────────────────────────────────────────────────


@pytest.mark.django_db
class TestNotifyVisitorArrivedTask:
    """
    Tests for notify_visitor_arrived — push notification to the resident
    when their pre-registered visitor arrives at the gate (US-022).
    """

    def test_visitor_not_found_exits_silently(
        self, complex_a: Any, mocker: Any
    ) -> None:
        """
        Visitor deleted between mark_arrived and task running.
        Task must exit silently — idempotency guarantee in docstring.
        """
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
        """
        Resident registered the visitor but has no Expo push token.
        resident.expo_push_token is empty → task exits silently.
        """
        mock_push = mocker.patch("apps.notifications.helpers.expo_push_send")

        resident = UserFactory(
            complex=complex_a,
            phone_number="+919000033300",
            expo_push_token="",  # no token
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
        """
        Happy path — visitor exists, resident has push token.
        expo_push_send must be called with visitor_name interpolated in the body.
        """
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
        """
        Task called with wrong complex_id — cross-tenant filter must prevent
        push being sent for a visitor in another complex.
        Visitor.unscoped.get(id=..., complex_id=complex_b.id) → DoesNotExist.
        """
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
            complex_id=str(complex_b.id),  # wrong complex
        )

        mock_push.assert_not_called()


# ── expire_stale_visitors ──────────────────────────────────────────────────────


@pytest.mark.django_db
class TestExpireStaleVisitorsTask:
    """
    Tests for expire_stale_visitors — the Celery Beat bulk sweep task
    that expires PENDING visitor passes past their expected_until window.

    Runs every 5 minutes per the beat schedule. Cross-complex sweep.
    """

    def test_no_stale_visitors_no_updates(
        self, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
        """
        No PENDING visitors past expected_until → 0 rows updated, no error.
        """
        # Active visitor — expected_until is in the future
        VisitorFactory(
            complex=complex_a,
            unit=unit_a,
            registered_by=resident,
            status=VisitorStatus.PENDING,
            expected_from=timezone.now() - timedelta(hours=1),
            expected_until=timezone.now() + timedelta(hours=3),  # future
        )

        expire_stale_visitors()

        # Visitor must remain PENDING
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
        """
        Multiple PENDING visitors across two complexes — all past expected_until.
        expire_stale_visitors is a cross-complex sweep (no complex_id filter).
        All must be transitioned to EXPIRED in a single call.
        """
        stale_a = VisitorFactory(
            complex=complex_a,
            unit=unit_a,
            registered_by=resident,
            status=VisitorStatus.PENDING,
            expected_from=timezone.now() - timedelta(hours=4),
            expected_until=timezone.now() - timedelta(hours=1),  # past
        )
        stale_b = VisitorFactory(
            complex=complex_b,
            unit=unit_b,
            registered_by=resident_complex_b,
            status=VisitorStatus.PENDING,
            expected_from=timezone.now() - timedelta(hours=2),
            expected_until=timezone.now() - timedelta(minutes=30),  # past
        )

        expire_stale_visitors()

        stale_a.refresh_from_db()
        stale_b.refresh_from_db()
        assert stale_a.status == VisitorStatus.EXPIRED
        assert stale_b.status == VisitorStatus.EXPIRED

    def test_active_pending_visitors_not_touched(
        self, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
        """
        PENDING visitors whose expected_until is in the future must remain PENDING.
        """
        active = VisitorFactory(
            complex=complex_a,
            unit=unit_a,
            registered_by=resident,
            status=VisitorStatus.PENDING,
            expected_from=timezone.now() - timedelta(hours=1),
            expected_until=timezone.now() + timedelta(hours=2),  # active
        )

        expire_stale_visitors()

        active.refresh_from_db()
        assert active.status == VisitorStatus.PENDING

    def test_arrived_visitors_not_touched(
        self, complex_a: Any, unit_a: Any, resident: Any, security_user: Any
    ) -> None:
        """
        ARRIVED visitors are not PENDING — the filter is `status=PENDING`.
        They must not be re-expired, even if their expected_until has passed.
        """
        arrived = VisitorFactory(
            complex=complex_a,
            unit=unit_a,
            registered_by=resident,
            status=VisitorStatus.ARRIVED,
            arrived_at=timezone.now() - timedelta(hours=3),
            expected_from=timezone.now() - timedelta(hours=4),
            expected_until=timezone.now() - timedelta(hours=2),  # past
        )

        expire_stale_visitors()

        arrived.refresh_from_db()
        assert arrived.status == VisitorStatus.ARRIVED

    def test_already_expired_visitors_not_re_expired(
        self, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
        """
        Already-EXPIRED visitors must not be touched.
        The filter is `status=PENDING` — EXPIRED rows are skipped.
        Verifies idempotency of the sweep task.
        """
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
