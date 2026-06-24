from __future__ import annotations

from django.db.models import QuerySet

from apps.lost_found.models import LostFoundReport
from apps.users.models import User


class LostFoundService:

    @staticmethod
    def list_reports(
        *,
        complex_id: str,
        report_type: str | None = None,
    ) -> QuerySet[LostFoundReport]:
        qs = LostFoundReport.unscoped.filter(complex_id=complex_id).order_by(
            "-created_at"
        )
        if report_type:
            qs = qs.filter(report_type=report_type)
        return qs

    @staticmethod
    def create_report(
        *,
        reporter: User,
        data: dict[str, object],
    ) -> LostFoundReport:
        complex_id = reporter.complex_id
        if complex_id is None:
            raise ValueError("reporter.complex_id must not be None")
        return LostFoundReport.objects.create(
            reported_by=reporter,
            complex_id=complex_id,
            **data,
        )
