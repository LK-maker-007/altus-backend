from __future__ import annotations

from typing import Any, ClassVar

from rest_framework import serializers

from apps.maintenance.models import (
    MaintenanceTicket,
    TicketCategory,
    TicketPhoto,
    TicketStatusHistory,
)


class TicketPhotoSerializer(serializers.ModelSerializer[TicketPhoto]):
    """Read serializer for a single photo attached to a ticket (api-contract §7).

    The model field is `photo_url`; the API contract §7 response uses `url`.
    Declared as an explicit SerializerMethodField to avoid binding to a
    non-existent model field name in Meta.fields.
    """

    # HIGH-002: explicit field — photo_url on model, url in api response
    url = serializers.SerializerMethodField()

    def get_url(self, obj: TicketPhoto) -> str:
        return str(obj.photo_url)

    class Meta:
        model = TicketPhoto
        fields: ClassVar[list[str]] = ["id", "url"]
        read_only_fields: ClassVar[list[str]] = ["id", "url"]


class TicketStatusHistorySerializer(serializers.ModelSerializer[TicketStatusHistory]):
    """Read serializer for a single status history entry (api-contract §7 detail)."""

    class Meta:
        model = TicketStatusHistory
        fields: ClassVar[list[str]] = ["status", "changed_at"]
        read_only_fields: ClassVar[list[str]] = fields


class TicketReadSerializer(serializers.ModelSerializer[MaintenanceTicket]):
    """Read serializer for ticket list items (api-contract §7 list)."""

    photos = TicketPhotoSerializer(many=True, read_only=True)

    class Meta:
        model = MaintenanceTicket
        fields: ClassVar[list[str]] = [
            "id",
            "category",
            "description",
            "status",
            "photos",
            "created_at",
            "updated_at",
            "resolved_at",
        ]
        read_only_fields: ClassVar[list[str]] = fields


class TicketDetailSerializer(serializers.ModelSerializer[MaintenanceTicket]):
    """Ticket detail serializer — full status history (api-contract §7)."""

    photos = TicketPhotoSerializer(many=True, read_only=True)
    status_history = TicketStatusHistorySerializer(many=True, read_only=True)

    class Meta:
        model = MaintenanceTicket
        fields: ClassVar[list[str]] = [
            "id",
            "category",
            "description",
            "status",
            "photos",
            "status_history",
            "created_at",
            "updated_at",
            "resolved_at",
        ]
        read_only_fields: ClassVar[list[str]] = fields


class TicketCreateSerializer(serializers.Serializer[dict[str, Any]]):
    """Write serializer for creating a maintenance ticket (api-contract §7 POST).

    Accepts multipart/form-data. Photos are optional — max 3, 5 MB each.
    client_idempotency_key is optional — device-generated UUID for deduplication.
    """

    category = serializers.ChoiceField(choices=TicketCategory.choices)
    description = serializers.CharField(min_length=10)
    client_idempotency_key = serializers.UUIDField(required=False, allow_null=True)
    queued_at = serializers.DateTimeField(required=False, allow_null=True)
    # photos handled separately in view via request.FILES — not a serializer field
