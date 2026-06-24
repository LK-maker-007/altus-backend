from __future__ import annotations

import uuid
from typing import Any

import pytest

from apps.packages.models import PackageStatus
from apps.packages.tasks import notify_package_arrived
from tests.factories.package_factory import PackageFactory
from tests.factories.user_factory import UserFactory


@pytest.mark.django_db
class TestNotifyPackageArrivedTask:

    def test_package_not_found_exits_silently(
        self, complex_a: Any, mocker: Any
    ) -> None:
        mock_push = mocker.patch("apps.notifications.helpers.expo_push_send")

        notify_package_arrived(
            package_id=str(uuid.uuid4()),
            complex_id=str(complex_a.id),
        )

        mock_push.assert_not_called()

    def test_no_registered_resident_exits_silently(
        self, complex_a: Any, unit_a: Any, security_user: Any, mocker: Any
    ) -> None:
        mock_push = mocker.patch("apps.notifications.helpers.expo_push_send")

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
        mock_push = mocker.patch("apps.notifications.helpers.expo_push_send")

        resident = UserFactory(
            complex=complex_a,
            phone_number="+919000011100",
            expo_push_token="",
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

        notify_package_arrived(
            package_id=str(package.id),
            complex_id=str(complex_b.id),
        )

        mock_push.assert_not_called()
