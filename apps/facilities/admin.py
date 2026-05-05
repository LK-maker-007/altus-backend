from __future__ import annotations

from django.contrib import admin

from apps.core.admin import ComplexScopedModelAdmin
from apps.facilities.models import Facility


@admin.register(Facility)
class FacilityAdmin(ComplexScopedModelAdmin):
    list_display = ["name", "category", "requires_booking", "is_active", "complex"]
    list_filter = ["category", "requires_booking", "is_active"]
    search_fields = ["name"]
    readonly_fields = ["id", "created_at", "updated_at"]
