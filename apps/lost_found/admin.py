from __future__ import annotations

from django.contrib import admin

from apps.core.admin import ComplexScopedModelAdmin
from apps.lost_found.models import LostFoundReport


@admin.register(LostFoundReport)
class LostFoundReportAdmin(ComplexScopedModelAdmin):
    """Admin for lost and found reports. Read-only — no business logic here."""

    list_display = ("report_type", "description", "status", "reported_by", "created_at")
    list_filter = ("report_type", "status")
    search_fields = ("description", "location")
    readonly_fields = ("created_at", "updated_at")
