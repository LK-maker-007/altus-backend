from __future__ import annotations

from typing import Any, ClassVar

from rest_framework import serializers

from apps.facilities.models import Facility


class FacilityReadSerializer(serializers.ModelSerializer[Facility]):
    class Meta:
        model = Facility
        fields: ClassVar[list[str]] = [
            "id",
            "name",
            "category",
            "requires_booking",
            "capacity",
            "operating_hours",
            "is_active",
        ]


class FacilityMinimalSerializer(serializers.ModelSerializer[Facility]):
    class Meta:
        model = Facility
        fields: ClassVar[list[str]] = ["id", "name", "category"]


class SlotSerializer(serializers.Serializer[dict[str, Any]]):
    slot_start = serializers.DateTimeField()
    slot_end = serializers.DateTimeField()
    status = serializers.ChoiceField(choices=["available", "unavailable"])
