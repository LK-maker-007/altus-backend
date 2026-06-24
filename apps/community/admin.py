from __future__ import annotations

from django.contrib import admin
from django.db import transaction
from django.http import HttpRequest

from apps.community.models import Announcement
from apps.core.admin import ComplexScopedModelAdmin


@admin.register(Announcement)
class AnnouncementAdmin(ComplexScopedModelAdmin):

    list_display = ("title", "category", "is_active", "created_at")
    list_filter = ("category", "is_active")
    search_fields = ("title", "body")
    readonly_fields = ("created_at", "updated_at")

    def save_model(
        self,
        request: HttpRequest,
        obj: Announcement,
        form: object,
        change: bool,
    ) -> None:
        super().save_model(request, obj, form, change)

        if not change and obj.is_active:
            from apps.community.tasks import send_announcement_push

            transaction.on_commit(
                lambda: send_announcement_push.apply_async(
                    args=(
                        str(obj.id),
                        str(obj.complex_id),
                    ),
                )
            )
