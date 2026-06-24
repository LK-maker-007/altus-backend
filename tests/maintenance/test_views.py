from __future__ import annotations

import uuid
from typing import Any

import pytest

from apps.maintenance.models import MaintenanceTicket, TicketCategory, TicketStatus
from tests.factories.maintenance_factory import MaintenanceTicketFactory


@pytest.mark.django_db
class TestTicketListView:

    def test_resident_sees_own_tickets(
        self, auth_client: Any, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
        MaintenanceTicketFactory(complex=complex_a, unit=unit_a, raised_by=resident)
        MaintenanceTicketFactory(complex=complex_a, unit=unit_a, raised_by=resident)

        response = auth_client.get("/api/v1/maintenance/tickets/")

        assert response.status_code == 200
        assert "results" in response.data
        assert len(response.data["results"]) == 2
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
        response = auth_client.get("/api/v1/maintenance/tickets/?status=garbage")
        assert response.status_code == 400

    def test_empty_list_returns_200(
        self, auth_client: Any, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
        response = auth_client.get("/api/v1/maintenance/tickets/")
        assert response.status_code == 200
        assert response.data["results"] == []

    def test_unauthenticated_returns_403(self, api_client: Any) -> None:
        response = api_client.get("/api/v1/maintenance/tickets/")
        assert response.status_code in (401, 403)

    def test_security_user_cannot_list_tickets(
        self, security_client: Any, complex_a: Any
    ) -> None:
        response = security_client.get("/api/v1/maintenance/tickets/")
        assert response.status_code == 403


@pytest.mark.django_db
class TestTicketCreateView:

    def test_create_ticket_without_photos_returns_201(
        self, auth_client: Any, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
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
        ticket = MaintenanceTicket.objects.get(id=response.data["id"])
        assert ticket.raised_by_id == resident.pk
        assert ticket.status == TicketStatus.OPEN

    def test_create_ticket_idempotency(
        self, auth_client: Any, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
        idempotency_key = str(uuid.uuid4())

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
        assert (
            MaintenanceTicket.objects.filter(
                client_idempotency_key=idempotency_key
            ).count()
            == 1
        )

    def test_missing_required_fields_returns_400(
        self, auth_client: Any, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
        response = auth_client.post(
            "/api/v1/maintenance/tickets/",
            data={"category": TicketCategory.PLUMBING},
            format="json",
        )
        assert response.status_code == 400

    def test_security_cannot_create_ticket(
        self, security_client: Any, complex_a: Any
    ) -> None:
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


@pytest.mark.django_db
class TestTicketDetailView:

    def test_resident_gets_own_ticket_detail(
        self, auth_client: Any, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
        ticket = MaintenanceTicketFactory(
            complex=complex_a, unit=unit_a, raised_by=resident
        )

        response = auth_client.get(f"/api/v1/maintenance/tickets/{ticket.id}/")

        assert response.status_code == 200
        assert str(response.data["id"]) == str(ticket.id)
        assert "status_history" in response.data

    def test_resident_cannot_access_other_residents_ticket(
        self,
        auth_client: Any,
        complex_a: Any,
        unit_a: Any,
        resident: Any,
        resident_b: Any,
    ) -> None:
        ticket = MaintenanceTicketFactory(complex=complex_a, raised_by=resident_b)

        response = auth_client.get(f"/api/v1/maintenance/tickets/{ticket.id}/")

        assert response.status_code == 403

    def test_nonexistent_ticket_returns_404(
        self, auth_client: Any, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
        response = auth_client.get(f"/api/v1/maintenance/tickets/{uuid.uuid4()}/")
        assert response.status_code == 404
