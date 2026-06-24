from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone
from freezegun import freeze_time

from apps.users.exceptions import (
    OTPInvalidError,
    OTPMaxAttemptsError,
    TokenExpiredError,
    TokenInvalidError,
)
from apps.users.services import AuthService, OTPService, UserService


@pytest.mark.django_db
class TestOTPCheckLockout:

    def test_no_lockout_set_passes_silently(self, resident: Any) -> None:
        resident.otp_locked_until = None
        resident.save(update_fields=["otp_locked_until"])
        OTPService.check_lockout(resident)

    def test_locked_until_future_raises(self, resident: Any) -> None:
        resident.otp_locked_until = timezone.now() + timedelta(minutes=10)
        resident.save(update_fields=["otp_locked_until"])
        with pytest.raises(OTPMaxAttemptsError):
            OTPService.check_lockout(resident)

    def test_lockout_expired_in_past_does_not_raise(self, resident: Any) -> None:
        resident.otp_locked_until = timezone.now() - timedelta(minutes=1)
        resident.save(update_fields=["otp_locked_until"])
        OTPService.check_lockout(resident)


@pytest.mark.django_db
class TestOTPVerifyStateMachine:

    @pytest.mark.parametrize(
        "prior_count, code, expected_exc, expected_count_after, expect_lockout",
        [
            (0, "999999", OTPInvalidError, 1, False),
            (1, "999999", OTPInvalidError, 2, False),
            (2, "999999", OTPMaxAttemptsError, 0, True),
            (0, "000000", None, 0, False),
            (2, "000000", None, 0, False),
        ],
        ids=[
            "1st_failure_count_becomes_1",
            "2nd_failure_count_becomes_2",
            "3rd_failure_lockout_triggered",
            "success_clears_clean_state",
            "success_after_2_failures_clears_state",
        ],
    )
    def test_otp_verify_state_transition(
        self,
        resident: Any,
        prior_count: int,
        code: str,
        expected_exc: type[Exception] | None,
        expected_count_after: int,
        expect_lockout: bool,
    ) -> None:
        resident.otp_attempt_count = prior_count
        resident.save(update_fields=["otp_attempt_count"])

        if expected_exc is not None:
            with pytest.raises(expected_exc):
                OTPService.verify(resident, code)
        else:
            OTPService.verify(resident, code)

        resident.refresh_from_db()
        assert resident.otp_attempt_count == expected_count_after, (
            f"Expected count={expected_count_after} after verify "
            f"(prior={prior_count}, code={code!r}), got {resident.otp_attempt_count}"
        )
        if expect_lockout:
            assert resident.otp_locked_until is not None
            assert resident.otp_locked_until > timezone.now()
        else:
            if resident.otp_locked_until is not None:
                assert resident.otp_locked_until <= timezone.now()

    def test_verify_while_locked_raises_before_checking_code(
        self, resident: Any
    ) -> None:
        resident.otp_locked_until = timezone.now() + timedelta(minutes=10)
        resident.save(update_fields=["otp_locked_until"])

        with pytest.raises(OTPMaxAttemptsError):
            OTPService.verify(resident, "000000")


@pytest.mark.django_db
class TestAuthServiceRefresh:

    def test_valid_refresh_token_returns_new_pair(self, resident: Any) -> None:
        tokens = AuthService.issue_tokens(resident)
        result = AuthService.refresh_access_token(tokens["refresh_token"])
        assert "access_token" in result
        assert "refresh_token" in result

    def test_expired_refresh_token_raises_token_expired(self, resident: Any) -> None:
        with freeze_time("2020-01-01"):
            tokens = AuthService.issue_tokens(resident)
        with pytest.raises(TokenExpiredError):
            AuthService.refresh_access_token(tokens["refresh_token"])

    @pytest.mark.parametrize(
        "bad_token, test_id",
        [
            ("not.a.jwt", "garbage_string"),
            ("ey.invalid.payload", "invalid_b64_payload"),
            ("", "empty_string"),
        ],
    )
    def test_malformed_token_raises_token_invalid(
        self, resident: Any, bad_token: str, test_id: str
    ) -> None:
        with pytest.raises(TokenInvalidError):
            AuthService.refresh_access_token(bad_token)

    def test_access_token_used_as_refresh_raises_invalid(self, resident: Any) -> None:
        tokens = AuthService.issue_tokens(resident)
        with pytest.raises(TokenInvalidError):
            AuthService.refresh_access_token(tokens["access_token"])


@pytest.mark.django_db
class TestUserServiceUpdatePushToken:

    @pytest.mark.parametrize(
        "new_token, test_id",
        [
            ("ExponentPushToken[new-token-xyz]", "set_new_token"),
            ("", "clear_existing_token"),
        ],
    )
    def test_push_token_update(
        self, resident: Any, new_token: str, test_id: str
    ) -> None:
        if test_id == "clear_existing_token":
            resident.expo_push_token = "ExponentPushToken[old-token]"
            resident.save(update_fields=["expo_push_token"])

        UserService.update_push_token(resident, new_token)

        resident.refresh_from_db()
        assert resident.expo_push_token == new_token
