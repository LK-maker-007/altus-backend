from __future__ import annotations

"""
Visitor API view tests -- US-019 (register), US-021 (verify OTP),
US-022 (arrive), US-023 (list).

Uses DRF APIClient via conftest fixtures.
API prefix: /api/v1/visitors/

Uncovered lines this file targets (visitors/views.py):
  35-44  VisitorListCreateView.get
  47-59  VisitorListCreateView.post
  72-80  VisitorVerifyView.post
  92-98  VisitorArriveView.post
"""

from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone

from apps.visitors.models import Visitor, VisitorStatus
from tests.factories.visitor_factory import VisitorFactory

# -- VisitorListCreateView.get -----------------------------------------------


@pytest.mark.django_db
class TestVisitorListView:
    """GET /api/v1/visitors/ -- resident lists their own visitor passes."""

    def test_resident_sees_own_visitors(
        self, auth_client: Any, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
        """Happy path -- 2 visitors registered by resident -> 2 results."""
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
        """?status=pending filter returns only PENDING passes."""
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
        """
        Isolation -- resident sees only visitors THEY registered.
        A visitor registered by resident_b must not appear.
        """
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
        """IsAuthenticated + IsResident blocks anonymous access."""
        response = api_client.get("/api/v1/visitors/")
        assert response.status_code in (401, 403)

    def test_empty_list_returns_200(
        self, auth_client: Any, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
        """No visitors yet -> empty results list, not 404."""
        response = auth_client.get("/api/v1/visitors/")
        assert response.status_code == 200
        assert response.data["results"] == []


# -- VisitorListCreateView.post -----------------------------------------------


@pytest.mark.django_db
class TestVisitorCreateView:
    """POST /api/v1/visitors/ -- resident pre-registers a visitor (US-019)."""

    def test_register_visitor_returns_201_with_otp(
        self, auth_client: Any, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
        """
        Happy path -- valid payload -> 201.
        Asserts: response schema, otp_code is 6 digits, DB state matches response.
        """
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
        # Response schema -- not just "key exists"
        assert response.data["visitor_name"] == "Jane Smith"
        assert response.data["status"] == VisitorStatus.PENDING
        assert "otp_code" in response.data
        assert len(response.data["otp_code"]) == 6
        assert response.data["otp_code"].isdigit()
        # DB state verification -- the write must be persisted
        db_visitor = Visitor.objects.get(registered_by=resident)
        assert db_visitor.status == VisitorStatus.PENDING
        assert db_visitor.visitor_name == "Jane Smith"
        assert db_visitor.otp_code == response.data["otp_code"]

    def test_missing_visitor_name_returns_400(
        self, auth_client: Any, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
        """Serializer validation -- visitor_name is required -> 400 with field error."""
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
        # Project wraps DRF errors in {"error": {"code": "invalid", "message": "...", "details": {}}}
        # The field name appears in error.message as a serializer repr string
        assert "error" in response.data
        assert "visitor_name" in str(response.data["error"])

    def test_security_user_cannot_register_visitor(
        self, security_client: Any, complex_a: Any, unit_a: Any
    ) -> None:
        """IsResident blocks security guard from pre-registering visitors."""
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
        # No visitor must be created in DB
        assert Visitor.objects.count() == 0


# -- VisitorVerifyView --------------------------------------------------------


@pytest.mark.django_db
class TestVisitorVerifyView:
    """POST /api/v1/visitors/verify/ -- security verifies visitor OTP (US-021)."""

    def test_valid_otp_returns_visitor_details(
        self, security_client: Any, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
        """
        Happy path -- correct OTP -> visitor details returned, NOT marked arrived.
        verify_otp is READ-ONLY: DB status must still be PENDING after this call.
        """
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
        # verify_otp must NOT mutate the status -- read-only operation
        visitor.refresh_from_db()
        assert visitor.status == VisitorStatus.PENDING

    def test_invalid_otp_returns_error(
        self, security_client: Any, complex_a: Any
    ) -> None:
        """OTP that doesn't match any PENDING visitor -> VisitorNotFoundError."""
        response = security_client.post(
            "/api/v1/visitors/verify/",
            data={"otp_code": "000000"},
            format="json",
        )
        assert response.status_code >= 400

    def test_resident_cannot_access_verify_endpoint(
        self, auth_client: Any, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
        """IsSecurityGuard blocks resident from the gate verification endpoint."""
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


# -- VisitorArriveView --------------------------------------------------------


@pytest.mark.django_db
class TestVisitorArriveView:
    """POST /api/v1/visitors/{id}/arrive/ -- security marks arrived (US-022)."""

    def test_security_marks_visitor_arrived(
        self,
        security_client: Any,
        complex_a: Any,
        unit_a: Any,
        resident: Any,
        security_user: Any,
        mocker: Any,
    ) -> None:
        """
        Happy path -- PENDING visitor -> status transitions to ARRIVED.

        Asserts ALL of:
          1. Response 200
          2. response.data["status"] == ARRIVED
          3. response.data["arrived_at"] is not None
          4. response.data["visitor_id"] matches the visitor's UUID
          5. DB visitor.status == ARRIVED
          6. DB visitor.arrived_at is set
          7. DB visitor.marked_by == security_user (the guard, not the resident)
        expo_push_send patched -- prevents real Expo network call in tests.
        """
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

        # Response assertions
        assert response.status_code == 200
        assert response.data["status"] == VisitorStatus.ARRIVED
        assert response.data["arrived_at"] is not None
        assert str(response.data["visitor_id"]) == str(visitor.id)

        # DB state assertions -- the view wrote, we verify the write was correct
        visitor.refresh_from_db()
        assert visitor.status == VisitorStatus.ARRIVED
        assert visitor.arrived_at is not None
        # marked_by must be the security guard, not the resident or complex
        assert visitor.marked_by_id == security_user.id

    def test_already_arrived_visitor_returns_error(
        self, security_client: Any, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
        """
        Already-ARRIVED visitor -> VisitorOTPUsedError -> non-2xx.
        DB must be unchanged -- no double-arrive corruption.
        """
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
        assert visitor.status == VisitorStatus.ARRIVED  # not mutated

    def test_expired_visitor_cannot_be_marked_arrived(
        self, security_client: Any, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
        """
        Visitor whose expected_until has passed -> VisitorOTPExpiredError -> non-2xx.
        Guards must not be able to mark stale passes as arrived.
        """
        visitor = VisitorFactory(
            complex=complex_a,
            unit=unit_a,
            registered_by=resident,
            status=VisitorStatus.PENDING,
            expected_from=timezone.now() - timedelta(hours=5),
            expected_until=timezone.now() - timedelta(hours=1),  # expired
        )

        response = security_client.post(f"/api/v1/visitors/{visitor.id}/arrive/")

        assert response.status_code >= 400
        visitor.refresh_from_db()
        assert visitor.status == VisitorStatus.PENDING  # not mutated

    def test_resident_cannot_mark_arrived(
        self, auth_client: Any, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
        """IsSecurityGuard blocks resident from marking visitors as arrived."""
        visitor = VisitorFactory(
            complex=complex_a,
            unit=unit_a,
            registered_by=resident,
            expected_from=timezone.now() - timedelta(hours=1),
            expected_until=timezone.now() + timedelta(hours=3),
        )
        response = auth_client.post(f"/api/v1/visitors/{visitor.id}/arrive/")
        assert response.status_code == 403
        # DB must be untouched
        visitor.refresh_from_db()
        assert visitor.status == VisitorStatus.PENDING
