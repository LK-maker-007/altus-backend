from __future__ import annotations

from typing import Any

import pytest
from django.core.cache import cache

from tests.factories.announcement_factory import AnnouncementFactory
from tests.factories.emergency_factory import EmergencyContactFactory
from tests.factories.lost_found_factory import LostFoundReportFactory


@pytest.mark.django_db
class TestAnnouncementListView:

    def test_resident_sees_active_announcements(
        self, auth_client: Any, complex_a: Any
    ) -> None:
        AnnouncementFactory(complex=complex_a, title="Meeting Today", is_active=True)
        AnnouncementFactory(complex=complex_a, title="Park Closed", is_active=True)

        response = auth_client.get("/api/v1/community/announcements/")

        assert response.status_code == 200
        assert "results" in response.data
        assert len(response.data["results"]) == 2

    def test_inactive_announcements_excluded(
        self, auth_client: Any, complex_a: Any
    ) -> None:
        AnnouncementFactory(complex=complex_a, title="Active", is_active=True)
        AnnouncementFactory(complex=complex_a, title="Archived", is_active=False)

        response = auth_client.get("/api/v1/community/announcements/")

        assert response.status_code == 200
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["title"] == "Active"

    def test_category_filter_returns_matching_only(
        self, auth_client: Any, complex_a: Any
    ) -> None:
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
        response = api_client.get("/api/v1/community/announcements/")
        assert response.status_code in (401, 403)


@pytest.mark.django_db
class TestEmergencyContactListView:

    def test_cache_miss_returns_contacts_from_db(
        self, auth_client: Any, complex_a: Any, resident: Any
    ) -> None:
        cache.clear()
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
        cache.clear()
        EmergencyContactFactory(
            complex=complex_a,
            name="Ambulance",
            display_order=1,
            phone_number="+911234567892",
        )

        response_1 = auth_client.get("/api/v1/emergency/")
        assert response_1.status_code == 200

        response_2 = auth_client.get("/api/v1/emergency/")
        assert response_2.status_code == 200
        assert response_2.data["results"] == response_1.data["results"]

    def test_inactive_contacts_excluded(self, auth_client: Any, complex_a: Any) -> None:
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
        cache.clear()
        response = auth_client.get("/api/v1/emergency/")
        assert response.status_code == 200
        assert response.data["results"] == []

    def test_unauthenticated_returns_403(self, api_client: Any) -> None:
        response = api_client.get("/api/v1/emergency/")
        assert response.status_code in (401, 403)

    def test_null_complex_user_forbidden(self, db: Any) -> None:
        from rest_framework.test import APIClient

        from apps.users.models import UserRole
        from tests.factories.user_factory import UserFactory

        cache.clear()
        platform_admin = UserFactory(role=UserRole.PLATFORM_ADMIN, complex=None)
        client = APIClient()
        client.force_authenticate(user=platform_admin)

        response = client.get("/api/v1/emergency/")
        assert response.status_code == 403


@pytest.mark.django_db
class TestLostFoundListCreateView:

    def test_list_returns_all_reports(
        self, auth_client: Any, complex_a: Any, resident: Any
    ) -> None:
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
        response = api_client.get("/api/v1/lost-found/")
        assert response.status_code in (401, 403)

    def test_null_complex_user_cannot_list_or_create(self, db: Any) -> None:
        from rest_framework.test import APIClient

        from apps.users.models import UserRole
        from tests.factories.user_factory import UserFactory

        LostFoundReportFactory()

        platform_admin = UserFactory(role=UserRole.PLATFORM_ADMIN, complex=None)
        client = APIClient()
        client.force_authenticate(user=platform_admin)

        list_response = client.get("/api/v1/lost-found/")
        assert list_response.status_code == 403

        create_response = client.post(
            "/api/v1/lost-found/",
            data={"report_type": "lost", "description": "x", "location": "lobby"},
            format="json",
        )
        assert create_response.status_code == 403
