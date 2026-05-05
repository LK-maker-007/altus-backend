from __future__ import annotations

from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest

from apps.bookings.models import Booking
from apps.core.admin import ComplexScopedModelAdmin


@admin.register(Booking)
class BookingAdmin(ComplexScopedModelAdmin):
    list_display = [
        "id",
        "facility",
        "resident",
        "slot_start",
        "slot_end",
        "status",
        "complex",
    ]
    list_filter = ["status", "facility__category"]
    search_fields = ["resident__phone_number", "resident__name", "facility__name"]
    readonly_fields = ["id", "created_at", "updated_at", "expires_at", "cancelled_at"]

    def get_queryset(self, request: HttpRequest) -> QuerySet[Booking]:
        return super().get_queryset(request).select_related("facility", "resident")
