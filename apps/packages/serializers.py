from __future__ import annotations

from typing import Any, ClassVar

from rest_framework import serializers

from apps.packages.models import Package


class PackageLogSerializer(serializers.Serializer[dict[str, Any]]):

    unit_number = serializers.CharField(max_length=20)
    building_block = serializers.CharField(max_length=50)
    description = serializers.CharField(max_length=500)
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class PackageReadSerializer(serializers.ModelSerializer[Package]):

    logged_at = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = Package
        fields: ClassVar[list[str]] = [
            "id",
            "description",
            "notes",
            "status",
            "logged_at",
            "collected_at",
        ]
        read_only_fields: ClassVar[list[str]] = fields


class PackageLogResponseSerializer(serializers.ModelSerializer[Package]):

    unit_number = serializers.CharField(source="unit.unit_number", read_only=True)
    logged_at = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = Package
        fields: ClassVar[list[str]] = [
            "id",
            "unit_id",
            "unit_number",
            "description",
            "status",
            "logged_at",
        ]
        read_only_fields: ClassVar[list[str]] = fields
