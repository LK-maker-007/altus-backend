from __future__ import annotations

from typing import Any

import pytest
from django.utils import timezone

from apps.packages.models import Package, PackageStatus
from tests.factories.package_factory import PackageFactory
from tests.factories.unit_factory import UnitFactory


@pytest.mark.django_db
class TestPackageListView:

    def test_resident_sees_own_packages(
        self,
        auth_client: Any,
        complex_a: Any,
        unit_a: Any,
        resident: Any,
        security_user: Any,
    ) -> None:
        PackageFactory(complex=complex_a, unit=unit_a, logged_by=security_user)
        PackageFactory(complex=complex_a, unit=unit_a, logged_by=security_user)

        response = auth_client.get("/api/v1/packages/")

        assert response.status_code == 200
        assert len(response.data["results"]) == 2

    def test_resident_can_filter_by_status(
        self,
        auth_client: Any,
        complex_a: Any,
        unit_a: Any,
        resident: Any,
        security_user: Any,
    ) -> None:
        PackageFactory(
            complex=complex_a,
            unit=unit_a,
            logged_by=security_user,
            status=PackageStatus.PENDING,
        )
        PackageFactory(
            complex=complex_a,
            unit=unit_a,
            logged_by=security_user,
            status=PackageStatus.COLLECTED,
            collected_at=timezone.now(),
            collected_by=resident,
        )

        response = auth_client.get("/api/v1/packages/?status=pending")

        assert response.status_code == 200
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["status"] == PackageStatus.PENDING

    def test_unauthenticated_returns_401(self, api_client: Any) -> None:
        response = api_client.get("/api/v1/packages/")
        assert response.status_code in (401, 403)

    def test_empty_list_when_no_packages(
        self, auth_client: Any, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
        response = auth_client.get("/api/v1/packages/")
        assert response.status_code == 200
        assert response.data["results"] == []


@pytest.mark.django_db
class TestPackageLogView:

    def test_security_logs_package_returns_201(
        self,
        security_client: Any,
        complex_a: Any,
        unit_a: Any,
        security_user: Any,
    ) -> None:
        response = security_client.post(
            "/api/v1/security/packages/log/",
            data={
                "unit_number": unit_a.unit_number,
                "building_block": unit_a.building_block,
                "description": "Amazon parcel",
                "notes": "Left at gate",
            },
            format="json",
        )

        assert response.status_code == 201
        assert response.data["status"] == PackageStatus.PENDING
        assert response.data["description"] == "Amazon parcel"
        assert Package.objects.filter(unit=unit_a).count() == 1

    def test_invalid_unit_returns_404_or_error(
        self,
        security_client: Any,
        complex_a: Any,
    ) -> None:
        response = security_client.post(
            "/api/v1/security/packages/log/",
            data={
                "unit_number": "Z-999",
                "building_block": "Z",
                "description": "Unknown",
                "notes": "",
            },
            format="json",
        )

        assert response.status_code >= 400

    def test_resident_cannot_log_package(
        self, auth_client: Any, complex_a: Any, unit_a: Any
    ) -> None:
        response = auth_client.post(
            "/api/v1/security/packages/log/",
            data={
                "unit_number": unit_a.unit_number,
                "building_block": unit_a.building_block,
                "description": "Test",
                "notes": "",
            },
            format="json",
        )
        assert response.status_code == 403

    def test_missing_description_returns_400(
        self, security_client: Any, complex_a: Any, unit_a: Any
    ) -> None:
        response = security_client.post(
            "/api/v1/security/packages/log/",
            data={
                "unit_number": unit_a.unit_number,
                "building_block": unit_a.building_block,
            },
            format="json",
        )
        assert response.status_code == 400


@pytest.mark.django_db
class TestPackageCollectView:

    def test_resident_can_collect_own_package(
        self,
        auth_client: Any,
        complex_a: Any,
        unit_a: Any,
        resident: Any,
        security_user: Any,
    ) -> None:
        package = PackageFactory(
            complex=complex_a,
            unit=unit_a,
            logged_by=security_user,
            status=PackageStatus.PENDING,
        )

        response = auth_client.post(f"/api/v1/packages/{package.id}/collect/")

        assert response.status_code == 200
        assert response.data["status"] == PackageStatus.COLLECTED
        assert response.data["collected_at"] is not None
        package.refresh_from_db()
        assert package.status == PackageStatus.COLLECTED

    def test_already_collected_returns_error(
        self,
        auth_client: Any,
        complex_a: Any,
        unit_a: Any,
        resident: Any,
        security_user: Any,
    ) -> None:
        package = PackageFactory(
            complex=complex_a,
            unit=unit_a,
            logged_by=security_user,
            status=PackageStatus.COLLECTED,
            collected_at=timezone.now(),
            collected_by=resident,
        )

        response = auth_client.post(f"/api/v1/packages/{package.id}/collect/")

        assert response.status_code >= 400

    def test_unauthenticated_collect_returns_401(
        self, api_client: Any, complex_a: Any, unit_a: Any, security_user: Any
    ) -> None:
        package = PackageFactory(
            complex=complex_a, unit=unit_a, logged_by=security_user
        )
        response = api_client.post(f"/api/v1/packages/{package.id}/collect/")
        assert response.status_code in (401, 403)

    def test_resident_cannot_collect_another_units_package(
        self,
        auth_client: Any,
        complex_a: Any,
        resident: Any,
        security_user: Any,
    ) -> None:
        other_unit = UnitFactory(complex=complex_a)
        package = PackageFactory(
            complex=complex_a,
            unit=other_unit,
            logged_by=security_user,
            status=PackageStatus.PENDING,
        )

        response = auth_client.post(f"/api/v1/packages/{package.id}/collect/")

        assert response.status_code == 403
        package.refresh_from_db()
        assert package.status == PackageStatus.PENDING
        assert package.collected_at is None

    def test_security_can_collect_any_units_package(
        self,
        security_client: Any,
        complex_a: Any,
        unit_a: Any,
        security_user: Any,
    ) -> None:
        package = PackageFactory(
            complex=complex_a,
            unit=unit_a,
            logged_by=security_user,
            status=PackageStatus.PENDING,
        )

        response = security_client.post(f"/api/v1/packages/{package.id}/collect/")

        assert response.status_code == 200
        package.refresh_from_db()
        assert package.status == PackageStatus.COLLECTED
