from __future__ import annotations

"""
Package API view tests — US-024 (log), US-026 (collect), US-027 (list).

Uses DRF APIClient via conftest fixtures (auth_client, security_client).
API prefix: /api/v1/packages/  and  /api/v1/security/packages/

Uncovered lines this file targets (packages/views.py):
  35-51  PackageListView.get
  63-77  PackageLogView.post
  89-95  PackageCollectView.post
"""

from typing import Any

import pytest
from django.utils import timezone

from apps.packages.models import Package, PackageStatus
from tests.factories.package_factory import PackageFactory

# ── PackageListView ────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestPackageListView:
    """GET /api/v1/packages/ — resident sees their own unit's packages."""

    def test_resident_sees_own_packages(
        self,
        auth_client: Any,
        complex_a: Any,
        unit_a: Any,
        resident: Any,
        security_user: Any,
    ) -> None:
        """
        Happy path — resident with a unit linked gets their packages.
        """
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
        """
        ?status=pending filter returns only PENDING packages.
        COLLECTED package must not appear.
        """
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
        """Unauthenticated request must be rejected — IsAuthenticated + IsResident."""
        response = api_client.get("/api/v1/packages/")
        assert response.status_code in (401, 403)

    def test_empty_list_when_no_packages(
        self, auth_client: Any, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
        """No packages in unit → empty results list, not 404."""
        response = auth_client.get("/api/v1/packages/")
        assert response.status_code == 200
        assert response.data["results"] == []


# ── PackageLogView ─────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestPackageLogView:
    """POST /api/v1/security/packages/log/ — security guard logs incoming package."""

    def test_security_logs_package_returns_201(
        self,
        security_client: Any,
        complex_a: Any,
        unit_a: Any,
        security_user: Any,
    ) -> None:
        """
        Happy path — valid unit_number + building_block → 201 + package in DB.
        """
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
        """
        Unknown unit_number → PackageNotFoundError → non-2xx response.
        """
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
        """
        PackageLogView requires IsSecurityGuard — resident must be rejected.
        """
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
        """Missing required field 'description' → serializer validation → 400."""
        response = security_client.post(
            "/api/v1/security/packages/log/",
            data={
                "unit_number": unit_a.unit_number,
                "building_block": unit_a.building_block,
            },
            format="json",
        )
        assert response.status_code == 400


# ── PackageCollectView ─────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestPackageCollectView:
    """POST /api/v1/packages/{id}/collect/ — resident or security marks collected."""

    def test_resident_can_collect_own_package(
        self,
        auth_client: Any,
        complex_a: Any,
        unit_a: Any,
        resident: Any,
        security_user: Any,
    ) -> None:
        """
        Happy path — resident collects a PENDING package from their unit.
        Response contains id, status=collected, collected_at.
        """
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
        """
        Already-COLLECTED package → PackageAlreadyCollectedError → non-2xx.
        """
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
        """Unauthenticated collect attempt must be rejected — IsAuthenticated."""
        package = PackageFactory(
            complex=complex_a, unit=unit_a, logged_by=security_user
        )
        response = api_client.post(f"/api/v1/packages/{package.id}/collect/")
        assert response.status_code in (401, 403)
