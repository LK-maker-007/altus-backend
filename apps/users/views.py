from __future__ import annotations

from collections.abc import Sequence
from typing import cast

import structlog
from django.contrib.auth.models import AnonymousUser
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny, BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle
from rest_framework.views import APIView

from apps.core.http import AuthenticatedRequest
from apps.core.models import Complex, Unit
from apps.core.throttles import (
    OTPSendRateThrottle,
    OTPVerifyRateThrottle,
    TokenRefreshRateThrottle,
)
from apps.users.exceptions import RegistrationFailedError
from apps.users.models import User
from apps.users.serializers import (
    ComplexSearchSerializer,
    LoginSerializer,
    LogoutSerializer,
    OTPVerifySerializer,
    ProfileUpdateSerializer,
    RegisterSerializer,
    TokenRefreshSerializer,
    UserReadSerializer,
)
from apps.users.services import AuthService, OTPService, QRTokenService, UserService

logger = structlog.get_logger(__name__)

# Tuples: immutable → no RUF012; Sequence[_PermissionClass] satisfies DRF stubs
_PUBLIC: Sequence[type[BasePermission]] = (AllowAny,)
_AUTH: Sequence[type[BasePermission]] = (IsAuthenticated,)
# Throttle tuples — same immutable tuple pattern as permission_classes above.
# RUF012 requires ClassVar for mutable list class attrs; tuples are immutable.
_OTP_SEND_THROTTLES: Sequence[type[BaseThrottle]] = (OTPSendRateThrottle,)
_OTP_VERIFY_THROTTLES: Sequence[type[BaseThrottle]] = (OTPVerifyRateThrottle,)
# WHY TokenRefreshRateThrottle: refresh endpoint is unauthenticated and was previously
# unthrottled — an open target for refresh token stuffing attacks. Per-IP, 5/min.
_TOKEN_REFRESH_THROTTLES: Sequence[type[BaseThrottle]] = (TokenRefreshRateThrottle,)


def _require_user(request: Request) -> User:
    """
    Safely cast request.user to User.
    Only called in views behind IsAuthenticated — anonymous never reaches here.
    """
    if isinstance(request.user, AnonymousUser):
        raise RegistrationFailedError()
    return request.user  # narrowed by isinstance(AnonymousUser) guard above


class ComplexSearchView(APIView):
    """GET /auth/complexes/search/ — public, no auth required."""

    permission_classes = _PUBLIC

    @extend_schema(
        parameters=[ComplexSearchSerializer],
        responses={200: UserReadSerializer(many=True)},
        summary="Search apartment complexes",
        tags=["auth"],
    )
    def get(self, request: Request) -> Response:
        serializer = ComplexSearchSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        q: str = serializer.validated_data["q"]

        complexes = (
            Complex.objects.filter(name__icontains=q, is_active=True)
            .values("slug", "name", "city", "state")
            .order_by("name")[:20]
        )
        return Response({"results": list(complexes)})


class RegisterView(APIView):
    """POST /auth/register/ — validates unit, sends OTP. No account created yet."""

    permission_classes = _PUBLIC
    # WHY OTPSendRateThrottle: 3 OTP sends/hour per phone number prevents
    # Twilio cost-denial attacks. Without this, one loop can exhaust SMS credits.
    # Source: Google Principal Architect review — "CRITICAL" §rate-limiting
    throttle_classes = _OTP_SEND_THROTTLES

    @extend_schema(
        request=RegisterSerializer,
        responses={
            200: {
                "type": "object",
                "properties": {
                    "status": {"type": "string"},
                    "expires_in_seconds": {"type": "integer"},
                },
            }
        },
        summary="Register: validate unit, send OTP",
        tags=["auth"],
    )
    def post(self, request: Request) -> Response:
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        complex_slug: str = data["complex_slug"]
        registration_token: str = data.get("registration_token", "")

        # US-001: validate HMAC QR token if provided; US-002: slug-only fallback
        if registration_token:
            complex_obj = QRTokenService.validate(registration_token, complex_slug)
        else:
            try:
                complex_obj = Complex.objects.get(slug=complex_slug, is_active=True)
            except Complex.DoesNotExist:
                raise RegistrationFailedError() from None

        # Validate unit — generic error on any failure (no field hint per US-003)
        try:
            unit = Unit.objects.get(
                complex=complex_obj,
                unit_number=data["unit_number"],
                building_block=data["building_block"],
            )
        except Unit.DoesNotExist:
            raise RegistrationFailedError() from None

        phone_number: str = data["phone_number"]

        # Unit already claimed by a different resident — generic error per US-003
        if unit.registered_resident_id is not None:
            # Check if the requesting phone is the existing resident's phone
            # Generic error if not — no field hint (US-003)
            existing_resident = unit.registered_resident
            if (
                existing_resident is None
                or existing_resident.phone_number != phone_number
            ):
                raise RegistrationFailedError()

        user = UserService.get_or_create_for_registration(
            complex_obj, unit, phone_number
        )
        OTPService.check_lockout(user)
        OTPService.send(phone_number)
        logger.info("otp_registration_sent", slug=complex_slug)

        return Response({"status": "otp_sent", "expires_in_seconds": 600})


class LoginView(APIView):
    """POST /auth/login/ — sends OTP for a registered phone number."""

    permission_classes = _PUBLIC
    # Same rationale as RegisterView — OTP send must be rate-limited by phone number.
    throttle_classes = _OTP_SEND_THROTTLES

    @extend_schema(
        request=LoginSerializer,
        responses={
            200: {
                "type": "object",
                "properties": {
                    "status": {"type": "string"},
                    "expires_in_seconds": {"type": "integer"},
                },
            }
        },
        summary="Login: send OTP to registered phone",
        tags=["auth"],
    )
    def post(self, request: Request) -> Response:
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        phone_number: str = serializer.validated_data["phone_number"]

        user = UserService.get_or_create_for_login(phone_number)
        OTPService.check_lockout(user)
        OTPService.send(phone_number)
        logger.info("otp_login_sent")

        return Response({"status": "otp_sent", "expires_in_seconds": 600})


class OTPVerifyView(APIView):
    """
    POST /auth/verify-otp/ — verify OTP for registration or login.
    Returns JWT token pair + user object on success.
    """

    permission_classes = _PUBLIC
    # WHY OTPVerifyRateThrottle: prevents brute-forcing the 6-digit OTP.
    # 5 verify attempts/hour per phone number — complements OTPService.check_lockout()
    # which enforces a 3-attempt / 15-minute lockout at the service layer.
    throttle_classes = _OTP_VERIFY_THROTTLES

    @extend_schema(
        request=OTPVerifySerializer,
        responses={200: UserReadSerializer},
        summary="Verify OTP — returns JWT token pair + user profile",
        tags=["auth"],
    )
    def post(self, request: Request) -> Response:
        serializer = OTPVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        phone_number: str = data["phone_number"]
        code: str = data["code"]

        user = UserService.get_or_create_for_login(phone_number)
        OTPService.verify(user, code)

        tokens = AuthService.issue_tokens(user)
        # WHY select_related("unit"): UserReadSerializer reads unit.unit_number,
        # unit.building_block, unit.floor, unit.id via source traversal.
        # The user returned by get_or_create_for_login has no unit prefetched.
        # Re-fetching with select_related avoids N+1 on the OTP verify response.
        user_with_unit = User.objects.select_related("unit").get(pk=user.pk)
        user_data = UserReadSerializer(user_with_unit).data
        logger.info("otp_verified", auth_flow=data["auth_flow"])

        return Response({**tokens, "user": user_data})


class TokenRefreshView(APIView):
    """POST /auth/token/refresh/ — exchange refresh token for new pair."""

    permission_classes = _PUBLIC
    # WHY TokenRefreshRateThrottle: this is the only public endpoint that was
    # previously unthrottled. Without this, an attacker with a stolen refresh
    # token can replay it at full speed before it's blacklisted. 5/min per IP
    # stops automated stuffing while allowing legitimate client retries.
    throttle_classes = _TOKEN_REFRESH_THROTTLES

    @extend_schema(
        request=TokenRefreshSerializer,
        responses={200: TokenRefreshSerializer},
        summary="Refresh access token using refresh token",
        tags=["auth"],
    )
    def post(self, request: Request) -> Response:
        serializer = TokenRefreshSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tokens = AuthService.refresh_access_token(
            serializer.validated_data["refresh_token"]
        )
        return Response(tokens)


class LogoutView(APIView):
    """POST /auth/logout/ — immediately revoke access + refresh JTIs in Redis."""

    permission_classes = _AUTH

    @extend_schema(
        request=LogoutSerializer,
        responses={204: None},
        summary="Logout — revoke both JTIs in Redis",
        tags=["auth"],
    )
    def post(self, request: Request) -> Response:
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # WHY cast to AuthenticatedRequest:
        #   request is DRF's Request; request._request is the underlying Django
        #   HttpRequest that JWTAuthMiddleware set access_jti / access_exp on.
        auth_req = cast(AuthenticatedRequest, request._request)

        AuthService.revoke_tokens(
            access_jti=auth_req.access_jti,
            access_exp=auth_req.access_exp,
            refresh_token=serializer.validated_data["refresh_token"],
        )

        logger.info("user_logged_out", user_id=str(request.user.pk))
        return Response(status=204)


class MeView(APIView):
    """GET /auth/me/ and PATCH /auth/me/"""

    permission_classes = _AUTH

    @extend_schema(
        responses={200: UserReadSerializer},
        summary="Get current user profile",
        tags=["auth"],
    )
    def get(self, request: Request) -> Response:
        user = _require_user(request)
        # WHY re-fetch with select_related("unit"):
        #   JWTAuthMiddleware._get_user() no longer does select_related("unit")
        #   (removed to avoid a JOIN on every API request — Google review fix).
        #   UserReadSerializer reads unit.unit_number, unit.building_block, etc.
        #   This endpoint is the ONLY one that needs unit fields, so we pay the
        #   JOIN cost here and only here.
        user_with_unit = User.objects.select_related("unit").get(pk=user.pk)
        return Response(UserReadSerializer(user_with_unit).data)

    @extend_schema(
        request=ProfileUpdateSerializer,
        responses={200: UserReadSerializer},
        summary="Update push token, name, or vehicle registrations",
        tags=["auth"],
    )
    def patch(self, request: Request) -> Response:
        serializer = ProfileUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user = _require_user(request)

        if "expo_push_token" in data:
            UserService.update_push_token(user, data["expo_push_token"])

        if "name" in data or "vehicle_registrations" in data:
            UserService.update_profile(
                user,
                name=data.get("name", user.name),
                vehicle_registrations=data.get(
                    "vehicle_registrations", user.vehicle_registrations
                ),
            )

        # Re-fetch with unit for the serializer response
        user_with_unit = User.objects.select_related("unit").get(pk=user.pk)
        return Response(UserReadSerializer(user_with_unit).data)
