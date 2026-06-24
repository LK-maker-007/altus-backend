from __future__ import annotations

import uuid
from typing import Any

import pytest
from django.utils import timezone

from apps.packages.exceptions import PackageAlreadyCollectedError, PackageNotFoundError
from apps.packages.models import PackageStatus
from apps.packages.services import PackageService
from tests.factories.package_factory import PackageFactory
from tests.factories.unit_factory import UnitFactory
from tests.factories.user_factory import UserFactory


@pytest.mark.django_db
class TestLogPackage:

    def test_log_package_creates_pending_package(
        self, complex_a: Any, unit_a: Any, security_user: Any
    ) -> None:
        package = PackageService.log_package(
            security_guard=security_user,
            unit_number=unit_a.unit_number,
            building_block=unit_a.building_block,
            complex_id=str(complex_a.id),
            description="Amazon box",
            notes="Left at gate",
        )

        assert package.status == PackageStatus.PENDING
        assert package.description == "Amazon box"
        assert package.notes == "Left at gate"
        assert package.logged_by_id == security_user.id
        assert package.unit_id == unit_a.id
        assert package.collected_at is None
        assert package.collected_by is None

    def test_log_package_unit_not_found_raises_error(
        self, complex_a: Any, security_user: Any
    ) -> None:
        with pytest.raises(PackageNotFoundError):
            PackageService.log_package(
                security_guard=security_user,
                unit_number="Z-999",
                building_block="Z",
                complex_id=str(complex_a.id),
                description="Mystery box",
                notes="",
            )

    def test_log_package_wrong_complex_raises_error(
        self,
        complex_a: Any,
        complex_b: Any,
        unit_a: Any,
        security_user: Any,
    ) -> None:
        with pytest.raises(PackageNotFoundError):
            PackageService.log_package(
                security_guard=security_user,
                unit_number=unit_a.unit_number,
                building_block=unit_a.building_block,
                complex_id=str(complex_b.id),
                description="Box",
                notes="",
            )


@pytest.mark.django_db
class TestLogPackageOnCommit:

    def test_no_task_when_unit_has_no_resident(
        self,
        complex_a: Any,
        security_user: Any,
        mocker: Any,
        django_capture_on_commit_callbacks: Any,
    ) -> None:
        unit = UnitFactory(
            complex=complex_a,
            unit_number="T-001",
            building_block="T",
        )
        assert unit.registered_resident is None

        mock_apply = mocker.patch(
            "apps.packages.tasks.notify_package_arrived.apply_async"
        )

        with django_capture_on_commit_callbacks(execute=True):
            PackageService.log_package(
                security_guard=security_user,
                unit_number=unit.unit_number,
                building_block=unit.building_block,
                complex_id=str(complex_a.id),
                description="Box",
                notes="",
            )

        mock_apply.assert_not_called()

    def test_no_task_when_resident_has_no_push_token(
        self,
        complex_a: Any,
        security_user: Any,
        mocker: Any,
        django_capture_on_commit_callbacks: Any,
    ) -> None:
        unit = UnitFactory(
            complex=complex_a,
            unit_number="T-002",
            building_block="T",
        )
        resident = UserFactory(
            complex=complex_a,
            phone_number="+919000022200",
            expo_push_token="",
        )
        unit.registered_resident = resident
        unit.save(update_fields=["registered_resident_id"])

        mock_apply = mocker.patch(
            "apps.packages.tasks.notify_package_arrived.apply_async"
        )

        with django_capture_on_commit_callbacks(execute=True):
            PackageService.log_package(
                security_guard=security_user,
                unit_number=unit.unit_number,
                building_block=unit.building_block,
                complex_id=str(complex_a.id),
                description="Box",
                notes="",
            )

        mock_apply.assert_not_called()

    def test_task_enqueued_when_resident_has_push_token(
        self,
        complex_a: Any,
        security_user: Any,
        mocker: Any,
        django_capture_on_commit_callbacks: Any,
    ) -> None:
        unit = UnitFactory(
            complex=complex_a,
            unit_number="T-003",
            building_block="T",
        )
        resident = UserFactory(
            complex=complex_a,
            phone_number="+919000022201",
            expo_push_token="ExponentPushToken[resident-device-xyz]",
        )
        unit.registered_resident = resident
        unit.save(update_fields=["registered_resident_id"])

        mock_apply = mocker.patch(
            "apps.packages.tasks.notify_package_arrived.apply_async"
        )

        with django_capture_on_commit_callbacks(execute=True):
            package = PackageService.log_package(
                security_guard=security_user,
                unit_number=unit.unit_number,
                building_block=unit.building_block,
                complex_id=str(complex_a.id),
                description="Large parcel",
                notes="",
            )

        mock_apply.assert_called_once_with(
            args=(
                str(package.id),
                str(complex_a.id),
            ),
        )


@pytest.mark.django_db
class TestMarkCollected:

    def test_mark_collected_transitions_to_collected(
        self, complex_a: Any, unit_a: Any, security_user: Any, resident: Any
    ) -> None:
        package = PackageFactory(
            complex=complex_a,
            unit=unit_a,
            logged_by=security_user,
            status=PackageStatus.PENDING,
        )

        result = PackageService.mark_collected(
            package_id=str(package.id),
            complex_id=str(complex_a.id),
            collector=resident,
        )

        assert result.status == PackageStatus.COLLECTED
        assert result.collected_at is not None
        assert result.collected_at <= timezone.now()
        assert result.collected_by_id == resident.id

    def test_mark_collected_package_not_found_raises_error(
        self, complex_a: Any, resident: Any
    ) -> None:
        with pytest.raises(PackageNotFoundError):
            PackageService.mark_collected(
                package_id=str(uuid.uuid4()),
                complex_id=str(complex_a.id),
                collector=resident,
            )

    def test_mark_collected_wrong_complex_raises_error(
        self,
        complex_a: Any,
        complex_b: Any,
        unit_a: Any,
        security_user: Any,
        resident: Any,
    ) -> None:
        package = PackageFactory(
            complex=complex_a,
            unit=unit_a,
            logged_by=security_user,
        )

        with pytest.raises(PackageNotFoundError):
            PackageService.mark_collected(
                package_id=str(package.id),
                complex_id=str(complex_b.id),
                collector=resident,
            )

    def test_mark_collected_already_collected_raises_error(
        self, complex_a: Any, unit_a: Any, security_user: Any, resident: Any
    ) -> None:
        package = PackageFactory(
            complex=complex_a,
            unit=unit_a,
            logged_by=security_user,
            status=PackageStatus.COLLECTED,
            collected_at=timezone.now(),
            collected_by=resident,
        )

        with pytest.raises(PackageAlreadyCollectedError):
            PackageService.mark_collected(
                package_id=str(package.id),
                complex_id=str(complex_a.id),
                collector=resident,
            )

    def test_mark_collected_persists_to_database(
        self, complex_a: Any, unit_a: Any, security_user: Any, resident: Any
    ) -> None:
        package = PackageFactory(
            complex=complex_a,
            unit=unit_a,
            logged_by=security_user,
            status=PackageStatus.PENDING,
        )

        PackageService.mark_collected(
            package_id=str(package.id),
            complex_id=str(complex_a.id),
            collector=resident,
        )

        package.refresh_from_db()
        assert package.status == PackageStatus.COLLECTED
        assert package.collected_by_id == resident.id
