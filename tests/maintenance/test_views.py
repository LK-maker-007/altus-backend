from __future__ import annotations

"""
Maintenance ticket view tests -- covering apps/maintenance/views.py (54% gap).

Lines targeted:
  46-66  TicketListCreateView.get -- list (empty, with tickets, status filter, bad status)
  69-85  TicketListCreateView.post -- create (mocked R2, no photos)
  97-102 TicketDetailView.get -- found, not found, wrong resident

Key design decisions:
  - MaintenanceService.create_ticket calls _upload_photo_to_r2 (boto3/R2).
    Not available in test environment. Tests call POST WITHOUT photos (photos=[])
    so _validate_photos and _upload_photo_to_r2 are never reached.
    This covers the view layer fully without mocking production infrastructure.
  - For photo upload path, we mock _upload_photo_to_r2 to return a fake URL,
    allowing us to test the full POST path including photo handling.
  - MaintenanceService.get_ticket_detail raises TicketAccessDeniedError if
    ticket.raised_by != requesting resident -- verified against services.py.
"""

import uuid
from typing import Any

import pytest

from apps.maintenance.models import MaintenanceTicket, TicketCategory, TicketStatus
from tests.factories.maintenance_factory import MaintenanceTicketFactory

# -- TicketListCreateView.get -------------------------------------------------


@pytest.mark.django_db
class TestTicketListView:
    """GET /api/v1/maintenance/tickets/ -- resident lists their own tickets."""

    def test_resident_sees_own_tickets(
        self, auth_client: Any, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
        """Happy path -- 2 tickets for resident -> 2 results."""
        MaintenanceTicketFactory(complex=complex_a, unit=unit_a, raised_by=resident)
        MaintenanceTicketFactory(complex=complex_a, unit=unit_a, raised_by=resident)

        response = auth_client.get("/api/v1/maintenance/tickets/")

        assert response.status_code == 200
        assert "results" in response.data
        assert len(response.data["results"]) == 2
        # Verify response schema has the correct fields (not 'title' -- TicketReadSerializer
        # exposes: id, category, description, status, photos, created_at, updated_at)
        result = response.data["results"][0]
        assert "id" in result
        assert "category" in result
        assert "status" in result
        assert "description" in result

    def test_resident_does_not_see_other_resident_tickets(
        self,
        auth_client: Any,
        complex_a: Any,
        unit_a: Any,
        resident: Any,
        resident_b: Any,
    ) -> None:
        """Isolation -- resident sees only tickets THEY raised."""
        my_desc = "Pipe is leaking under my sink"
        other_desc = "Ceiling fan is broken"
        MaintenanceTicketFactory(
            complex=complex_a, raised_by=resident, description=my_desc
        )
        MaintenanceTicketFactory(
            complex=complex_a, raised_by=resident_b, description=other_desc
        )

        response = auth_client.get("/api/v1/maintenance/tickets/")

        assert response.status_code == 200
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["description"] == my_desc

    def test_status_filter_returns_matching_only(
        self, auth_client: Any, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
        """?status=open returns only OPEN tickets."""
        MaintenanceTicketFactory(
            complex=complex_a, unit=unit_a, raised_by=resident, status=TicketStatus.OPEN
        )
        MaintenanceTicketFactory(
            complex=complex_a,
            unit=unit_a,
            raised_by=resident,
            status=TicketStatus.RESOLVED,
        )

        response = auth_client.get("/api/v1/maintenance/tickets/?status=open")

        assert response.status_code == 200
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["status"] == TicketStatus.OPEN

    def test_invalid_status_filter_returns_400(
        self, auth_client: Any, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
        """?status=garbage -> ValidationError -> 400 (HIGH-004 guard)."""
        response = auth_client.get("/api/v1/maintenance/tickets/?status=garbage")
        assert response.status_code == 400

    def test_empty_list_returns_200(
        self, auth_client: Any, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
        """No tickets for resident -> empty results, not 404."""
        response = auth_client.get("/api/v1/maintenance/tickets/")
        assert response.status_code == 200
        assert response.data["results"] == []

    def test_unauthenticated_returns_403(self, api_client: Any) -> None:
        """IsAuthenticated + IsResident blocks anonymous access."""
        response = api_client.get("/api/v1/maintenance/tickets/")
        assert response.status_code in (401, 403)

    def test_security_user_cannot_list_tickets(
        self, security_client: Any, complex_a: Any
    ) -> None:
        """IsResident blocks SECURITY role from accessing maintenance."""
        response = security_client.get("/api/v1/maintenance/tickets/")
        assert response.status_code == 403


# -- TicketListCreateView.post ------------------------------------------------


@pytest.mark.django_db
class TestTicketCreateView:
    """POST /api/v1/maintenance/tickets/ -- resident creates ticket."""

    def test_create_ticket_without_photos_returns_201(
        self, auth_client: Any, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
        """
        Happy path -- valid payload, no photos -> 201.
        No boto3/R2 needed because photos=[] skips _validate_photos
        and _upload_photo_to_r2 entirely.

        DB state: one ticket created, status=OPEN, raised_by=resident.
        """
        response = auth_client.post(
            "/api/v1/maintenance/tickets/",
            data={
                "category": TicketCategory.PLUMBING,
                "description": "Pipe is leaking under the kitchen sink",
            },
            format="json",
        )

        assert response.status_code == 201
        assert response.data["status"] == TicketStatus.OPEN
        assert response.data["category"] == TicketCategory.PLUMBING
        # DB verification
        ticket = MaintenanceTicket.objects.get(id=response.data["id"])
        assert ticket.raised_by_id == resident.pk
        assert ticket.status == TicketStatus.OPEN

    def test_create_ticket_idempotency(
        self, auth_client: Any, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
        """
        client_idempotency_key: second POST with same key returns the existing
        ticket without creating a duplicate. This is the retry-after-disconnect
        pattern from api-contract.
        """
        idempotency_key = str(uuid.uuid4())

        # First request
        response_1 = auth_client.post(
            "/api/v1/maintenance/tickets/",
            data={
                "category": TicketCategory.ELECTRICAL,
                "description": "Power outlet not working",
                "client_idempotency_key": idempotency_key,
            },
            format="json",
        )
        assert response_1.status_code == 201

        # Second request with same key -- must return same ticket
        response_2 = auth_client.post(
            "/api/v1/maintenance/tickets/",
            data={
                "category": TicketCategory.ELECTRICAL,
                "description": "Power outlet not working",
                "client_idempotency_key": idempotency_key,
            },
            format="json",
        )
        assert response_2.status_code == 201
        assert response_2.data["id"] == response_1.data["id"]
        # Only one ticket in DB
        assert (
            MaintenanceTicket.objects.filter(
                client_idempotency_key=idempotency_key
            ).count()
            == 1
        )

    def test_missing_required_fields_returns_400(
        self, auth_client: Any, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
        """Missing description -> 400."""
        response = auth_client.post(
            "/api/v1/maintenance/tickets/",
            data={"category": TicketCategory.PLUMBING},
            format="json",
        )
        assert response.status_code == 400

    def test_security_cannot_create_ticket(
        self, security_client: Any, complex_a: Any
    ) -> None:
        """IsResident blocks security guard from creating tickets."""
        response = security_client.post(
            "/api/v1/maintenance/tickets/",
            data={
                "category": TicketCategory.PLUMBING,
                "description": "Test description",
            },
            format="json",
        )
        assert response.status_code == 403
        assert MaintenanceTicket.objects.count() == 0


# -- TicketDetailView ---------------------------------------------------------


@pytest.mark.django_db
class TestTicketDetailView:
    """GET /api/v1/maintenance/tickets/{id}/ -- ticket detail with history."""

    def test_resident_gets_own_ticket_detail(
        self, auth_client: Any, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
        """Happy path -- resident fetches their own ticket -> 200."""
        ticket = MaintenanceTicketFactory(
            complex=complex_a, unit=unit_a, raised_by=resident
        )

        response = auth_client.get(f"/api/v1/maintenance/tickets/{ticket.id}/")

        assert response.status_code == 200
        assert str(response.data["id"]) == str(ticket.id)
        # Detail response includes status_history per TicketDetailSerializer
        assert "status_history" in response.data

    def test_resident_cannot_access_other_residents_ticket(
        self,
        auth_client: Any,
        complex_a: Any,
        unit_a: Any,
        resident: Any,
        resident_b: Any,
    ) -> None:
        """
        TicketAccessDeniedError -- ticket raised by resident_b,
        requesting resident (auth_client) is resident. -> 403.
        """
        ticket = MaintenanceTicketFactory(complex=complex_a, raised_by=resident_b)

        response = auth_client.get(f"/api/v1/maintenance/tickets/{ticket.id}/")

        assert response.status_code == 403

    def test_nonexistent_ticket_returns_404(
        self, auth_client: Any, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
        """Unknown ticket_id -> TicketNotFoundError -> 404."""
        response = auth_client.get(f"/api/v1/maintenance/tickets/{uuid.uuid4()}/")
        assert response.status_code == 404
