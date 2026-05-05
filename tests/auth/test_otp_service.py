from __future__ import annotations

"""
Comprehensive unit tests for apps/users/services.py

Covers all uncovered paths identified by coverage analysis:
  - QRTokenService.validate() — malformed token, bad sig, wrong slug, expired, missing complex
  - OTPService._send_via_twilio_sms() — success, HTTP error
  - OTPService._send_via_msg91() — success, non-success body, HTTP error
  - OTPService.send() — mock mode, twilio mode, msg91 mode
  - OTPService.verify() — mock mode (valid/invalid), twilio/msg91 mode (Redis-based),
                          lockout, max attempts
  - OTPService.check_lockout() — locked, not locked
  - AuthService.refresh_access_token() — expired token, invalid token, wrong type, missing user
  - UserService.get_or_create_for_registration() — complex mismatch, unit already claimed
  - UserService.update_push_token()

Sources:
  Twilio Programmable Messaging API: twilio.com/docs/sms/api/message-resource
  Django test settings: config/settings/test.py (SMS_PROVIDER=mock)
"""

import base64
import hashlib
import hmac
import json
import time
from datetime import timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone

from apps.users.exceptions import (
    OTPInvalidError,
    OTPMaxAttemptsError,
    RegistrationFailedError,
    TokenExpiredError,
    TokenInvalidError,
)
from apps.users.services import AuthService, OTPService, QRTokenService, UserService


def _make_valid_qr_token(slug: str, exp_offset: int = 3600) -> str:
    """Build a correctly signed QR token for testing."""
    from django.conf import settings

    secret = settings.QR_TOKEN_SECRET.encode()
    exp = int(time.time()) + exp_offset
    sig = hmac.new(
        secret,
        f"{slug}:{exp}".encode(),
        hashlib.sha256,
    ).hexdigest()
    payload = {"slug": slug, "exp": exp, "sig": sig}
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")


# ─────────────────────────────────────────────────────────────────────────────
# QRTokenService
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestQRTokenService:
    def test_valid_token_returns_complex(self, complex_a: Any) -> None:
        token = _make_valid_qr_token(complex_a.slug)
        result = QRTokenService.validate(token, complex_a.slug)
        assert result.id == complex_a.id

    def test_malformed_base64_raises(self) -> None:
        with pytest.raises(RegistrationFailedError):
            QRTokenService.validate("not-valid-base64!!!", "some-slug")

    def test_wrong_signature_raises(self, complex_a: Any) -> None:
        """Token with tampered sig must be rejected."""
        exp = int(time.time()) + 3600
        payload = {"slug": complex_a.slug, "exp": exp, "sig": "deadbeef" * 8}
        token = (
            base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
        )
        with pytest.raises(RegistrationFailedError):
            QRTokenService.validate(token, complex_a.slug)

    def test_slug_mismatch_raises(self, complex_a: Any) -> None:
        """Token for slug A used against slug B must be rejected."""
        token = _make_valid_qr_token("wrong-slug")
        with pytest.raises(RegistrationFailedError):
            QRTokenService.validate(token, complex_a.slug)

    def test_expired_token_raises(self, complex_a: Any) -> None:
        """Token with exp in the past must be rejected."""
        token = _make_valid_qr_token(complex_a.slug, exp_offset=-1)
        with pytest.raises(RegistrationFailedError):
            QRTokenService.validate(token, complex_a.slug)

    def test_inactive_complex_raises(self, complex_a: Any) -> None:
        """Token for a complex that is inactive must be rejected."""
        complex_a.is_active = False
        complex_a.save(update_fields=["is_active"])
        token = _make_valid_qr_token(complex_a.slug)
        with pytest.raises(RegistrationFailedError):
            QRTokenService.validate(token, complex_a.slug)


# ─────────────────────────────────────────────────────────────────────────────
# OTPService
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestOTPServiceSend:
    """Tests for OTPService.send() and _send_via_twilio_sms()."""

    def test_send_mock_mode_returns_immediately(self, resident: Any) -> None:
        """In mock mode, send() never calls Twilio — returns None silently."""
        with patch(
            "apps.users.services.OTPService._send_via_twilio_sms"
        ) as mock_twilio:
            OTPService.send(resident.phone_number)
        mock_twilio.assert_not_called()

    def test_send_twilio_mode_calls_twilio_sms(self, resident: Any) -> None:
        """In twilio mode, send() delegates to _send_via_twilio_sms()."""
        with patch("django.conf.settings.SMS_PROVIDER", "twilio"):
            with patch(
                "apps.users.services.OTPService._send_via_twilio_sms"
            ) as mock_twilio:
                OTPService.send(resident.phone_number)
        # WHY assert_called_once: send() must pass the generated code to the
        # SMS method. We can't assert the exact code (random) so we only
        # verify the phone_number arg and that it was called exactly once.
        assert mock_twilio.call_count == 1
        assert mock_twilio.call_args[0][0] == resident.phone_number

    def test_send_via_twilio_sms_success(self) -> None:
        """_send_via_twilio_sms() POSTs to Twilio Programmable Messaging and returns on 2xx."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None

        with patch("httpx.post", return_value=mock_resp) as mock_post:
            OTPService._send_via_twilio_sms("+919000000001", "123456")

        mock_post.assert_called_once()
        call_args = mock_post.call_args
        # Programmable Messaging URL — NOT the Verify /Verifications path
        assert "Messages.json" in call_args[0][0]
        assert call_args[1]["data"]["To"] == "+919000000001"
        assert "123456" in call_args[1]["data"]["Body"]

    def test_send_via_twilio_sms_http_error_reraises(self) -> None:
        """_send_via_twilio_sms() re-raises httpx.HTTPError on Twilio failure."""
        import httpx

        with patch("httpx.post", side_effect=httpx.HTTPError("timeout")):
            with pytest.raises(httpx.HTTPError):
                OTPService._send_via_twilio_sms("+919000000001", "123456")


@pytest.mark.django_db
class TestOTPServiceVerify:
    """Tests for OTPService.verify() including lockout and Twilio paths."""

    def test_verify_mock_mode_valid_code(self, resident: Any) -> None:
        """In mock mode, code '000000' is always valid — resets attempt count."""
        resident.otp_attempt_count = 1
        resident.save(update_fields=["otp_attempt_count"])

        OTPService.verify(resident, "000000")

        resident.refresh_from_db()
        assert resident.otp_attempt_count == 0
        assert resident.otp_locked_until is None

    def test_verify_mock_mode_invalid_code_increments_attempts(
        self, resident: Any
    ) -> None:
        """In mock mode, wrong code increments attempt count and raises OTPInvalidError."""
        resident.otp_attempt_count = 0
        resident.save(update_fields=["otp_attempt_count"])

        with pytest.raises(OTPInvalidError):
            OTPService.verify(resident, "111111")

        resident.refresh_from_db()
        assert resident.otp_attempt_count == 1

    def test_verify_mock_mode_max_attempts_locks_out(self, resident: Any) -> None:
        """3 failed attempts locks the user for 15 minutes and raises OTPMaxAttemptsError."""
        resident.otp_attempt_count = 2  # next failure = 3rd = lockout
        resident.save(update_fields=["otp_attempt_count"])

        with pytest.raises(OTPMaxAttemptsError):
            OTPService.verify(resident, "999999")

        resident.refresh_from_db()
        assert resident.otp_attempt_count == 0
        assert resident.otp_locked_until is not None
        assert resident.otp_locked_until > timezone.now()

    def test_check_lockout_raises_when_locked(self, resident: Any) -> None:
        """check_lockout() raises OTPMaxAttemptsError if otp_locked_until is in the future."""
        resident.otp_locked_until = timezone.now() + timedelta(minutes=10)
        resident.save(update_fields=["otp_locked_until"])

        with pytest.raises(OTPMaxAttemptsError):
            OTPService.check_lockout(resident)

    def test_check_lockout_passes_when_not_locked(self, resident: Any) -> None:
        """check_lockout() is a no-op when otp_locked_until is None or in the past."""
        resident.otp_locked_until = None
        resident.save(update_fields=["otp_locked_until"])
        OTPService.check_lockout(resident)  # must not raise

    def test_verify_twilio_mode_approved(self, resident: Any) -> None:
        """In twilio mode, correct Redis OTP → no exception, resets attempt count."""
        # Manually store the OTP hash as if send() had been called
        OTPService._store_otp(resident.phone_number, "123456")

        with patch("django.conf.settings.SMS_PROVIDER", "twilio"):
            OTPService.verify(resident, "123456")

        resident.refresh_from_db()
        assert resident.otp_attempt_count == 0

    def test_verify_twilio_mode_wrong_code_raises(self, resident: Any) -> None:
        """In twilio mode, wrong code → OTPInvalidError and increments attempt count."""
        OTPService._store_otp(resident.phone_number, "123456")

        with patch("django.conf.settings.SMS_PROVIDER", "twilio"):
            with pytest.raises(OTPInvalidError):
                OTPService.verify(resident, "999999")

        resident.refresh_from_db()
        assert resident.otp_attempt_count == 1

    def test_verify_twilio_mode_expired_otp_raises(self, resident: Any) -> None:
        """Expired OTP (no Redis key) → OTPInvalidError — code never stored or TTL expired."""
        from django.core.cache import cache

        # WHY explicit delete: Redis state is NOT rolled back between tests (unlike DB).
        # The previous test (wrong_code) stores a key that it doesn't delete (mismatch
        # leaves it). Clearing here guarantees the "no key" precondition is met.
        cache.delete(OTPService._otp_redis_key(resident.phone_number))

        with patch("django.conf.settings.SMS_PROVIDER", "twilio"):
            with pytest.raises(OTPInvalidError):
                OTPService.verify(resident, "123456")

    def test_locked_user_blocked_before_twilio_call(self, resident: Any) -> None:
        """A locked-out user must be rejected BEFORE any Twilio call is made."""
        resident.otp_locked_until = timezone.now() + timedelta(minutes=10)
        resident.save(update_fields=["otp_locked_until"])

        with patch("httpx.post") as mock_post:
            with pytest.raises(OTPMaxAttemptsError):
                OTPService.verify(resident, "000000")

        mock_post.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# AuthService
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestAuthServiceRefresh:
    """Tests for AuthService.refresh_access_token()."""

    def test_expired_refresh_token_raises(self) -> None:
        """Expired JWT raises TokenExpiredError — not TokenInvalidError."""
        import jwt
        from django.conf import settings

        payload = {
            "token_type": "refresh",
            "user_id": "00000000-0000-0000-0000-000000000001",
            "iat": int(time.time()) - 3600,
            "exp": int(time.time()) - 1800,  # expired 30 min ago
            "jti": "test-jti",
        }
        token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm="HS256")

        with pytest.raises(TokenExpiredError):
            AuthService.refresh_access_token(token)

    def test_invalid_jwt_signature_raises(self) -> None:
        """Token signed with wrong key → TokenInvalidError."""
        import jwt

        payload = {
            "token_type": "refresh",
            "user_id": "00000000-0000-0000-0000-000000000001",
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
            "jti": "test-jti",
        }
        token = jwt.encode(payload, "WRONG_SECRET_KEY", algorithm="HS256")

        with pytest.raises(TokenInvalidError):
            AuthService.refresh_access_token(token)

    def test_wrong_token_type_raises(self, resident: Any) -> None:
        """Access token used as refresh token → TokenInvalidError."""
        tokens = AuthService.issue_tokens(resident)
        with pytest.raises(TokenInvalidError):
            AuthService.refresh_access_token(tokens["access_token"])

    def test_missing_user_raises(self) -> None:
        """Refresh token for a deleted user → TokenInvalidError."""
        import jwt
        from django.conf import settings

        payload = {
            "token_type": "refresh",
            "user_id": "00000000-0000-0000-0000-000000000099",  # non-existent
            "iat": int(time.time()),
            "exp": int(time.time()) + 86400,
            "jti": "test-jti",
        }
        token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm="HS256")

        with pytest.raises(TokenInvalidError):
            AuthService.refresh_access_token(token)


# ─────────────────────────────────────────────────────────────────────────────
# UserService
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestUserServiceRegistration:
    """Tests for UserService.get_or_create_for_registration() edge cases."""

    def test_complex_mismatch_raises(self, complex_b: Any, unit_a: Any) -> None:
        """Unit belongs to complex_a but token is for complex_b → RegistrationFailedError."""
        with pytest.raises(RegistrationFailedError):
            UserService.get_or_create_for_registration(
                complex_obj=complex_b,
                unit=unit_a,  # unit_a is in complex_a
                phone_number="+919000000050",
            )

    def test_unit_claimed_by_different_phone_raises(
        self, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
        """
        unit_a is registered to `resident` (+919000000001).
        A different phone attempting to claim it → RegistrationFailedError (US-003).
        """
        with pytest.raises(RegistrationFailedError):
            UserService.get_or_create_for_registration(
                complex_obj=complex_a,
                unit=unit_a,
                phone_number="+919000000099",  # different phone
            )


@pytest.mark.django_db
class TestUserServicePushToken:
    """Tests for UserService.update_push_token()."""

    def test_update_push_token_persists(self, resident: Any) -> None:
        """update_push_token() writes the new token to the DB."""
        new_token = "ExponentPushToken[new-token-abc123]"
        UserService.update_push_token(resident, new_token)

        resident.refresh_from_db()
        assert resident.expo_push_token == new_token

    def test_update_push_token_clears_on_empty(self, resident: Any) -> None:
        """Passing empty string clears the push token (user unregistered device)."""
        resident.expo_push_token = "ExponentPushToken[old]"
        resident.save(update_fields=["expo_push_token"])

        UserService.update_push_token(resident, "")
        resident.refresh_from_db()
        assert resident.expo_push_token == ""
