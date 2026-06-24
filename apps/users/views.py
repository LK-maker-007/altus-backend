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

_PUBLIC: Sequence[type[BasePermission]] = (AllowAny,)
_AUTH: Sequence[type[BasePermission]] = (IsAuthenticated,)
_OTP_SEND_THROTTLES: Sequence[type[BaseThrottle]] = (OTPSendRateThrottle,)
_OTP_VERIFY_THROTTLES: Sequence[type[BaseThrottle]] = (OTPVerifyRateThrottle,)
_TOKEN_REFRESH_THROTTLES: Sequence[type[BaseThrottle]] = (TokenRefreshRateThrottle,)


def _require_user(request: Request) -> User:
    if isinstance(request.user, AnonymousUser):
        raise RegistrationFailedError()
    return request.user


class ComplexSearchView(APIView):

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

    permission_classes = _PUBLIC
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

        if registration_token:
            complex_obj = QRTokenService.validate(registration_token, complex_slug)
        else:
            try:
                complex_obj = Complex.objects.get(slug=complex_slug, is_active=True)
            except Complex.DoesNotExist:
                raise RegistrationFailedError() from None

        try:
            unit = Unit.objects.get(
                complex=complex_obj,
                unit_number=data["unit_number"],
                building_block=data["building_block"],
            )
        except Unit.DoesNotExist:
            raise RegistrationFailedError() from None

        phone_number: str = data["phone_number"]

        if unit.registered_resident_id is not None:
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

    permission_classes = _PUBLIC
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

    permission_classes = _PUBLIC
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
        user_with_unit = User.objects.select_related("unit").get(pk=user.pk)
        user_data = UserReadSerializer(user_with_unit).data
        logger.info("otp_verified", auth_flow=data["auth_flow"])

        return Response({**tokens, "user": user_data})


class TokenRefreshView(APIView):

    permission_classes = _PUBLIC
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

        auth_req = cast(AuthenticatedRequest, request._request)

        AuthService.revoke_tokens(
            access_jti=auth_req.access_jti,
            access_exp=auth_req.access_exp,
            refresh_token=serializer.validated_data["refresh_token"],
        )

        logger.info("user_logged_out", user_id=str(request.user.pk))
        return Response(status=204)


class MeView(APIView):

    permission_classes = _AUTH

    @extend_schema(
        responses={200: UserReadSerializer},
        summary="Get current user profile",
        tags=["auth"],
    )
    def get(self, request: Request) -> Response:
        user = _require_user(request)
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

        user_with_unit = User.objects.select_related("unit").get(pk=user.pk)
        return Response(UserReadSerializer(user_with_unit).data)
