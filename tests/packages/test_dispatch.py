from __future__ import annotations

"""
Layer 2 dispatch tests — apps/packages/services.py

Verifies PackageService.log_package() correctly enqueues notify_package_arrived
via transaction.on_commit() when the unit has a registered resident with a
push token, and does NOT enqueue when the resident is missing or has no token.

Pattern (research-rule.md §10 / Django 6.0 official / Celery 5.6.3):
  django_capture_on_commit_callbacks(execute=True) + mock .apply_async()
"""

from typing import Any

import pytest

from apps.packages.services import PackageService


@pytest.mark.django_db
class TestPackageDispatch:
    """
    Layer 2 — dispatch tests for PackageService.log_package().

    The unit_a fixture in conftest.py is linked to `resident` via
    unit_a.registered_resident. We control expo_push_token on the resident
    to exercise both branches of the conditional dispatch.
    """

    def test_log_package_dispatches_task_when_resident_has_token(
        self,
        complex_a: Any,
        unit_a: Any,
        resident: Any,
        security_user: Any,
        django_capture_on_commit_callbacks: Any,
        mocker: Any,
    ) -> None:
        """
        Happy path — unit has a registered resident with an expo_push_token.
        notify_package_arrived.apply_async must be called once with the correct
        [package_id, complex_id] args after the transaction commits.
        """
        # Ensure resident has a push token (conftest UserFactory may not set one)
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
        """
        Resident exists but has no expo_push_token (opted out / never registered
        the device). No task must be enqueued — silent no-op.
        """
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
        """
        Unit has no registered resident (vacant unit).
        No task must be enqueued — silent no-op.
        Note: unit_a fixture default has no registered_resident unless `resident`
        fixture is also requested (which sets it). We don't request `resident` here.
        """
        # Ensure unit has no resident (explicit guard)
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
