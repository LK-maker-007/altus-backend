from __future__ import annotations

from typing import ClassVar

from rest_framework import serializers

from apps.emergency.models import EmergencyContact


class EmergencyContactSerializer(serializers.ModelSerializer[EmergencyContact]):
    """Read serializer for the emergency contacts list endpoint (api-contract §9)."""

    class Meta:
        model = EmergencyContact
        fields: ClassVar[list[str]] = [
            "id",
            "name",
            "role",
            "phone_number",
            "display_order",
        ]
        read_only_fields: ClassVar[list[str]] = fields
