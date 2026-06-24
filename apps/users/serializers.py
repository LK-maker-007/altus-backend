from __future__ import annotations

import re
from typing import Any, ClassVar

from rest_framework import serializers

from apps.users.models import User

_E164_RE = re.compile(r"^\+[1-9]\d{7,14}$")


def _validate_e164(value: str) -> None:
    if not _E164_RE.match(value):
        raise serializers.ValidationError(
            "Enter a valid phone number in international format (e.g. +919876543210)."
        )


_AUTH_FLOW_CHOICES = ["registration", "login"]


class ComplexSearchSerializer(serializers.Serializer[dict[str, Any]]):

    q = serializers.CharField(min_length=3, max_length=200)


class RegisterSerializer(serializers.Serializer[dict[str, Any]]):

    registration_token = serializers.CharField(
        required=False, default="", allow_blank=True
    )
    complex_slug = serializers.CharField(max_length=100)
    phone_number = serializers.CharField(max_length=20, validators=[_validate_e164])
    unit_number = serializers.CharField(max_length=20)
    building_block = serializers.CharField(max_length=50)


class LoginSerializer(serializers.Serializer[dict[str, Any]]):

    phone_number = serializers.CharField(max_length=20, validators=[_validate_e164])


class OTPVerifySerializer(serializers.Serializer[dict[str, Any]]):

    phone_number = serializers.CharField(max_length=20, validators=[_validate_e164])
    code = serializers.CharField(min_length=6, max_length=6)
    auth_flow = serializers.ChoiceField(choices=_AUTH_FLOW_CHOICES)


class TokenRefreshSerializer(serializers.Serializer[dict[str, Any]]):

    refresh_token = serializers.CharField()


class LogoutSerializer(serializers.Serializer[dict[str, Any]]):

    refresh_token = serializers.CharField()


class ProfileUpdateSerializer(serializers.Serializer[dict[str, Any]]):

    name = serializers.CharField(max_length=200, required=False)
    vehicle_registrations = serializers.ListField(
        child=serializers.CharField(max_length=20),
        max_length=3,
        required=False,
    )
    expo_push_token = serializers.CharField(
        max_length=200, required=False, allow_blank=True
    )


_USER_READ_FIELDS: list[str] = [
    "id",
    "name",
    "phone_number",
    "role",
    "complex_id",
    "unit_id",
    "unit_number",
    "building_block",
    "floor",
    "vehicle_registrations",
    "is_profile_complete",
    "expo_push_token",
]


class UserReadSerializer(serializers.ModelSerializer["User"]):

    unit_id = serializers.UUIDField(source="unit.id", read_only=True, default=None)
    unit_number = serializers.CharField(
        source="unit.unit_number", read_only=True, default=""
    )
    building_block = serializers.CharField(
        source="unit.building_block", read_only=True, default=""
    )
    floor = serializers.IntegerField(source="unit.floor", read_only=True, default=None)

    class Meta:
        model = User
        fields: ClassVar[list[str]] = _USER_READ_FIELDS
        read_only_fields: ClassVar[list[str]] = _USER_READ_FIELDS
