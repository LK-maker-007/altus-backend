from __future__ import annotations

import re
from typing import Any, ClassVar

from rest_framework import serializers

from apps.users.models import User

# ── Phone number validation ────────────────────────────────────────────────────
# WHY E.164 regex (not phonenumbers library):
#   Google's phonenumbers (libphonenumber) is more accurate but adds a 20MB
#   dependency for a single validation. An E.164 regex correctly validates the
#   format constraint: + country code (1-3 digits) + subscriber number (4-14 digits).
#   The minimum total length is 8 digits (e.g. +1234567), maximum is 15 (E.164 spec).
#   For the Indian market (+91 + 10 digits = 13 chars total), this is exact.
#   Source: ITU-T E.164 spec; Twilio phone number formatting docs
_E164_RE = re.compile(r"^\+[1-9]\d{7,14}$")


def _validate_e164(value: str) -> None:
    """Validate phone number is E.164 format (e.g. +919876543210).

    Raises ValidationError with a generic message — never reveal what format
    we accept vs reject (prevents enumeration of valid phone patterns).

    WHY return None (not str):
      DRF field validators must return None or raise ValidationError.
      The field value is not transformed by validators — use validate_<field>()
      on the serializer if normalization is needed. Returning a value here has
      no effect on the serialized data and mypy flags it as a type mismatch
      against Callable[[str], None].
    """
    if not _E164_RE.match(value):
        raise serializers.ValidationError(
            "Enter a valid phone number in international format (e.g. +919876543210)."
        )


# ── Auth flow choices ──────────────────────────────────────────────────────────
_AUTH_FLOW_CHOICES = ["registration", "login"]


class ComplexSearchSerializer(serializers.Serializer[dict[str, Any]]):
    """Query params for GET /auth/complexes/search/"""

    q = serializers.CharField(min_length=3, max_length=200)


class RegisterSerializer(serializers.Serializer[dict[str, Any]]):
    """POST /auth/register/ — validates QR token + unit details."""

    registration_token = serializers.CharField(
        required=False, default="", allow_blank=True
    )
    complex_slug = serializers.CharField(max_length=100)
    # WHY validators=[_validate_e164]: prevents garbage input reaching Twilio.
    # Without validation, any string reaches OTPService.send() → Twilio returns 400
    # → unhandled exception → 500. E.164 is required by all SMS providers.
    phone_number = serializers.CharField(max_length=20, validators=[_validate_e164])
    unit_number = serializers.CharField(max_length=20)
    building_block = serializers.CharField(max_length=50)


class LoginSerializer(serializers.Serializer[dict[str, Any]]):
    """POST /auth/login/ — phone-only, OTP sent on success."""

    phone_number = serializers.CharField(max_length=20, validators=[_validate_e164])


class OTPVerifySerializer(serializers.Serializer[dict[str, Any]]):
    """POST /auth/verify-otp/ — verifies OTP for registration and login."""

    phone_number = serializers.CharField(max_length=20, validators=[_validate_e164])
    code = serializers.CharField(min_length=6, max_length=6)
    # WHY ChoiceField not CharField: 'context' is DRF-reserved. auth_flow must be
    # one of ['registration', 'login'] — any other value is a client bug.
    # A CharField with max_length=20 silently accepted typos like 'registraton'.
    # ChoiceField makes the constraint explicit and surfaces the error to the client.
    auth_flow = serializers.ChoiceField(choices=_AUTH_FLOW_CHOICES)


class TokenRefreshSerializer(serializers.Serializer[dict[str, Any]]):
    """POST /auth/token/refresh/"""

    refresh_token = serializers.CharField()


class LogoutSerializer(serializers.Serializer[dict[str, Any]]):
    """POST /auth/logout/"""

    refresh_token = serializers.CharField()


class ProfileUpdateSerializer(serializers.Serializer[dict[str, Any]]):
    """PATCH /auth/me/ — all fields optional per api-contract."""

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
    """
    GET /auth/me/ — read-only response per api-contract §auth.
    Includes nested unit fields resolved via select_related("unit").

    WHY the caller is responsible for select_related:
      This serializer accesses user.unit.unit_number, user.unit.building_block, etc.
      The caller (MeView.get, OTPVerifyView.post) must pass a User instance with
      the unit relation prefetched — see each view for the select_related call.
      Doing it here would require the serializer to hit the DB, violating the
      principle that serializers are pure data-transformation layers.
    """

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
