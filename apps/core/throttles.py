"""
apps/core/throttles.py

Custom DRF rate-limiting throttle classes for the Yali API.

WHY per-phone-number throttling (not just per-IP):
  IP-based throttling alone is insufficient for OTP abuse:
    - Attackers route through proxies / VPNs — 1 attacker = N IPs
    - Victims: their phone number receives SMS spam regardless of IP
  Per-phone throttling limits abuse at the resource level (the phone number that
  receives the SMS), not just the network level. Both layers are needed.

WHY DRF SimpleRateThrottle (not django-ratelimit or custom Redis):
  SimpleRateThrottle uses the Django cache backend (Redis in production) with a
  fixed time-window counter. It is battle-tested, zero extra dependencies, and
  integrates directly with DRF's throttle_classes on each view.
  The limitation (fixed window vs sliding window) is acceptable for OTP endpoints:
  burst abuse within a window is bounded by the 6-digit OTP brute-force window,
  not the rate-limit window. The OTPService lockout (3 attempts, 15 min) is the
  primary brute-force defence; these throttles are the cost-denial defence.

WHY scope-based rates in settings (not hardcoded here):
  Allows rate tuning in settings/production.py or via env without a code deploy.
  Pattern: REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["otp_send"] = "3/hour"

Sources: DRF throttling docs; Stripe API throttling patterns; auth_patterns_2026.md §4
"""

from __future__ import annotations

from django.core.exceptions import ImproperlyConfigured
from rest_framework.request import Request
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView


class OTPSendRateThrottle(SimpleRateThrottle):
    """Rate-limit OTP send requests per phone number.

    Scope: "otp_send" — 3 requests per hour per phone number (configurable in
    REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["otp_send"]).

    Applied to: RegisterView, LoginView.

    WHY per-phone not per-IP:
      A single attacker can rotate IPs. The phone number is the rate-limited
      resource — it receives the SMS. Limit by the target, not the source.

    WHY get_cache_key returns None when phone is absent:
      Returning None disables throttling for the request (DRF contract). The request
      will fail validation at the serializer level anyway (phone_number required).
      We must not throttle based on an absent key — that would collide with other
      None-keyed requests.

    WHY get_rate() returns None on ImproperlyConfigured:
      DRF's allow_request() returns True (unlimited) when self.rate is None.
      This is the DRF-documented way to make a throttle opt-in per environment.
      Test settings set DEFAULT_THROTTLE_RATES={} — throttles self-disable cleanly
      instead of raising ImproperlyConfigured and crashing the test suite.
      Source: DRF throttling.py SimpleRateThrottle.allow_request() — rate=None guard.
    """

    scope = "otp_send"

    def get_rate(self) -> str | None:
        """Return configured rate, or None (= unlimited) if scope not in settings."""
        try:
            return super().get_rate()
        except ImproperlyConfigured:
            return None  # test environment: DEFAULT_THROTTLE_RATES={} → no limit

    def get_cache_key(self, request: Request, view: APIView) -> str | None:
        phone_number = (
            request.data.get("phone_number", "") if hasattr(request, "data") else ""
        )
        if not phone_number:
            # No phone number → serializer will reject; don't apply throttle
            return None
        return self.cache_format % {
            "scope": self.scope,
            "ident": phone_number,
        }


class OTPVerifyRateThrottle(SimpleRateThrottle):
    """Rate-limit OTP verify requests per phone number.

    Scope: "otp_verify" — 5 requests per hour per phone number (configurable).

    Applied to: OTPVerifyView.

    WHY a separate scope from otp_send:
      Verification failure is different from send abuse. An attacker who steals
      a phone number might attempt to brute-force the 6-digit code — they need
      to try many codes, not send many OTPs. Verification needs a tighter retry
      window than send. Different scopes allow independent tuning.

    NOTE: OTPService.check_lockout() provides a 3-attempt / 15-min lockout at
      the service layer. This throttle is the HTTP-layer defence — it fires before
      the service layer is even reached.

    WHY get_rate() returns None on ImproperlyConfigured: see OTPSendRateThrottle.
    """

    scope = "otp_verify"

    def get_rate(self) -> str | None:
        """Return configured rate, or None (= unlimited) if scope not in settings."""
        try:
            return super().get_rate()
        except ImproperlyConfigured:
            return None  # test environment: DEFAULT_THROTTLE_RATES={} → no limit

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
    """Rate-limit token refresh requests by IP address.

    Scope: "token_refresh" — 5 requests/minute per IP (configurable via
    REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["token_refresh"]).

    Applied to: TokenRefreshView.

    WHY per-IP (not per-phone-number):
      The refresh token is opaque — decoding it to extract the phone number
      before validation creates a chicken-and-egg problem (the point of this
      endpoint IS to validate the token). IP-based throttling is the correct
      defence layer for unauthenticated token exchange.

    WHY 5/minute:
      Legitimate clients refresh once per 15 minutes (access token lifetime).
      Allowing 5/minute accommodates network retries while blocking automated
      refresh token stuffing attacks that typically run at 100s/second.

    WHY get_rate() returns None on ImproperlyConfigured: see OTPSendRateThrottle.
    """

    scope = "token_refresh"

    def get_rate(self) -> str | None:
        """Return configured rate, or None (= unlimited) if scope not in settings."""
        try:
            return super().get_rate()
        except ImproperlyConfigured:
            return None  # test environment: DEFAULT_THROTTLE_RATES={} → no limit

    def get_cache_key(self, request: Request, view: APIView) -> str | None:
        # Throttle by client IP (X-Forwarded-For via REMOTE_ADDR after proxy strip).
        # get_ident() reads X-Forwarded-For if NUM_PROXIES is set, else REMOTE_ADDR.
        return self.cache_format % {
            "scope": self.scope,
            "ident": self.get_ident(request),
        }


class BookingHoldRateThrottle(SimpleRateThrottle):
    """Rate-limit booking hold creation per authenticated resident.

    Scope: "booking_hold" — 10 requests/minute per resident (configurable via
    REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["booking_hold"]).

    Applied to: BookingHoldView (POST /bookings/hold/).

    WHY per-resident (user ID) not per-IP:
      BookingHoldView requires IsAuthenticated — every caller has a known identity.
      Per-IP throttling on an authenticated endpoint is weaker: residents on shared
      networks (apartment building, office) share an IP and would compete for the
      same bucket. Per-resident keying is both more precise and harder to spoof.

    WHY 10/minute:
      A real booking interaction takes ≥5 seconds (open app, pick facility, pick
      slot, tap confirm). 10/minute = one per 6 seconds — generous for human use,
      restrictive for scripts. The GiST exclusion constraint and facility row lock
      are the data-integrity backstops; this throttle is the abuse-prevention layer.
      Source: audit §MEDIUM §BookingHoldView no throttle; Stripe API rate-limiting
      patterns 2026 — "authenticated endpoints should throttle by identity, not IP."

    WHY get_rate() returns None on ImproperlyConfigured: see OTPSendRateThrottle.
    """

    scope = "booking_hold"

    def get_rate(self) -> str | None:
        """Return configured rate, or None (= unlimited) if scope not in settings."""
        try:
            return super().get_rate()
        except ImproperlyConfigured:
            return None  # test environment: DEFAULT_THROTTLE_RATES={} → no limit

    def get_cache_key(self, request: Request, view: APIView) -> str | None:
        # Throttle by authenticated user ID — more precise than IP for auth endpoints.
        # Returns None (= skip throttle) if user is anonymous — should never happen
        # since BookingHoldView requires IsAuthenticated, but defensive is correct.
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return None
        return self.cache_format % {
            "scope": self.scope,
            "ident": str(user.pk),
        }
