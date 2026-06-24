from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

from rest_framework import serializers

from apps.visitors.models import Visitor


class VisitorCreateSerializer(serializers.Serializer[dict[str, Any]]):

    visitor_name = serializers.CharField(max_length=200)
    visitor_phone = serializers.CharField(max_length=20, required=False, default="")
    expected_from = serializers.DateTimeField()
    expected_until = serializers.DateTimeField()

    def validate(self, data: dict[str, Any]) -> dict[str, Any]:
        expected_from = data["expected_from"]
        expected_until = data["expected_until"]
        if isinstance(expected_from, datetime) and isinstance(expected_until, datetime):
            if expected_until <= expected_from:
                raise serializers.ValidationError(
                    "expected_until must be after expected_from."
                )
        return data


class VisitorOTPVerifySerializer(serializers.Serializer[dict[str, Any]]):

    otp_code = serializers.CharField(max_length=6, min_length=6)


class VisitorReadSerializer(serializers.ModelSerializer[Visitor]):

    class Meta:
        model = Visitor
        fields: ClassVar[list[str]] = [
            "id",
            "visitor_name",
            "visitor_phone",
            "expected_from",
            "expected_until",
            "otp_code",
            "status",
            "arrived_at",
            "created_at",
        ]
        read_only_fields: ClassVar[list[str]] = fields


class VisitorVerifyReadSerializer(serializers.ModelSerializer[Visitor]):

    unit_number = serializers.CharField(source="unit.unit_number", read_only=True)
    building_block = serializers.CharField(source="unit.building_block", read_only=True)
    resident_name = serializers.CharField(source="registered_by.name", read_only=True)

    class Meta:
        model = Visitor
        fields: ClassVar[list[str]] = [
            "id",
            "visitor_name",
            "unit_number",
            "building_block",
            "resident_name",
            "expected_from",
            "expected_until",
            "status",
        ]
        read_only_fields: ClassVar[list[str]] = fields
