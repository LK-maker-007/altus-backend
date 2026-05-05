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

_OTP_WINDOW_SECONDS: int = 600  # 10 minutes — per US-004
_OTP_MAX_ATTEMPTS: int = 3  # 3 failures → lockout — per US-003
_OTP_LOCKOUT_SECONDS: int = 900  # 15 minutes — per US-003


class QRTokenService:
    """Validates HMAC-signed QR code registration tokens (US-001)."""

    @staticmethod
    def validate(token: str, complex_slug: str) -> Complex:
        """
        Decode and verify the HMAC-signed QR token.
        Raises RegistrationFailedError on any failure — no field hint exposed (US-003).
        """
        secret = settings.QR_TOKEN_SECRET.encode()
        try:
            # base64 imported at module level — never use __import__() inline
            payload: dict[str, Any] = json.loads(
                base64.urlsafe_b64decode(token + "==").decode()
            )
        except Exception as exc:  # catch-all: malformed token is user input
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
    """
    Self-managed OTP: we generate the code, store in Redis, deliver via SMS,
    and verify against Redis. No dependency on Twilio Verify VerificationChecks.

    WHY self-managed instead of Twilio Verify:
      Twilio Verify VerificationChecks is hard-blocked for Indian numbers on trial
      accounts (20404 regardless of config). Programmable Messaging works fine for
      Verified Caller IDs even on trial. Self-managed OTP also makes us
      provider-agnostic for the verification step — we own the code lifecycle.

    SMS_PROVIDER env var options:
      'mock'   — Dev only. Code '000000' always passes. NEVER use in production.
      'twilio' — Twilio Programmable Messaging. Requires TWILIO_PHONE_NUMBER.
      'msg91'  — MSG91 OTP API. DLT-compliant for India production.
    """

    _REDIS_KEY_PREFIX: str = "yali:otp:"

    @staticmethod
    def _otp_redis_key(phone_number: str) -> str:
        return f"{OTPService._REDIS_KEY_PREFIX}{phone_number}"

    @staticmethod
    def _generate_otp() -> str:
        """Cryptographically secure 6-digit OTP."""
        import secrets

        return f"{secrets.randbelow(1_000_000):06d}"

    @staticmethod
    def _store_otp(phone_number: str, code: str) -> None:
        """
        Store OTP in Redis as SHA-256 hex digest (TTL = _OTP_WINDOW_SECONDS).
        Hashing prevents raw code exposure on a Redis breach.
        """
        import hashlib

        digest = hashlib.sha256(code.encode()).hexdigest()
        cache.set(
            OTPService._otp_redis_key(phone_number), digest, timeout=_OTP_WINDOW_SECONDS
        )

    @staticmethod
    def _check_otp(phone_number: str, code: str) -> bool:
        """
        Compare submitted code against Redis-stored hash.
        Returns False on mismatch or expiry. Deletes key on match (one-time use).
        """
        import hashlib

        stored = cache.get(OTPService._otp_redis_key(phone_number))
        if stored is None:
            return False  # expired or never sent
        if stored == hashlib.sha256(code.encode()).hexdigest():
            cache.delete(OTPService._otp_redis_key(phone_number))
            return True
        return False

    # ── SMS delivery ──────────────────────────────────────────────────────────

    @staticmethod
    def _send_via_twilio_sms(phone_number: str, code: str) -> None:
        """
        Twilio Programmable Messaging (plain SMS, NOT Verify).
        Verify VerificationChecks returns 20404 for Indian numbers on trial.
        Programmable Messaging works for Verified Caller IDs on trial accounts.
        Requires TWILIO_PHONE_NUMBER in settings.
        """
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
        """
        MSG91 Flow OTP API — DLT-compliant for India production.
        We pass our generated code so Redis-based verification stays canonical.
        Requires MSG91_AUTH_KEY + MSG91_TEMPLATE_ID in settings.
        """
        import httpx

        mobile = phone_number.lstrip("+")  # MSG91 expects no '+' prefix
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

    # ── Public API ────────────────────────────────────────────────────────────

    @staticmethod
    def send(phone_number: str) -> None:
        """Generate OTP, store in Redis, deliver via configured SMS provider."""
        if settings.SMS_PROVIDER == "mock":
            logger.info("otp_mock_sent")
            return  # mock: code is always '000000', nothing stored in Redis

        code = OTPService._generate_otp()
        OTPService._store_otp(phone_number, code)

        if settings.SMS_PROVIDER == "msg91":
            OTPService._send_via_msg91(phone_number, code)
        else:
            OTPService._send_via_twilio_sms(phone_number, code)

    @staticmethod
    def check_lockout(user: User) -> None:
        """Raise OTPMaxAttemptsError if the user is currently locked out."""
        if user.otp_locked_until and user.otp_locked_until > timezone.now():
            raise OTPMaxAttemptsError()

    @staticmethod
    def verify(user: User, code: str) -> None:
        """
        Verify OTP. Updates attempt count and lockout on failure.
        Resets counter on success. Raises the correct domain exception on failure.
        """
        OTPService.check_lockout(user)

        if settings.SMS_PROVIDER == "mock":
            valid = code == "000000"
        else:
            # Both 'twilio' and 'msg91' verify against Redis — fully provider-agnostic
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

        # Reset on success — atomic partial save
        user.otp_attempt_count = 0
        user.otp_locked_until = None
        user.save(update_fields=["otp_attempt_count", "otp_locked_until"])


class AuthService:
    """
    Issues and verifies PyJWT tokens.
    JWT payload: user_id, complex_id, unit_id, role, is_profile_complete.
    Custom implementation — no DRF SimpleJWT (per lld.md §1 and api-contract §2.auth).
    Access token: 15 min (US-004). Refresh token: 30 days (US-004).
    """

    @staticmethod
    def issue_tokens(user: User) -> dict[str, str]:
        """Return access_token and refresh_token for the given user."""
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

        # jwt.encode stubs declare dict[str, Any] — TypedDict requires cast here.
        # TypedDict is a plain dict at runtime; cast is a zero-cost annotation only.
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
        """
        Validate refresh token, detect replay attacks, issue a rotated pair,
        and blacklist the old refresh JTI.

        WHY rotation + blacklist (not just new access token):
            If a refresh token is stolen and used after the legitimate client
            already rotated it, cache.get(jti:bl:{old_jti}) will return True
            — replay detected. We raise TokenInvalidError immediately.
            Source: auth_patterns_2026.md §1 Gap 1; descope.com; oneuptime.com.
        """
        try:
            payload = cast(
                JWTRefreshPayload,
                # WHY decode_jwt() (not jwt.decode() directly):
                #   Single decode point — supports zero-downtime JWT_SECRET_KEY
                #   rotation via JWT_PREVIOUS_SECRET_KEY fallback.
                #   If the current key raises InvalidSignatureError, the previous
                #   key is tried automatically.
                #   See apps/core/jwt_utils.py and docs/runbooks/secrets-rotation.md.
                decode_jwt(refresh_token),
            )
        except jwt.ExpiredSignatureError:
            raise TokenExpiredError() from None
        except jwt.InvalidTokenError:
            raise TokenInvalidError() from None

        if payload["token_type"] != JWT_REFRESH_TYPE:
            raise TokenInvalidError()

        old_jti: str = payload["jti"]

        # WHY check blacklist before user lookup:
        #   Fail fast on replay — no DB hit for stolen/reused tokens.
        if cache.get(f"jti:bl:{old_jti}"):
            # Token already used or user logged out — potential theft.
            # MAANG pattern: log for anomaly detection, raise generic error.
            logger.warning("refresh_token_replay_detected", old_jti=old_jti)
            raise TokenInvalidError()

        try:
            user = User.objects.get(id=payload["user_id"], is_active=True)
        except User.DoesNotExist:
            raise TokenInvalidError() from None

        # Issue new pair — both tokens get fresh JTIs (full rotation)
        tokens = AuthService.issue_tokens(user)

        # Blacklist old refresh JTI with its remaining TTL.
        # WHY remaining_ttl not fixed 30d: token may have been issued days ago.
        # TTL = exp - now() → Redis auto-expires the key at exactly the right time.
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
        """
        Blacklist access and/or refresh JTIs in Redis. Called by LogoutView.

        Provides instant session termination — the blacklisted access token is
        rejected by JWTAuthMiddleware._decode_token() before its 15-min natural
        expiry. The refresh token is blocked to prevent further rotation.

        WHY silent on refresh decode failure:
            User may log out with a near-expired or corrupted refresh token.
            We must not block the logout — client-side cleanup always runs.
        Source: auth_patterns_2026.md §1 Gap 2 + §5.
        """
        now = int(time.time())

        if access_jti and access_exp:
            remaining = access_exp - now
            if remaining > 0:
                cache.set(f"jti:bl:{access_jti}", True, timeout=remaining)

        if refresh_token:
            try:
                rt_payload = cast(
                    JWTRefreshPayload,
                    # WHY verify_exp=False: user may log out with a near-expired
                    # refresh token — still blacklist the remaining lifetime.
                    # WHY decode_jwt(): same rotation-safe single decode point.
                    decode_jwt(refresh_token, options={"verify_exp": False}),
                )
                if rt_payload.get("token_type") == JWT_REFRESH_TYPE:
                    remaining = rt_payload["exp"] - now
                    if remaining > 0:
                        cache.set(
                            f"jti:bl:{rt_payload['jti']}", True, timeout=remaining
                        )
            except jwt.InvalidTokenError:
                pass  # Malformed token — nothing to blacklist; logout proceeds


class UserService:
    """Handles user account lifecycle: registration, profile update, push token."""

    @staticmethod
    def get_or_create_for_registration(
        complex_obj: Complex,
        unit: Unit,
        phone_number: str,
    ) -> User:
        """
        Find or create a resident user for this phone + unit combination.
        Raises RegistrationFailedError if unit belongs to a different complex
        or is already linked to a different resident (US-003 — generic message).
        """
        if unit.complex_id != complex_obj.id:
            raise RegistrationFailedError()

        # Check if unit is claimed by a different phone — generic error per US-003
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
                    # NOTE: 'unit' is NOT a FK on User — it's a reverse accessor
                    # on Unit.registered_resident. The link is made below via
                    # unit.registered_resident = user (line 290 below).
                },
            )
            if unit.registered_resident_id is None:
                unit.registered_resident = user
                unit.save(update_fields=["registered_resident_id"])

        return user

    @staticmethod
    def get_or_create_for_login(phone_number: str) -> User:
        """
        Return the active user for this phone number.
        Raises RegistrationFailedError if no account exists — generic (US-003).
        """
        try:
            return User.objects.get(phone_number=phone_number, is_active=True)
        except User.DoesNotExist:
            raise RegistrationFailedError() from None

    @staticmethod
    def update_profile(user: User, name: str, vehicle_registrations: list[str]) -> User:
        """Update profile. Sets is_profile_complete=True when name is non-empty."""
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
        """Silently update the Expo push token. Called on every app launch."""
        user.expo_push_token = token
        user.save(update_fields=["expo_push_token"])
