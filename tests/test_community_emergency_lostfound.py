from __future__ import annotations

"""
Community, Emergency Contact, and Lost & Found view tests.

Covers:
  apps/community/views.py      74%  → category filter branch (lines 30-34)
  apps/emergency/views.py      58%  → cache hit + cache miss (lines 40-55)
  apps/lost_found/views.py     68%  → type filter (28-32), POST (38-39)

Bug fix included: community/views.py had a production bug where global
CursorPagination ordering="-created" (field is "created_at") caused a FieldError.
Fixed by adding _AnnouncementCursorPagination(ordering="-created_at").
"""

from typing import Any

import pytest
from django.core.cache import cache

from tests.factories.announcement_factory import AnnouncementFactory
from tests.factories.emergency_factory import EmergencyContactFactory
from tests.factories.lost_found_factory import LostFoundReportFactory

# -- AnnouncementListView (community) ----------------------------------------


@pytest.mark.django_db
class TestAnnouncementListView:
    """GET /api/v1/community/announcements/ -- list active announcements."""

    def test_resident_sees_active_announcements(
        self, auth_client: Any, complex_a: Any
    ) -> None:
        """Happy path -- 2 active announcements -> 2 results."""
        AnnouncementFactory(complex=complex_a, title="Meeting Today", is_active=True)
        AnnouncementFactory(complex=complex_a, title="Park Closed", is_active=True)

        response = auth_client.get("/api/v1/community/announcements/")

        assert response.status_code == 200
        assert "results" in response.data
        assert len(response.data["results"]) == 2

    def test_inactive_announcements_excluded(
        self, auth_client: Any, complex_a: Any
    ) -> None:
        """is_active=False announcements are excluded."""
        AnnouncementFactory(complex=complex_a, title="Active", is_active=True)
        AnnouncementFactory(complex=complex_a, title="Archived", is_active=False)

        response = auth_client.get("/api/v1/community/announcements/")

        assert response.status_code == 200
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["title"] == "Active"

    def test_category_filter_returns_matching_only(
        self, auth_client: Any, complex_a: Any
    ) -> None:
        """?category= filters by announcement category -- covers lines 30-34."""
        AnnouncementFactory(
            complex=complex_a,
            title="General Notice",
            is_active=True,
            category="general",
        )
        AnnouncementFactory(
            complex=complex_a,
            title="Maintenance Update",
            is_active=True,
            category="maintenance",
        )

        response = auth_client.get("/api/v1/community/announcements/?category=general")

        assert response.status_code == 200
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["title"] == "General Notice"

    def test_unauthenticated_returns_403(self, api_client: Any) -> None:
        """IsAuthenticated blocks anonymous access."""
        response = api_client.get("/api/v1/community/announcements/")
        assert response.status_code in (401, 403)


# -- EmergencyContactListView -------------------------------------------------


@pytest.mark.django_db
class TestEmergencyContactListView:
    """GET /api/v1/emergency/ -- cache-aside pattern (1-hour TTL)."""

    def test_cache_miss_returns_contacts_from_db(
        self, auth_client: Any, complex_a: Any, resident: Any
    ) -> None:
        """
        Cache miss path -- cache is empty, DB queried, result cached.
        Covers lines 45-55 of emergency/views.py.
        """
        cache.clear()  # ensure cold cache
        EmergencyContactFactory(
            complex=complex_a,
            name="Police",
            display_order=1,
            phone_number="+911234567890",
        )
        EmergencyContactFactory(
            complex=complex_a,
            name="Fire Station",
            display_order=2,
            phone_number="+911234567891",
        )

        response = auth_client.get("/api/v1/emergency/")

        assert response.status_code == 200
        assert len(response.data["results"]) == 2
        names = {r["name"] for r in response.data["results"]}
        assert names == {"Police", "Fire Station"}

    def test_cache_hit_returns_cached_data(
        self, auth_client: Any, complex_a: Any, resident: Any
    ) -> None:
        """
        Cache hit path -- second request returns from Redis cache.
        Covers line 40-43 of emergency/views.py (early return on cache hit).
        """
        cache.clear()
        EmergencyContactFactory(
            complex=complex_a,
            name="Ambulance",
            display_order=1,
            phone_number="+911234567892",
        )

        # First request -- populates cache
        response_1 = auth_client.get("/api/v1/emergency/")
        assert response_1.status_code == 200

        # Second request -- must serve from cache (same data, no DB hit)
        response_2 = auth_client.get("/api/v1/emergency/")
        assert response_2.status_code == 200
        assert response_2.data["results"] == response_1.data["results"]

    def test_inactive_contacts_excluded(self, auth_client: Any, complex_a: Any) -> None:
        """is_active=False contacts are excluded (DB query filter)."""
        cache.clear()
        EmergencyContactFactory(
            complex=complex_a,
            name="Active Hotline",
            is_active=True,
            phone_number="+911234567893",
        )
        EmergencyContactFactory(
            complex=complex_a,
            name="Closed Line",
            is_active=False,
            phone_number="+911234567894",
        )

        response = auth_client.get("/api/v1/emergency/")

        assert response.status_code == 200
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["name"] == "Active Hotline"

    def test_empty_returns_200(self, auth_client: Any, complex_a: Any) -> None:
        """No contacts -> empty results, not 404."""
        cache.clear()
        response = auth_client.get("/api/v1/emergency/")
        assert response.status_code == 200
        assert response.data["results"] == []

    def test_unauthenticated_returns_403(self, api_client: Any) -> None:
        """IsAuthenticated blocks anonymous access."""
        response = api_client.get("/api/v1/emergency/")
        assert response.status_code in (401, 403)


# -- LostFoundListCreateView --------------------------------------------------


@pytest.mark.django_db
class TestLostFoundListCreateView:
    """GET + POST /api/v1/lost-found/ -- list and create lost/found reports."""

    def test_list_returns_all_reports(
        self, auth_client: Any, complex_a: Any, resident: Any
    ) -> None:
        """Happy path -- 2 reports visible to authenticated user."""
        LostFoundReportFactory(
            complex=complex_a, reported_by=resident, report_type="lost"
        )
        LostFoundReportFactory(
            complex=complex_a, reported_by=resident, report_type="found"
        )

        response = auth_client.get("/api/v1/lost-found/")

        assert response.status_code == 200
        assert "results" in response.data
        assert len(response.data["results"]) == 2

    def test_type_filter_returns_matching_only(
        self, auth_client: Any, complex_a: Any, resident: Any
    ) -> None:
        """?type=lost returns only lost reports -- covers lines 28-32."""
        LostFoundReportFactory(
            complex=complex_a, reported_by=resident, report_type="lost"
        )
        LostFoundReportFactory(
            complex=complex_a, reported_by=resident, report_type="found"
        )

        response = auth_client.get("/api/v1/lost-found/?type=lost")

        assert response.status_code == 200
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["report_type"] == "lost"

    def test_security_can_create_report(
        self, security_client: Any, complex_a: Any, security_user: Any
    ) -> None:
        """
        All authenticated roles (including security) can POST reports.
        Covers perform_create lines 38-39 (reported_by + complex_id set from user).
        """
        response = security_client.post(
            "/api/v1/lost-found/",
            data={
                "report_type": "found",
                "description": "Blue bicycle found near building entrance",
                "location": "Near Block A entrance",
            },
            format="json",
        )
        assert response.status_code == 201
        assert response.data["report_type"] == "found"

    def test_resident_can_create_lost_report(
        self, auth_client: Any, complex_a: Any, resident: Any
    ) -> None:
        """Resident creates a lost report -> 201 with correct report_type."""
        response = auth_client.post(
            "/api/v1/lost-found/",
            data={
                "report_type": "lost",
                "description": "Lost my car keys near the gym",
                "location": "Near the gym on Ground Floor",
            },
            format="json",
        )
        assert response.status_code == 201
        assert response.data["report_type"] == "lost"

    def test_unauthenticated_returns_403(self, api_client: Any) -> None:
        """IsAuthenticated blocks anonymous access."""
        response = api_client.get("/api/v1/lost-found/")
        assert response.status_code in (401, 403)
