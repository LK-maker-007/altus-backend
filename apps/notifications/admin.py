from __future__ import annotations

from django.contrib import admin

from apps.notifications.models import NotificationLog


@admin.register(NotificationLog)
class NotificationLogAdmin(admin.ModelAdmin[NotificationLog]):

    list_display = (
        "id",
        "recipient",
        "title",
        "push_token_prefix",
        "status",
        "expo_ticket_id",
        "created_at",
        "checked_at",
    )
    list_filter = ("status", "created_at")
    search_fields = ("recipient__phone_number", "push_token", "title", "expo_ticket_id")
    readonly_fields = (
        "id",
        "recipient",
        "complex",
        "push_token",
        "title",
        "body",
        "data",
        "status",
        "expo_ticket_id",
        "checked_at",
        "error_message",
        "created_at",
        "updated_at",
    )
    ordering = ("-created_at",)

    @admin.display(description="Token (prefix)")
    def push_token_prefix(self, obj: NotificationLog) -> str:
        return obj.push_token[:25] + "…" if len(obj.push_token) > 25 else obj.push_token

    def has_add_permission(self, request: object) -> bool:
        return False

    def has_change_permission(self, request: object, obj: object = None) -> bool:
        return False
