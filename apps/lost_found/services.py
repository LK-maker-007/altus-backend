"""
apps/lost_found/services.py

LostFoundService — business logic for lost and found report operations.

WHY a service layer for generic DRF views:
  ADR-010 mandates that all business logic lives in the service layer, not views.
  The previous implementation used DRF's generics.ListCreateAPIView with
  perform_create() containing the tenant-scoping logic (complex_id assignment).
  Moving this to a service:
    - Makes the create logic independently testable.
    - Makes the filtering logic a named, testable function.
    - Provides a reusable entry point for future callers (admin commands, etc.).
    - Matches the pattern of every other app in the codebase.
  Source: audit §P2 §lost_found app violates ADR-010;
          HackSoftware Django Styleguide §Services.
"""

from __future__ import annotations

from django.db.models import QuerySet

from apps.lost_found.models import LostFoundReport
from apps.users.models import User


class LostFoundService:
    """Service layer for lost and found report operations."""

    @staticmethod
    def list_reports(
        *,
        complex_id: str,
        report_type: str | None = None,
    ) -> QuerySet[LostFoundReport]:
        """Return lost and found reports for a complex, newest first.

        Args:
            complex_id: UUID string of the complex to filter by.
            report_type: Optional filter — "lost" or "found". None returns all.

        Returns:
            QuerySet of LostFoundReport, ordered by -created_at. Callers
            are responsible for applying pagination.
        """
        qs = LostFoundReport.objects.order_by("-created_at")
        if report_type:
            qs = qs.filter(report_type=report_type)
        return qs

    @staticmethod
    def create_report(
        *,
        reporter: User,
        data: dict[str, object],
    ) -> LostFoundReport:
        """Create a lost or found report for the reporter's complex.

        Args:
            reporter: The User submitting the report.
            data:     Validated serializer data
                      (report_type, description, images, etc.).

        Returns:
            The created LostFoundReport instance.
        """
        # WHY reporter.complex_id guaranteed non-None:
        #   The auth layer (JWTAuthMiddleware + IsAuthenticated) ensures
        #   request.user.complex_id is set for every resident or security
        #   role that can reach this endpoint. PLATFORM_ADMIN without a
        #   complex cannot call this endpoint. If complex_id is somehow
        #   None, the model's FK constraint will catch it at DB level.
        complex_id = reporter.complex_id
        if complex_id is None:
            raise ValueError("reporter.complex_id must not be None")
        return LostFoundReport.objects.create(
            reported_by=reporter,
            complex_id=complex_id,
            **data,
        )
