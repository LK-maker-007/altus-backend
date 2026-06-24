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

    url = serializers.SerializerMethodField()

    def get_url(self, obj: TicketPhoto) -> str:
        return str(obj.photo_url)

    class Meta:
        model = TicketPhoto
        fields: ClassVar[list[str]] = ["id", "url"]
        read_only_fields: ClassVar[list[str]] = ["id", "url"]


class TicketStatusHistorySerializer(serializers.ModelSerializer[TicketStatusHistory]):

    class Meta:
        model = TicketStatusHistory
        fields: ClassVar[list[str]] = ["status", "changed_at"]
        read_only_fields: ClassVar[list[str]] = fields


class TicketReadSerializer(serializers.ModelSerializer[MaintenanceTicket]):

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

    category = serializers.ChoiceField(choices=TicketCategory.choices)
    description = serializers.CharField(min_length=10)
    client_idempotency_key = serializers.UUIDField(required=False, allow_null=True)
    queued_at = serializers.DateTimeField(required=False, allow_null=True)
