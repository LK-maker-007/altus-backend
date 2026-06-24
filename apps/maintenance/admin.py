from __future__ import annotations

from typing import cast

from django.contrib import admin
from django.db import transaction
from django.http import HttpRequest

from apps.core.admin import ComplexScopedModelAdmin
from apps.maintenance.models import MaintenanceTicket, TicketPhoto, TicketStatusHistory
from apps.users.models import User


class TicketPhotoInline(admin.TabularInline[TicketPhoto, MaintenanceTicket]):
    model = TicketPhoto
    extra = 0
    readonly_fields = ("photo_url", "uploaded_at")
    can_delete = False


class TicketStatusHistoryInline(
    admin.TabularInline[TicketStatusHistory, MaintenanceTicket]
):
    model = TicketStatusHistory
    extra = 0
    readonly_fields = ("status", "changed_at", "changed_by")
    can_delete = False
    ordering = ("changed_at",)


@admin.register(MaintenanceTicket)
class MaintenanceTicketAdmin(ComplexScopedModelAdmin):

    list_display = ("title", "category", "status", "raised_by", "created_at")
    list_filter = ("category", "status")
    search_fields = ("title", "description")
    readonly_fields = ("created_at", "updated_at", "resolved_at", "queued_at")
    inlines = [TicketPhotoInline, TicketStatusHistoryInline]

    def save_model(
        self,
        request: HttpRequest,
        obj: MaintenanceTicket,
        form: object,
        change: bool,
    ) -> None:
        if change:
            try:
                old_status = MaintenanceTicket.objects.get(pk=obj.pk).status
            except MaintenanceTicket.DoesNotExist:
                old_status = None
        else:
            old_status = None

        super().save_model(request, obj, form, change)

        if change and old_status != obj.status:
            TicketStatusHistory.objects.create(
                ticket=obj,
                status=obj.status,
                changed_by=cast(User, request.user),
            )

            from apps.maintenance.tasks import send_maintenance_status_notification

            transaction.on_commit(
                lambda: send_maintenance_status_notification.apply_async(
                    args=(
                        str(obj.id),
                        str(obj.complex_id),
                    ),
                )
            )
