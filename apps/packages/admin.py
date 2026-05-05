from __future__ import annotations

from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest

from apps.core.admin import ComplexScopedModelAdmin
from apps.packages.models import Package


@admin.register(Package)
class PackageAdmin(ComplexScopedModelAdmin):
    list_display = [
        "id",
        "description",
        "unit",
        "logged_by",
        "status",
        "created_at",
        "collected_at",
        "complex",
    ]
    list_filter = ["status"]
    search_fields = [
        "description",
        "unit__unit_number",
        "unit__building_block",
        "logged_by__phone_number",
    ]
    readonly_fields = [
        "id",
        "logged_by",
        "created_at",
        "updated_at",
        "collected_at",
        "collected_by",
    ]

    def get_queryset(self, request: HttpRequest) -> QuerySet[Package]:
        return (
            super()
            .get_queryset(request)
            .select_related("unit", "logged_by", "collected_by")
        )
