from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from datetime import timedelta
from typing import Any, cast

import jwt
import structlog
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from apps.core.jwt_utils import decode_jwt
from apps.core.models import Complex, Unit
from apps.core.schemas import (
    JWT_ACCESS_TYPE,
    JWT_REFRESH_TYPE,
    JWTAccessPayload,
    JWTRefreshPayload,
)
from apps.users.exceptions import (
    OTPInvalidError,
    OTPMaxAttemptsError,
    RegistrationFailedError,
    TokenExpiredError,
    TokenInvalidError,
)
from apps.users.models import User, UserRole

logger = structlog.get_logger(__name__)

_OTP_WINDOW_SECONDS: int = 600
_OTP_MAX_ATTEMPTS: int = 3
_OTP_LOCKOUT_SECONDS: int = 900


class QRTokenService:

    @staticmethod
    def validate(token: str, complex_slug: str) -> Complex:
        secret = settings.QR_TOKEN_SECRET.encode()
        try:
            payload: dict[str, Any] = json.loads(
                base64.urlsafe_b64decode(token + "==").decode()
            )
        except Exception as exc:
            logger.warning("qr_token_decode_failed", exc_info=True)
            raise RegistrationFailedError() from exc

        expected_sig = hmac.new(
            secret,
            f"{payload.get('slug', '')}:{payload.get('exp', '')}".encode(),
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(expected_sig, payload.get("sig", "")):
            raise RegistrationFailedError()

        if payload.get("slug") != complex_slug:
            raise RegistrationFailedError()

        if payload.get("exp", 0) < int(time.time()):
            raise RegistrationFailedError()

        try:
            return Complex.objects.get(slug=complex_slug, is_active=True)
        except Complex.DoesNotExist:
            raise RegistrationFailedError() from None


class OTPService:

    _REDIS_KEY_PREFIX: str = "yali:otp:"

    @staticmethod
    def _otp_redis_key(phone_number: str) -> str:
        return f"{OTPService._REDIS_KEY_PREFIX}{phone_number}"

    @staticmethod
    def _generate_otp() -> str:
        import secrets

        return f"{secrets.randbelow(1_000_000):06d}"

    @staticmethod
    def _store_otp(phone_number: str, code: str) -> None:
        import hashlib

        digest = hashlib.sha256(code.encode()).hexdigest()
        cache.set(
            OTPService._otp_redis_key(phone_number), digest, timeout=_OTP_WINDOW_SECONDS
        )

    @staticmethod
    def _check_otp(phone_number: str, code: str) -> bool:
        import hashlib

        stored = cache.get(OTPService._otp_redis_key(phone_number))
        if stored is None:
            return False
        if stored == hashlib.sha256(code.encode()).hexdigest():
            cache.delete(OTPService._otp_redis_key(phone_number))
            return True
        return False

    @staticmethod
    def _send_via_twilio_sms(phone_number: str, code: str) -> None:
        import httpx

        url = (
            f"https://api.twilio.com/2010-04-01/Accounts/"
            f"{settings.TWILIO_ACCOUNT_SID}/Messages.json"
        )
        sms_body = (
            f"Your Yali OTP is: {code}\n"
            "Valid for 10 minutes. Do not share this code."
        )
        try:
            resp = httpx.post(
                url,
                data={
                    "From": settings.TWILIO_PHONE_NUMBER,
                    "To": phone_number,
                    "Body": sms_body,
                },
                auth=(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN),
                timeout=10.0,
            )
            resp.raise_for_status()
            logger.info("otp_sms_sent", provider="twilio", to=phone_number)
        except httpx.HTTPError:
            logger.error("otp_send_failed", provider="twilio", exc_info=True)
            raise

    @staticmethod
    def _send_via_msg91(phone_number: str, code: str) -> None:
        import httpx

        mobile = phone_number.lstrip("+")
        try:
            resp = httpx.post(
                "https://control.msg91.com/api/v5/otp",
                headers={
                    "authkey": settings.MSG91_AUTH_KEY,
                    "content-type": "application/json",
                },
                json={
                    "mobile": mobile,
                    "otp": code,
                    "template_id": settings.MSG91_TEMPLATE_ID,
                    "otp_length": 6,
                    "otp_expiry": 10,
                },
                timeout=10.0,
            )
            body = resp.json()
            if body.get("type") != "success":
                logger.error("otp_send_failed", provider="msg91", body=body)
                raise RuntimeError(
                    f"MSG91 send failed: {body.get('message', 'unknown')}"
                )
            logger.info("otp_sms_sent", provider="msg91", to=phone_number)
        except httpx.HTTPError:
            logger.error("otp_send_failed", provider="msg91", exc_info=True)
            raise

    @staticmethod
    def send(phone_number: str) -> None:
        if settings.SMS_PROVIDER == "mock":
            logger.info("otp_mock_sent")
            return

        code = OTPService._generate_otp()
        OTPService._store_otp(phone_number, code)

        if settings.SMS_PROVIDER == "msg91":
            OTPService._send_via_msg91(phone_number, code)
        else:
            OTPService._send_via_twilio_sms(phone_number, code)

    @staticmethod
    def check_lockout(user: User) -> None:
        if user.otp_locked_until and user.otp_locked_until > timezone.now():
            raise OTPMaxAttemptsError()

    @staticmethod
    def verify(user: User, code: str) -> None:
        OTPService.check_lockout(user)

        if settings.SMS_PROVIDER == "mock":
            valid = code == "000000"
        else:
            valid = OTPService._check_otp(user.phone_number, code)

        if not valid:
            user.otp_attempt_count += 1
            if user.otp_attempt_count >= _OTP_MAX_ATTEMPTS:
                user.otp_locked_until = timezone.now() + timedelta(
                    seconds=_OTP_LOCKOUT_SECONDS
                )
                user.otp_attempt_count = 0
                user.save(update_fields=["otp_attempt_count", "otp_locked_until"])
                raise OTPMaxAttemptsError()
            user.save(update_fields=["otp_attempt_count"])
            raise OTPInvalidError()

        user.otp_attempt_count = 0
        user.otp_locked_until = None
        user.save(update_fields=["otp_attempt_count", "otp_locked_until"])


class AuthService:

    @staticmethod
    def issue_tokens(user: User) -> dict[str, str]:
        now = int(time.time())
        unit_id = str(user.unit_id) if user.unit_id else None

        access_payload = JWTAccessPayload(
            token_type=JWT_ACCESS_TYPE,
            user_id=str(user.id),
            complex_id=str(user.complex_id) if user.complex_id else None,
            unit_id=unit_id,
            role=str(user.role),
            is_profile_complete=bool(user.is_profile_complete),
            iat=now,
            exp=now + settings.JWT_ACCESS_TOKEN_LIFETIME_MINUTES * 60,
            jti=str(uuid.uuid4()),
        )

        refresh_payload = JWTRefreshPayload(
            token_type=JWT_REFRESH_TYPE,
            user_id=str(user.id),
            iat=now,
            exp=now + settings.JWT_REFRESH_TOKEN_LIFETIME_DAYS * 86400,
            jti=str(uuid.uuid4()),
        )

        access_token = jwt.encode(
            cast(dict[str, Any], access_payload),
            settings.JWT_SECRET_KEY,
            algorithm="HS256",
        )
        refresh_token = jwt.encode(
            cast(dict[str, Any], refresh_payload),
            settings.JWT_SECRET_KEY,
            algorithm="HS256",
        )
        return {"access_token": access_token, "refresh_token": refresh_token}

    @staticmethod
    def refresh_access_token(refresh_token: str) -> dict[str, str]:
        try:
            payload = cast(
                JWTRefreshPayload,
                decode_jwt(refresh_token),
            )
        except jwt.ExpiredSignatureError:
            raise TokenExpiredError() from None
        except jwt.InvalidTokenError:
            raise TokenInvalidError() from None

        if payload["token_type"] != JWT_REFRESH_TYPE:
            raise TokenInvalidError()

        old_jti: str = payload["jti"]

        if cache.get(f"jti:bl:{old_jti}"):
            logger.warning("refresh_token_replay_detected", old_jti=old_jti)
            raise TokenInvalidError()

        try:
            user = User.objects.get(id=payload["user_id"], is_active=True)
        except User.DoesNotExist:
            raise TokenInvalidError() from None

        tokens = AuthService.issue_tokens(user)

        remaining_ttl = payload["exp"] - int(time.time())
        if remaining_ttl > 0:
            cache.set(f"jti:bl:{old_jti}", True, timeout=remaining_ttl)

        logger.info("token_rotated", user_id=payload["user_id"])
        return tokens

    @staticmethod
    def revoke_tokens(
        access_jti: str | None,
        access_exp: int | None,
        refresh_token: str | None,
    ) -> None:
        now = int(time.time())

        if access_jti and access_exp:
            remaining = access_exp - now
            if remaining > 0:
                cache.set(f"jti:bl:{access_jti}", True, timeout=remaining)

        if refresh_token:
            try:
                rt_payload = cast(
                    JWTRefreshPayload,
                    decode_jwt(refresh_token, options={"verify_exp": False}),
                )
                if rt_payload.get("token_type") == JWT_REFRESH_TYPE:
                    remaining = rt_payload["exp"] - now
                    if remaining > 0:
                        cache.set(
                            f"jti:bl:{rt_payload['jti']}", True, timeout=remaining
                        )
            except jwt.InvalidTokenError:
                pass


class UserService:

    @staticmethod
    def get_or_create_for_registration(
        complex_obj: Complex,
        unit: Unit,
        phone_number: str,
    ) -> User:
        if unit.complex_id != complex_obj.id:
            raise RegistrationFailedError()

        existing_user_id = (
            User.objects.filter(phone_number=phone_number)
            .values_list("id", flat=True)
            .first()
        )
        if unit.registered_resident_id is not None and str(
            unit.registered_resident_id
        ) != str(existing_user_id or ""):
            raise RegistrationFailedError()

        with transaction.atomic():
            user, _ = User.objects.get_or_create(
                phone_number=phone_number,
                defaults={
                    "complex": complex_obj,
                    "role": UserRole.RESIDENT,
                },
            )
            if unit.registered_resident_id is None:
                unit.registered_resident = user
                unit.save(update_fields=["registered_resident_id"])

        return user

    @staticmethod
    def get_or_create_for_login(phone_number: str) -> User:
        try:
            return User.objects.get(phone_number=phone_number, is_active=True)
        except User.DoesNotExist:
            raise RegistrationFailedError() from None

    @staticmethod
    def update_profile(user: User, name: str, vehicle_registrations: list[str]) -> User:
        user.name = name
        user.vehicle_registrations = vehicle_registrations
        user.is_profile_complete = bool(name.strip())
        user.save(
            update_fields=[
                "name",
                "vehicle_registrations",
                "is_profile_complete",
            ]
        )
        return user

    @staticmethod
    def update_push_token(user: User, token: str) -> None:
        user.expo_push_token = token
        user.save(update_fields=["expo_push_token"])
