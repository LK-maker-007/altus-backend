from __future__ import annotations

from typing import Any

from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest

from apps.core.models import Complex, Plan, Subscription, Unit
from apps.users.models import UserRole


class ComplexScopedModelAdmin(
    admin.ModelAdmin[Any]
):  # Any = multi-model base; concrete subclasses supply their model type
    """Base admin for all tenant-scoped models.
    platform_admin sees all complexes; complex_admin sees only their own.
    """

    def get_queryset(self, request: HttpRequest) -> QuerySet[Any]:
        qs = super().get_queryset(request)
        role = getattr(request.user, "role", "")
        if role == UserRole.PLATFORM_ADMIN:
            return qs
        if role == UserRole.COMPLEX_ADMIN:
            return qs.filter(complex=getattr(request.user, "complex", None))
        return qs.none()

    def has_add_permission(self, request: HttpRequest) -> bool:
        role = getattr(request.user, "role", "")
        return role in (UserRole.PLATFORM_ADMIN, UserRole.COMPLEX_ADMIN)

    def has_change_permission(self, request: HttpRequest, obj: object = None) -> bool:
        role = getattr(request.user, "role", "")
        if role == UserRole.PLATFORM_ADMIN:
            return True
        if role != UserRole.COMPLEX_ADMIN:
            return False
        if obj is None:
            return True
        return getattr(obj, "complex", None) == getattr(request.user, "complex", None)

    def has_delete_permission(self, request: HttpRequest, obj: object = None) -> bool:
        # Only platform_admin can delete — complex_admin is read/write only
        return getattr(request.user, "role", "") == UserRole.PLATFORM_ADMIN


@admin.register(Complex)
class ComplexAdmin(admin.ModelAdmin[Complex]):
    list_display = ["name", "slug", "city", "state", "is_active"]
    search_fields = ["name", "slug"]
    list_filter = ["is_active", "city"]


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin[Plan]):
    list_display = ["name", "max_units", "price_monthly_inr", "is_active"]


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin[Subscription]):
    list_display = ["complex", "plan", "status", "billing_cycle", "next_billing_date"]
    list_filter = ["status", "billing_cycle"]


@admin.register(Unit)
class UnitAdmin(ComplexScopedModelAdmin):
    list_display = ["unit_number", "building_block", "floor", "complex"]
    list_filter = ["building_block"]
    search_fields = ["unit_number", "building_block"]
