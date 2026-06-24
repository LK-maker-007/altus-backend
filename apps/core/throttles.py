from __future__ import annotations

from django.core.exceptions import ImproperlyConfigured
from rest_framework.request import Request
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView


class OTPSendRateThrottle(SimpleRateThrottle):

    scope = "otp_send"

    def get_rate(self) -> str | None:
        try:
            return super().get_rate()
        except ImproperlyConfigured:
            return None

    def get_cache_key(self, request: Request, view: APIView) -> str | None:
        phone_number = (
            request.data.get("phone_number", "") if hasattr(request, "data") else ""
        )
        if not phone_number:
            return None
        return self.cache_format % {
            "scope": self.scope,
            "ident": phone_number,
        }


class OTPVerifyRateThrottle(SimpleRateThrottle):

    scope = "otp_verify"

    def get_rate(self) -> str | None:
        try:
            return super().get_rate()
        except ImproperlyConfigured:
            return None

    def get_cache_key(self, request: Request, view: APIView) -> str | None:
        phone_number = (
            request.data.get("phone_number", "") if hasattr(request, "data") else ""
        )
        if not phone_number:
            return None
        return self.cache_format % {
            "scope": self.scope,
            "ident": phone_number,
        }


class TokenRefreshRateThrottle(SimpleRateThrottle):

    scope = "token_refresh"

    def get_rate(self) -> str | None:
        try:
            return super().get_rate()
        except ImproperlyConfigured:
            return None

    def get_cache_key(self, request: Request, view: APIView) -> str | None:
        return self.cache_format % {
            "scope": self.scope,
            "ident": self.get_ident(request),
        }


class BookingHoldRateThrottle(SimpleRateThrottle):

    scope = "booking_hold"

    def get_rate(self) -> str | None:
        try:
            return super().get_rate()
        except ImproperlyConfigured:
            return None

    def get_cache_key(self, request: Request, view: APIView) -> str | None:
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return None
        return self.cache_format % {
            "scope": self.scope,
            "ident": str(user.pk),
        }
