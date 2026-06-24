from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone

from apps.visitors.models import Visitor, VisitorStatus
from tests.factories.visitor_factory import VisitorFactory


@pytest.mark.django_db
class TestVisitorListView:

    def test_resident_sees_own_visitors(
        self, auth_client: Any, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
        VisitorFactory(
            complex=complex_a,
            unit=unit_a,
            registered_by=resident,
            visitor_name="Alice",
            expected_from=timezone.now() + timedelta(hours=1),
            expected_until=timezone.now() + timedelta(hours=5),
        )
        VisitorFactory(
            complex=complex_a,
            unit=unit_a,
            registered_by=resident,
            visitor_name="Bob",
            expected_from=timezone.now() + timedelta(hours=2),
            expected_until=timezone.now() + timedelta(hours=6),
        )

        response = auth_client.get("/api/v1/visitors/")

        assert response.status_code == 200
        assert len(response.data["results"]) == 2
        names = {r["visitor_name"] for r in response.data["results"]}
        assert names == {"Alice", "Bob"}

    def test_resident_can_filter_by_status(
        self, auth_client: Any, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
        VisitorFactory(
            complex=complex_a,
            unit=unit_a,
            registered_by=resident,
            status=VisitorStatus.PENDING,
            expected_from=timezone.now() + timedelta(hours=1),
            expected_until=timezone.now() + timedelta(hours=5),
        )
        VisitorFactory(
            complex=complex_a,
            unit=unit_a,
            registered_by=resident,
            status=VisitorStatus.EXPIRED,
            expected_from=timezone.now() - timedelta(hours=5),
            expected_until=timezone.now() - timedelta(hours=1),
        )

        response = auth_client.get("/api/v1/visitors/?status=pending")

        assert response.status_code == 200
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["status"] == VisitorStatus.PENDING

    def test_resident_does_not_see_other_residents_visitors(
        self,
        auth_client: Any,
        complex_a: Any,
        unit_a: Any,
        resident: Any,
        resident_b: Any,
    ) -> None:
        VisitorFactory(
            complex=complex_a,
            unit=unit_a,
            registered_by=resident,
            visitor_name="My Visitor",
            expected_from=timezone.now() + timedelta(hours=1),
            expected_until=timezone.now() + timedelta(hours=5),
        )
        VisitorFactory(
            complex=complex_a,
            unit=unit_a,
            registered_by=resident_b,
            visitor_name="Other Visitor",
            expected_from=timezone.now() + timedelta(hours=1),
            expected_until=timezone.now() + timedelta(hours=5),
        )

        response = auth_client.get("/api/v1/visitors/")

        assert response.status_code == 200
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["visitor_name"] == "My Visitor"

    def test_unauthenticated_returns_403(self, api_client: Any) -> None:
        response = api_client.get("/api/v1/visitors/")
        assert response.status_code in (401, 403)

    def test_empty_list_returns_200(
        self, auth_client: Any, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
        response = auth_client.get("/api/v1/visitors/")
        assert response.status_code == 200
        assert response.data["results"] == []


@pytest.mark.django_db
class TestVisitorCreateView:

    def test_register_visitor_returns_201_with_otp(
        self, auth_client: Any, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
        expected_from = timezone.now() + timedelta(hours=2)
        expected_until = expected_from + timedelta(hours=4)

        response = auth_client.post(
            "/api/v1/visitors/",
            data={
                "visitor_name": "Jane Smith",
                "visitor_phone": "+919000099999",
                "expected_from": expected_from.isoformat(),
                "expected_until": expected_until.isoformat(),
            },
            format="json",
        )

        assert response.status_code == 201
        assert response.data["visitor_name"] == "Jane Smith"
        assert response.data["status"] == VisitorStatus.PENDING
        assert "otp_code" in response.data
        assert len(response.data["otp_code"]) == 6
        assert response.data["otp_code"].isdigit()
        db_visitor = Visitor.objects.get(registered_by=resident)
        assert db_visitor.status == VisitorStatus.PENDING
        assert db_visitor.visitor_name == "Jane Smith"
        assert db_visitor.otp_code == response.data["otp_code"]

    def test_missing_visitor_name_returns_400(
        self, auth_client: Any, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
        response = auth_client.post(
            "/api/v1/visitors/",
            data={
                "visitor_phone": "+919000099998",
                "expected_from": (timezone.now() + timedelta(hours=2)).isoformat(),
                "expected_until": (timezone.now() + timedelta(hours=6)).isoformat(),
            },
            format="json",
        )
        assert response.status_code == 400
        assert "error" in response.data
        assert "visitor_name" in str(response.data["error"])

    def test_security_user_cannot_register_visitor(
        self, security_client: Any, complex_a: Any, unit_a: Any
    ) -> None:
        response = security_client.post(
            "/api/v1/visitors/",
            data={
                "visitor_name": "Test",
                "expected_from": (timezone.now() + timedelta(hours=1)).isoformat(),
                "expected_until": (timezone.now() + timedelta(hours=3)).isoformat(),
            },
            format="json",
        )
        assert response.status_code == 403
        assert Visitor.objects.count() == 0


@pytest.mark.django_db
class TestVisitorVerifyView:

    def test_valid_otp_returns_visitor_details(
        self, security_client: Any, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
        visitor = VisitorFactory(
            complex=complex_a,
            unit=unit_a,
            registered_by=resident,
            otp_code="123456",
            visitor_name="Test Visitor",
            status=VisitorStatus.PENDING,
            expected_from=timezone.now() - timedelta(hours=1),
            expected_until=timezone.now() + timedelta(hours=3),
        )

        response = security_client.post(
            "/api/v1/visitors/verify/",
            data={"otp_code": "123456"},
            format="json",
        )

        assert response.status_code == 200
        assert str(response.data["id"]) == str(visitor.id)
        assert response.data["visitor_name"] == "Test Visitor"
        visitor.refresh_from_db()
        assert visitor.status == VisitorStatus.PENDING

    def test_invalid_otp_returns_error(
        self, security_client: Any, complex_a: Any
    ) -> None:
        response = security_client.post(
            "/api/v1/visitors/verify/",
            data={"otp_code": "000000"},
            format="json",
        )
        assert response.status_code >= 400

    def test_resident_cannot_access_verify_endpoint(
        self, auth_client: Any, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
        VisitorFactory(
            complex=complex_a,
            unit=unit_a,
            registered_by=resident,
            otp_code="654321",
            expected_from=timezone.now() - timedelta(hours=1),
            expected_until=timezone.now() + timedelta(hours=3),
        )
        response = auth_client.post(
            "/api/v1/visitors/verify/",
            data={"otp_code": "654321"},
            format="json",
        )
        assert response.status_code == 403


@pytest.mark.django_db
class TestVisitorArriveView:

    def test_security_marks_visitor_arrived(
        self,
        security_client: Any,
        complex_a: Any,
        unit_a: Any,
        resident: Any,
        security_user: Any,
        mocker: Any,
    ) -> None:
        mocker.patch("apps.notifications.helpers.expo_push_send")
        visitor = VisitorFactory(
            complex=complex_a,
            unit=unit_a,
            registered_by=resident,
            status=VisitorStatus.PENDING,
            expected_from=timezone.now() - timedelta(hours=1),
            expected_until=timezone.now() + timedelta(hours=3),
        )

        response = security_client.post(f"/api/v1/visitors/{visitor.id}/arrive/")

        assert response.status_code == 200
        assert response.data["status"] == VisitorStatus.ARRIVED
        assert response.data["arrived_at"] is not None
        assert str(response.data["visitor_id"]) == str(visitor.id)

        visitor.refresh_from_db()
        assert visitor.status == VisitorStatus.ARRIVED
        assert visitor.arrived_at is not None
        assert visitor.marked_by_id == security_user.id

    def test_already_arrived_visitor_returns_error(
        self, security_client: Any, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
        visitor = VisitorFactory(
            complex=complex_a,
            unit=unit_a,
            registered_by=resident,
            status=VisitorStatus.ARRIVED,
            arrived_at=timezone.now() - timedelta(minutes=5),
            expected_from=timezone.now() - timedelta(hours=2),
            expected_until=timezone.now() + timedelta(hours=2),
        )

        response = security_client.post(f"/api/v1/visitors/{visitor.id}/arrive/")

        assert response.status_code >= 400
        visitor.refresh_from_db()
        assert visitor.status == VisitorStatus.ARRIVED

    def test_expired_visitor_cannot_be_marked_arrived(
        self, security_client: Any, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
        visitor = VisitorFactory(
            complex=complex_a,
            unit=unit_a,
            registered_by=resident,
            status=VisitorStatus.PENDING,
            expected_from=timezone.now() - timedelta(hours=5),
            expected_until=timezone.now() - timedelta(hours=1),
        )

        response = security_client.post(f"/api/v1/visitors/{visitor.id}/arrive/")

        assert response.status_code >= 400
        visitor.refresh_from_db()
        assert visitor.status == VisitorStatus.PENDING

    def test_resident_cannot_mark_arrived(
        self, auth_client: Any, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
        visitor = VisitorFactory(
            complex=complex_a,
            unit=unit_a,
            registered_by=resident,
            expected_from=timezone.now() - timedelta(hours=1),
            expected_until=timezone.now() + timedelta(hours=3),
        )
        response = auth_client.post(f"/api/v1/visitors/{visitor.id}/arrive/")
        assert response.status_code == 403
        visitor.refresh_from_db()
        assert visitor.status == VisitorStatus.PENDING
