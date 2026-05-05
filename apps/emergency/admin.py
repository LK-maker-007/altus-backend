from __future__ import annotations

from django.contrib import admin
from django.core.cache import cache
from django.http import HttpRequest

from apps.core.admin import ComplexScopedModelAdmin
from apps.emergency.models import EmergencyContact
from apps.emergency.services import _cache_key


def _invalidate_cache(complex_id: str) -> None:
    """Clear the emergency contacts Redis cache for a given complex."""
    cache.delete(_cache_key(complex_id))


@admin.register(EmergencyContact)
class EmergencyContactAdmin(ComplexScopedModelAdmin):
    """Admin for managing emergency contacts.

    Invalidates the Redis contacts cache on every save or delete so that
    residents see the updated list within seconds, not hours.
    """

    list_display = ("name", "role", "phone_number", "display_order", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "role", "phone_number")
    readonly_fields = ("created_at", "updated_at")

    def save_model(
        self,
        request: HttpRequest,
        obj: EmergencyContact,
        form: object,
        change: bool,
    ) -> None:
        super().save_model(request, obj, form, change)
        _invalidate_cache(str(obj.complex_id))

    def delete_model(self, request: HttpRequest, obj: EmergencyContact) -> None:
        complex_id = str(obj.complex_id)
        super().delete_model(request, obj)
        _invalidate_cache(complex_id)
