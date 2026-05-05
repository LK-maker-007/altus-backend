from __future__ import annotations

from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest

from apps.core.admin import ComplexScopedModelAdmin
from apps.visitors.models import Visitor


@admin.register(Visitor)
class VisitorAdmin(ComplexScopedModelAdmin):
    list_display = [
        "id",
        "visitor_name",
        "visitor_phone",
        "unit",
        "registered_by",
        "otp_code",
        "status",
        "expected_from",
        "expected_until",
        "arrived_at",
        "complex",
    ]
    list_filter = ["status"]
    search_fields = [
        "visitor_name",
        "visitor_phone",
        "otp_code",
        "registered_by__phone_number",
        "registered_by__name",
    ]
    readonly_fields = [
        "id",
        "otp_code",
        "arrived_at",
        "marked_by",
        "created_at",
        "updated_at",
    ]

    def get_queryset(self, request: HttpRequest) -> QuerySet[Visitor]:
        return (
            super()
            .get_queryset(request)
            .select_related("unit", "registered_by", "marked_by")
        )
