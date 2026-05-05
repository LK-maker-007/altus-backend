from __future__ import annotations

"""
Package task unit tests — US-024, US-025.

Tests call task functions directly (not via .delay()).
Source: Celery 5.6.3 docs — "preferred method is mocking" for unit tests.

Key constraints verified before writing:
  - expo_push_send is imported INSIDE notify_package_arrived (deferred import).
    Correct patch target: "apps.packages.tasks.expo_push_send"
    Wrong target:        "apps.notifications.helpers.expo_push_send"
  - Tasks use Package.unscoped — no request context in Celery workers.
  - @pytest.mark.django_db (no transaction=True) — tasks don't dispatch
    further on_commit callbacks, so a real commit is not needed.
"""

import uuid
from typing import Any

import pytest

from apps.packages.models import PackageStatus
from apps.packages.tasks import notify_package_arrived
from tests.factories.package_factory import PackageFactory
from tests.factories.user_factory import UserFactory


@pytest.mark.django_db
class TestNotifyPackageArrivedTask:
    """
    Tests for notify_package_arrived — the push notification task fired
    when security logs an incoming package (US-024, US-025).

    All 5 code paths in the task are covered.
    """

    def test_package_not_found_exits_silently(
        self, complex_a: Any, mocker: Any
    ) -> None:
        """
        Package deleted between service creating it and task running
        (e.g., very fast admin delete or DB race). Task must exit silently
        — no exception, no push sent.

        This is the documented idempotency guarantee in the task docstring.
        """
        mock_push = mocker.patch("apps.notifications.helpers.expo_push_send")

        # Call with a UUID that has no corresponding Package row
        notify_package_arrived(
            package_id=str(uuid.uuid4()),
            complex_id=str(complex_a.id),
        )

        mock_push.assert_not_called()

    def test_no_registered_resident_exits_silently(
        self, complex_a: Any, unit_a: Any, security_user: Any, mocker: Any
    ) -> None:
        """
        Package logged for an unoccupied unit (no registered_resident).
        Task must exit silently — no push sent.

        unit_a has no registered_resident by default (conftest fixture
        only sets it when the `resident` fixture is requested).
        """
        mock_push = mocker.patch("apps.notifications.helpers.expo_push_send")

        # unit_a has no registered_resident — this is the unoccupied unit path
        assert unit_a.registered_resident is None

        package = PackageFactory(
            complex=complex_a,
            unit=unit_a,
            logged_by=security_user,
            status=PackageStatus.PENDING,
        )

        notify_package_arrived(
            package_id=str(package.id),
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
        Resident is registered to the unit but has no Expo push token
        (e.g., they haven't granted notification permission on device).
        Task must exit silently.
        """
        mock_push = mocker.patch("apps.notifications.helpers.expo_push_send")

        # Create a resident with empty push token
        resident = UserFactory(
            complex=complex_a,
            phone_number="+919000011100",
            expo_push_token="",  # no token
        )
        unit_a.registered_resident = resident
        unit_a.save(update_fields=["registered_resident_id"])

        package = PackageFactory(
            complex=complex_a,
            unit=unit_a,
            logged_by=security_user,
            status=PackageStatus.PENDING,
        )

        notify_package_arrived(
            package_id=str(package.id),
            complex_id=str(complex_a.id),
        )

        mock_push.assert_not_called()

    def test_push_sent_to_resident_with_token(
        self,
        complex_a: Any,
        unit_a: Any,
        security_user: Any,
        mocker: Any,
    ) -> None:
        """
        Happy path — package exists, unit has a registered resident, resident
        has a valid Expo push token. expo_push_send must be called with the
        correct arguments.
        """
        mock_push = mocker.patch("apps.notifications.helpers.expo_push_send")

        resident = UserFactory(
            complex=complex_a,
            phone_number="+919000011101",
            expo_push_token="ExponentPushToken[test-token-abc123]",
        )
        unit_a.registered_resident = resident
        unit_a.save(update_fields=["registered_resident_id"])

        package = PackageFactory(
            complex=complex_a,
            unit=unit_a,
            logged_by=security_user,
            status=PackageStatus.PENDING,
        )

        notify_package_arrived(
            package_id=str(package.id),
            complex_id=str(complex_a.id),
        )

        mock_push.assert_called_once_with(
            token="ExponentPushToken[test-token-abc123]",
            title="Package arrived",
            body="A package has arrived at the security desk.",
            data={"package_id": str(package.id)},
        )

    def test_wrong_complex_id_exits_silently(
        self,
        complex_a: Any,
        complex_b: Any,
        unit_a: Any,
        security_user: Any,
        mocker: Any,
    ) -> None:
        """
        Task called with complex_b's ID but the package belongs to complex_a.
        Package.unscoped.get(id=..., complex_id=...) raises DoesNotExist →
        task exits silently.

        This verifies the explicit complex_id filter that prevents cross-tenant
        data access in Celery workers (which have no request context).
        """
        mock_push = mocker.patch("apps.notifications.helpers.expo_push_send")

        resident = UserFactory(
            complex=complex_a,
            phone_number="+919000011102",
            expo_push_token="ExponentPushToken[some-token]",
        )
        unit_a.registered_resident = resident
        unit_a.save(update_fields=["registered_resident_id"])

        package = PackageFactory(
            complex=complex_a,
            unit=unit_a,
            logged_by=security_user,
        )

        # Pass wrong complex_id — cross-tenant filter must reject this
        notify_package_arrived(
            package_id=str(package.id),
            complex_id=str(complex_b.id),  # wrong complex
        )

        mock_push.assert_not_called()
