from __future__ import annotations

from django.contrib import admin

from apps.core.admin import ComplexScopedModelAdmin
from apps.users.models import User


@admin.register(User)
class UserAdmin(ComplexScopedModelAdmin):
    """
    User admin — uses ComplexScopedModelAdmin for role-based complex isolation (§7.3).
    """

    list_display = [
        "phone_number",
        "name",
        "role",
        "complex",
        "unit",
        "is_profile_complete",
        "is_active",
        "date_joined",
    ]
    list_filter = ["role", "is_profile_complete", "is_active"]
    search_fields = ["phone_number", "name"]
    readonly_fields = ["id", "date_joined", "last_login"]
    ordering = ["-date_joined"]
