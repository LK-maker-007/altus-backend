from __future__ import annotations

"""
Facilities API view tests -- covering the 45% gap in facilities/views.py.

Targets (facilities/views.py lines):
  36-49   FacilityListView.get (list, category filter, empty)
  61       FacilityDetailView.get (found)
  71-75   FacilityDetailView.get (not found)
  86-92   FacilitySlotsView.get (happy path, missing date, bad date, past date)
  114-130  _parse_and_validate_date (validation edge cases)

FacilitySlotStreamView is an SSE endpoint (text/event-stream). It runs an
infinite while loop inside a generator -- not testable with DRF APIClient
without mocking time.sleep. We test the entry guard (date validation, auth)
but NOT the full stream iteration to avoid hanging tests.
"""

import uuid
from datetime import date, timedelta
from typing import Any

import pytest

from apps.facilities.models import FacilityCategory
from tests.factories.facility_factory import FacilityFactory

# -- FacilityListView ---------------------------------------------------------


@pytest.mark.django_db
class TestFacilityListView:
    """GET /api/v1/facilities/ -- resident/admin lists all active facilities."""

    def test_resident_sees_all_active_facilities(
        self, auth_client: Any, complex_a: Any
    ) -> None:
        """Happy path -- 3 facilities created -> 3 returned."""
        FacilityFactory(
            complex=complex_a, name="Gym", category=FacilityCategory.SPORTS_FITNESS
        )
        FacilityFactory(
            complex=complex_a, name="Pool", category=FacilityCategory.SPORTS_FITNESS
        )
        FacilityFactory(
            complex=complex_a, name="Library", category=FacilityCategory.SOCIAL_SPACES
        )

        response = auth_client.get("/api/v1/facilities/")

        assert response.status_code == 200
        assert len(response.data["results"]) == 3
        names = {r["name"] for r in response.data["results"]}
        assert names == {"Gym", "Pool", "Library"}

    def test_category_filter_returns_matching_only(
        self, auth_client: Any, complex_a: Any
    ) -> None:
        """?category=sports_fitness returns only SPORTS_FITNESS facilities."""
        FacilityFactory(
            complex=complex_a, name="Gym", category=FacilityCategory.SPORTS_FITNESS
        )
        FacilityFactory(
            complex=complex_a, name="Library", category=FacilityCategory.SOCIAL_SPACES
        )

        response = auth_client.get("/api/v1/facilities/?category=sports_fitness")

        assert response.status_code == 200
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["name"] == "Gym"
        assert (
            response.data["results"][0]["category"] == FacilityCategory.SPORTS_FITNESS
        )

    def test_inactive_facilities_not_returned(
        self, auth_client: Any, complex_a: Any
    ) -> None:
        """is_active=False facilities must never appear in the list."""
        FacilityFactory(complex=complex_a, name="Active Gym", is_active=True)
        FacilityFactory(complex=complex_a, name="Closed Pool", is_active=False)

        response = auth_client.get("/api/v1/facilities/")

        assert response.status_code == 200
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["name"] == "Active Gym"

    def test_empty_complex_returns_empty_list(
        self, auth_client: Any, complex_a: Any
    ) -> None:
        """No facilities in complex -> empty results, not 404."""
        response = auth_client.get("/api/v1/facilities/")
        assert response.status_code == 200
        assert response.data["results"] == []

    def test_unauthenticated_returns_403(self, api_client: Any) -> None:
        """IsAuthenticated + IsResidentOrAdmin blocks anonymous access."""
        response = api_client.get("/api/v1/facilities/")
        assert response.status_code in (401, 403)

    def test_security_user_cannot_list_facilities(
        self, security_client: Any, complex_a: Any
    ) -> None:
        """IsResidentOrAdmin blocks SECURITY role."""
        FacilityFactory(complex=complex_a)
        response = security_client.get("/api/v1/facilities/")
        assert response.status_code == 403


# -- FacilityDetailView -------------------------------------------------------


@pytest.mark.django_db
class TestFacilityDetailView:
    """GET /api/v1/facilities/{id}/ -- single facility detail."""

    def test_resident_gets_facility_detail(
        self, auth_client: Any, complex_a: Any
    ) -> None:
        """Happy path -- valid facility_id -> 200 with full schema."""
        facility = FacilityFactory(complex=complex_a, name="Tennis Court")

        response = auth_client.get(f"/api/v1/facilities/{facility.id}/")

        assert response.status_code == 200
        assert str(response.data["id"]) == str(facility.id)
        assert response.data["name"] == "Tennis Court"
        assert "operating_hours" in response.data

    def test_nonexistent_facility_returns_error(
        self, auth_client: Any, complex_a: Any
    ) -> None:
        """Unknown facility_id -> FacilityNotFoundError -> non-2xx."""
        response = auth_client.get(f"/api/v1/facilities/{uuid.uuid4()}/")
        assert response.status_code >= 400

    def test_inactive_facility_returns_error(
        self, auth_client: Any, complex_a: Any
    ) -> None:
        """is_active=False facility -> treated as not found (no info leak)."""
        facility = FacilityFactory(complex=complex_a, is_active=False)
        response = auth_client.get(f"/api/v1/facilities/{facility.id}/")
        assert response.status_code >= 400

    def test_unauthenticated_detail_returns_403(
        self, api_client: Any, complex_a: Any
    ) -> None:
        """Unauthenticated request rejected."""
        facility = FacilityFactory(complex=complex_a)
        response = api_client.get(f"/api/v1/facilities/{facility.id}/")
        assert response.status_code in (401, 403)


# -- FacilitySlotsView --------------------------------------------------------


@pytest.mark.django_db
class TestFacilitySlotsView:
    """GET /api/v1/facilities/{id}/slots/?date=YYYY-MM-DD -- slot grid."""

    def _tomorrow(self) -> str:
        return (date.today() + timedelta(days=1)).isoformat()

    def test_valid_date_returns_slot_grid(
        self, auth_client: Any, complex_a: Any
    ) -> None:
        """
        Happy path -- valid date within booking window -> 200 + slots array.
        Response schema: {facility_id, date, slots: [{slot_start, slot_end, status}]}.
        """
        facility = FacilityFactory(complex=complex_a)
        tomorrow = self._tomorrow()

        response = auth_client.get(
            f"/api/v1/facilities/{facility.id}/slots/?date={tomorrow}"
        )

        assert response.status_code == 200
        assert str(response.data["facility_id"]) == str(facility.id)
        assert response.data["date"] == tomorrow
        assert isinstance(response.data["slots"], list)
        assert len(response.data["slots"]) > 0
        slot = response.data["slots"][0]
        assert "slot_start" in slot
        assert "slot_end" in slot
        assert "status" in slot

    def test_missing_date_param_returns_400(
        self, auth_client: Any, complex_a: Any
    ) -> None:
        """?date= missing -> validation error -> 400."""
        facility = FacilityFactory(complex=complex_a)
        response = auth_client.get(f"/api/v1/facilities/{facility.id}/slots/")
        assert response.status_code == 400

    def test_invalid_date_format_returns_400(
        self, auth_client: Any, complex_a: Any
    ) -> None:
        """?date=not-a-date -> ValueError -> 400."""
        facility = FacilityFactory(complex=complex_a)
        response = auth_client.get(
            f"/api/v1/facilities/{facility.id}/slots/?date=25-04-2026"
        )
        assert response.status_code == 400

    def test_past_date_returns_400(self, auth_client: Any, complex_a: Any) -> None:
        """?date in the past -> 400."""
        facility = FacilityFactory(complex=complex_a)
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        response = auth_client.get(
            f"/api/v1/facilities/{facility.id}/slots/?date={yesterday}"
        )
        assert response.status_code == 400

    def test_date_beyond_booking_window_returns_400(
        self, auth_client: Any, complex_a: Any
    ) -> None:
        """?date= beyond 7-day window -> 400."""
        facility = FacilityFactory(complex=complex_a)
        far_future = (date.today() + timedelta(days=30)).isoformat()
        response = auth_client.get(
            f"/api/v1/facilities/{facility.id}/slots/?date={far_future}"
        )
        assert response.status_code == 400

    def test_nonexistent_facility_slots_returns_error(
        self, auth_client: Any, complex_a: Any
    ) -> None:
        """Unknown facility_id with valid date -> FacilityNotFoundError."""
        tomorrow = self._tomorrow()
        response = auth_client.get(
            f"/api/v1/facilities/{uuid.uuid4()}/slots/?date={tomorrow}"
        )
        assert response.status_code >= 400

    def test_unauthenticated_slots_returns_403(
        self, api_client: Any, complex_a: Any
    ) -> None:
        """Unauthenticated slot request rejected."""
        facility = FacilityFactory(complex=complex_a)
        tomorrow = self._tomorrow()
        response = api_client.get(
            f"/api/v1/facilities/{facility.id}/slots/?date={tomorrow}"
        )
        assert response.status_code in (401, 403)


# -- FacilitySlotStreamView entry guard only ----------------------------------


@pytest.mark.django_db
class TestFacilitySlotStreamViewGuard:
    """
    FacilitySlotStreamView -- tests the entry guard only.

    The full SSE stream body (time.sleep + infinite while) is NOT exercised
    because it would hang indefinitely in the test runner. We test auth
    and date validation guards which cover lines 114-120.
    """

    def test_unauthenticated_stream_returns_403(
        self, api_client: Any, complex_a: Any
    ) -> None:
        """Unauthenticated SSE request rejected before starting the stream."""
        facility = FacilityFactory(complex=complex_a)
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        response = api_client.get(
            f"/api/v1/facilities/{facility.id}/slots/stream/?date={tomorrow}"
        )
        assert response.status_code in (401, 403)

    def test_stream_missing_date_returns_400(
        self, auth_client: Any, complex_a: Any
    ) -> None:
        """SSE stream without ?date= raises 400 before entering the generator."""
        facility = FacilityFactory(complex=complex_a)
        response = auth_client.get(f"/api/v1/facilities/{facility.id}/slots/stream/")
        assert response.status_code == 400
