from __future__ import annotations

from typing import Any

import pytest

from apps.packages.services import PackageService


@pytest.mark.django_db
class TestPackageDispatch:

    def test_log_package_dispatches_task_when_resident_has_token(
        self,
        complex_a: Any,
        unit_a: Any,
        resident: Any,
        security_user: Any,
        django_capture_on_commit_callbacks: Any,
        mocker: Any,
    ) -> None:
        resident.expo_push_token = "ExponentPushToken[dispatch-test-packages]"
        resident.save(update_fields=["expo_push_token"])

        mock_notify = mocker.patch(
            "apps.packages.tasks.notify_package_arrived.apply_async"
        )

        with django_capture_on_commit_callbacks(execute=True):
            package = PackageService.log_package(
                security_guard=security_user,
                unit_number=unit_a.unit_number,
                building_block=unit_a.building_block,
                complex_id=str(complex_a.id),
                description="Amazon parcel",
                notes="Left at reception",
            )

        mock_notify.assert_called_once_with(
            args=(
                str(package.id),
                str(complex_a.id),
            ),
        )

    def test_log_package_does_not_dispatch_when_resident_has_no_token(
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

        mock_notify = mocker.patch(
            "apps.packages.tasks.notify_package_arrived.apply_async"
        )

        with django_capture_on_commit_callbacks(execute=True):
            PackageService.log_package(
                security_guard=security_user,
                unit_number=unit_a.unit_number,
                building_block=unit_a.building_block,
                complex_id=str(complex_a.id),
                description="DHL parcel",
                notes="",
            )

        mock_notify.assert_not_called()

    def test_log_package_does_not_dispatch_when_no_resident_registered(
        self,
        complex_a: Any,
        unit_a: Any,
        security_user: Any,
        django_capture_on_commit_callbacks: Any,
        mocker: Any,
    ) -> None:
        unit_a.registered_resident = None
        unit_a.save(update_fields=["registered_resident_id"])

        mock_notify = mocker.patch(
            "apps.packages.tasks.notify_package_arrived.apply_async"
        )

        with django_capture_on_commit_callbacks(execute=True):
            PackageService.log_package(
                security_guard=security_user,
                unit_number=unit_a.unit_number,
                building_block=unit_a.building_block,
                complex_id=str(complex_a.id),
                description="FedEx parcel",
                notes="",
            )

        mock_notify.assert_not_called()
