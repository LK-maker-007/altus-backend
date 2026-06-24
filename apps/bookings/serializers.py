from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

from rest_framework import serializers

from apps.bookings.models import Booking
from apps.facilities.serializers import FacilityMinimalSerializer


class BookingHoldSerializer(serializers.Serializer[dict[str, Any]]):
    facility_id = serializers.UUIDField()
    slot_start = serializers.DateTimeField()
    slot_end = serializers.DateTimeField()

    def validate(self, data: dict[str, Any]) -> dict[str, Any]:
        slot_start = data["slot_start"]
        slot_end = data["slot_end"]
        if isinstance(slot_start, datetime) and isinstance(slot_end, datetime):
            if slot_end <= slot_start:
                raise serializers.ValidationError("slot_end must be after slot_start.")
        return data


class BookingCancelSerializer(serializers.Serializer[dict[str, Any]]):
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class BookingReadSerializer(serializers.ModelSerializer[Booking]):
    facility = FacilityMinimalSerializer(read_only=True)

    class Meta:
        model = Booking
        fields: ClassVar[list[str]] = [
            "id",
            "facility",
            "slot_start",
            "slot_end",
            "status",
            "expires_at",
            "cancelled_at",
            "cancellation_source",
            "created_at",
        ]


class BookingHoldResponseSerializer(serializers.ModelSerializer[Booking]):

    facility_id = serializers.UUIDField(source="facility.id", read_only=True)

    class Meta:
        model = Booking
        fields: ClassVar[list[str]] = [
            "id",
            "facility_id",
            "slot_start",
            "slot_end",
            "status",
            "expires_at",
        ]
