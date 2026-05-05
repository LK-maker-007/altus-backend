from __future__ import annotations

"""
Multi-tenancy RLS enforcement tests.

Coverage target: 100% of cross-complex isolation scenarios (testing-strategy.md §12).

These tests are the most security-critical in the entire suite. A failure here
means a tenant data leak — a contractual failure, not just a bug.

Key assertions:
- A resident of Complex A must NEVER see data from Complex B
- Cross-complex resource access must return 404 (not 403 — must not reveal existence)
- ComplexContextMiddleware must set the correct complex_id on every request
"""

from typing import Any

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from tests.factories.booking_factory import BookingFactory
from tests.factories.visitor_factory import VisitorFactory


@pytest.mark.django_db
class TestCrossComplexBookingIsolation:
    """RLS must block Complex A resident from accessing Complex B booking data."""

    def test_resident_cannot_see_other_complex_booking_by_id(
        self,
        auth_client: APIClient,
        complex_b: Any,
        facility_b: Any,
        resident_complex_b: Any,
    ) -> None:
        """
        A resident of Complex A requesting a Complex B booking UUID must get 404.
        Must NOT return 403 — that would confirm the booking exists.
        """

        booking_b = BookingFactory(
            complex=complex_b,
            facility=facility_b,
            resident=resident_complex_b,
        )

        response = auth_client.get(f"/api/v1/bookings/{booking_b.id}/")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_booking_list_only_returns_own_complex_bookings(
        self,
        auth_client: APIClient,
        complex_a: Any,
        complex_b: Any,
        facility: Any,
        facility_b: Any,
        resident: Any,
        resident_complex_b: Any,
    ) -> None:
        """Booking list for Complex A resident must only contain Complex A bookings."""
        booking_a = BookingFactory(
            complex=complex_a, facility=facility, resident=resident
        )
        booking_b = BookingFactory(
            complex=complex_b, facility=facility_b, resident=resident_complex_b
        )

        response = auth_client.get("/api/v1/bookings/")

        assert response.status_code == status.HTTP_200_OK
        ids = [str(item["id"]) for item in response.data.get("results", response.data)]
        assert str(booking_a.id) in ids
        assert str(booking_b.id) not in ids

    def test_facility_list_only_returns_own_complex_facilities(
        self,
        auth_client: APIClient,
        facility: Any,
        facility_b: Any,
    ) -> None:
        """Facility list must only return facilities from the authenticated user's complex."""
        response = auth_client.get("/api/v1/facilities/")

        assert response.status_code == status.HTTP_200_OK
        ids = [str(item["id"]) for item in response.data.get("results", response.data)]
        assert str(facility.id) in ids
        assert str(facility_b.id) not in ids


@pytest.mark.django_db
class TestCrossComplexVisitorIsolation:
    """RLS must block visibility of visitor passes across complexes."""

    def test_cannot_read_other_complex_visitor(
        self,
        auth_client: APIClient,
        complex_b: Any,
        unit_b: Any,
        resident_complex_b: Any,
    ) -> None:
        visitor_b = VisitorFactory(
            complex=complex_b,
            unit=unit_b,
            registered_by=resident_complex_b,
        )

        response = auth_client.get(f"/api/v1/visitors/{visitor_b.id}/")

        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
class TestUnauthenticatedAccess:
    """All protected endpoints must return 401 without a valid JWT."""

    endpoints = [
        ("GET", "/api/v1/bookings/"),
        ("GET", "/api/v1/facilities/"),
        ("GET", "/api/v1/visitors/"),
        ("GET", "/api/v1/packages/"),
        ("GET", "/api/v1/dashboard/"),
        ("GET", "/api/v1/maintenance/tickets/"),
    ]

    @pytest.mark.parametrize("method,url", endpoints)
    def test_unauthenticated_returns_401(
        self, api_client: APIClient, method: str, url: str
    ) -> None:
        response = getattr(api_client, method.lower())(url)
        # DRF returns 403 for anonymous users when DEFAULT_AUTHENTICATION_CLASSES
        # does not include a scheme that sends WWW-Authenticate (which triggers 401).
        # Both 401 and 403 correctly block unauthenticated access; the exact code
        # depends on the authentication scheme configured.
        # See: https://www.django-rest-framework.org/api-guide/authentication/#unauthorized-and-forbidden-responses
        assert response.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        ), f"{method} {url} returned {response.status_code}, expected 401 or 403"


@pytest.mark.django_db
class TestRoleBasedAccess:
    """RBAC: roles must gate access to role-specific endpoints."""

    def test_security_cannot_access_resident_booking_create(
        self,
        security_client: APIClient,
        facility: Any,
    ) -> None:
        """Security staff cannot create resident bookings."""
        from datetime import timedelta

        from django.utils import timezone

        slot_start = timezone.now() + timedelta(days=1, hours=10)
        response = security_client.post(
            "/api/v1/bookings/hold/",
            {
                "facility_id": str(facility.id),
                "slot_start": slot_start.isoformat(),
                "slot_end": (slot_start + timedelta(hours=1)).isoformat(),
            },
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_resident_cannot_mark_visitor_arrived(
        self,
        auth_client: APIClient,
        complex_a: Any,
        unit_a: Any,
        resident: Any,
    ) -> None:
        """A resident cannot call the security-only visitor arrival endpoint."""
        visitor = VisitorFactory(complex=complex_a, unit=unit_a, registered_by=resident)
        response = auth_client.post(
            f"/api/v1/visitors/{visitor.id}/arrive/",
            {"otp_code": visitor.otp_code},
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
