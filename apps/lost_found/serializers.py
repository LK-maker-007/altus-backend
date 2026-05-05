from __future__ import annotations

from typing import ClassVar

from rest_framework import serializers

from apps.lost_found.models import LostFoundReport


class LostFoundReportSerializer(serializers.ModelSerializer[LostFoundReport]):
    """Read serializer for lost & found report list/create (api-contract §10)."""

    class Meta:
        model = LostFoundReport
        fields: ClassVar[list[str]] = [
            "id",
            "report_type",
            "description",
            "location",
            "status",
            "created_at",
        ]
        read_only_fields: ClassVar[list[str]] = ["id", "status", "created_at"]
