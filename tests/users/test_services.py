from __future__ import annotations

"""
OTPService and AuthService unit tests -- covering uncovered paths in
apps/users/services.py.

MAANG upgrade from the previous version:
  - OTP state machine uses @pytest.mark.parametrize -- not 5 separate methods
  - parametrize covers the full (attempt_count, code, expected_exc, expected_count)
    matrix in a single truth table, making the state machine explicit and readable

Uncovered lines targeted:
  72-73  OTPService.check_lockout -- user is locked -> raises
  85-102 OTPService.verify -- invalid code increments count, hits max -> lockout
  107-111 OTPService.verify -- second failure (count < max) -> OTPInvalidError
  117     OTPService.verify -- success resets counters
  121-142 OTPService.verify -- all paths
  237, 242, 246-247 AuthService.refresh_access_token -- expired / invalid token
  267, 278 AuthService.refresh_access_token -- wrong token_type
  326-327  UserService.update_push_token

Test settings use SMS_PROVIDER=mock, so Twilio is never called.
The mock OTP code is '000000' -- anything else is invalid.
"""

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

# -- OTPService.check_lockout -------------------------------------------------


@pytest.mark.django_db
class TestOTPCheckLockout:
    """OTPService.check_lockout -- three distinct code paths."""

    def test_no_lockout_set_passes_silently(self, resident: Any) -> None:
        """User has no lockout set -> check_lockout passes silently."""
        resident.otp_locked_until = None
        resident.save(update_fields=["otp_locked_until"])
        OTPService.check_lockout(resident)  # must not raise

    def test_locked_until_future_raises(self, resident: Any) -> None:
        """User locked until future -> OTPMaxAttemptsError immediately."""
        resident.otp_locked_until = timezone.now() + timedelta(minutes=10)
        resident.save(update_fields=["otp_locked_until"])
        with pytest.raises(OTPMaxAttemptsError):
            OTPService.check_lockout(resident)

    def test_lockout_expired_in_past_does_not_raise(self, resident: Any) -> None:
        """Lockout timestamp in the past -> lock has expired -> no raise."""
        resident.otp_locked_until = timezone.now() - timedelta(minutes=1)
        resident.save(update_fields=["otp_locked_until"])
        OTPService.check_lockout(resident)  # must not raise


# -- OTPService.verify -- parametrized state machine --------------------------


@pytest.mark.django_db
class TestOTPVerifyStateMachine:
    """
    OTPService.verify -- full state machine as a parametrized truth table.

    This is the MAANG-grade approach: instead of 5 separate test methods,
    we express the OTP failure/success state machine as a single parametrized
    test with explicit (prior_count, code, expected_exc, expected_count_after)
    tuples. The truth table is self-documenting and prevents untested transitions.

    State machine (_OTP_MAX_ATTEMPTS = 3):
      prior_count=0, wrong code -> OTPInvalidError, count=1
      prior_count=1, wrong code -> OTPInvalidError, count=2
      prior_count=2, wrong code -> OTPMaxAttemptsError, count=0 (reset on lockout)
      prior_count=0, correct code -> None, count=0 (reset on success)
      prior_count=2, correct code -> None, count=0 (even with 2 prior failures)
    """

    @pytest.mark.parametrize(
        "prior_count, code, expected_exc, expected_count_after, expect_lockout",
        [
            # 1st failure: count goes 0 -> 1, OTPInvalidError, no lockout
            (0, "999999", OTPInvalidError, 1, False),
            # 2nd failure: count goes 1 -> 2, OTPInvalidError, no lockout
            (1, "999999", OTPInvalidError, 2, False),
            # 3rd failure (max): OTPMaxAttemptsError, count RESET to 0, lockout SET
            (2, "999999", OTPMaxAttemptsError, 0, True),
            # Success with clean slate: count reset to 0, no lockout
            (0, "000000", None, 0, False),
            # Success after 2 prior failures: count reset to 0, locked_until cleared
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
        """
        Parametrized OTP state machine.

        For each (prior_count, code) pair, verify that:
          - The correct exception is raised (or none)
          - otp_attempt_count is the expected value after the call
          - otp_locked_until is set/not-set as expected
        """
        resident.otp_attempt_count = prior_count
        resident.save(update_fields=["otp_attempt_count"])

        if expected_exc is not None:
            with pytest.raises(expected_exc):
                OTPService.verify(resident, code)
        else:
            OTPService.verify(resident, code)  # must not raise

        resident.refresh_from_db()
        assert resident.otp_attempt_count == expected_count_after, (
            f"Expected count={expected_count_after} after verify "
            f"(prior={prior_count}, code={code!r}), got {resident.otp_attempt_count}"
        )
        if expect_lockout:
            assert resident.otp_locked_until is not None
            assert resident.otp_locked_until > timezone.now()
        else:
            # Success or non-lockout failure -- locked_until must be None or past
            if resident.otp_locked_until is not None:
                assert resident.otp_locked_until <= timezone.now()

    def test_verify_while_locked_raises_before_checking_code(
        self, resident: Any
    ) -> None:
        """
        User is locked -> OTPMaxAttemptsError before the code is checked.
        Verifies check_lockout() is the FIRST guard in verify().
        The correct code (000000) is passed -- but the lock gate fires first.
        """
        resident.otp_locked_until = timezone.now() + timedelta(minutes=10)
        resident.save(update_fields=["otp_locked_until"])

        with pytest.raises(OTPMaxAttemptsError):
            OTPService.verify(resident, "000000")  # correct code, but locked


# -- AuthService.refresh_access_token ----------------------------------------


@pytest.mark.django_db
class TestAuthServiceRefresh:
    """
    AuthService.refresh_access_token -- all token validation paths.

    Parametrized where patterns repeat; direct methods where each case
    requires unique setup (freeze_time, specific token construction).
    """

    def test_valid_refresh_token_returns_new_pair(self, resident: Any) -> None:
        """Happy path -- valid refresh token -> new access + refresh pair."""
        tokens = AuthService.issue_tokens(resident)
        result = AuthService.refresh_access_token(tokens["refresh_token"])
        assert "access_token" in result
        assert "refresh_token" in result

    def test_expired_refresh_token_raises_token_expired(self, resident: Any) -> None:
        """
        Expired refresh token -> TokenExpiredError.
        Simulated with freeze_time: token issued in 2020 is expired in 2026.
        """
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
        """Malformed / garbage JWT string -> TokenInvalidError."""
        with pytest.raises(TokenInvalidError):
            AuthService.refresh_access_token(bad_token)

    def test_access_token_used_as_refresh_raises_invalid(self, resident: Any) -> None:
        """
        Access token passed to refresh endpoint -> token_type='access' != 'refresh'
        -> TokenInvalidError. Prevents token reuse attacks.
        """
        tokens = AuthService.issue_tokens(resident)
        with pytest.raises(TokenInvalidError):
            AuthService.refresh_access_token(tokens["access_token"])


# -- UserService.update_push_token -------------------------------------------


@pytest.mark.django_db
class TestUserServiceUpdatePushToken:
    """UserService.update_push_token -- lines 326-327."""

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
        """update_push_token writes expo_push_token and persists to DB."""
        if test_id == "clear_existing_token":
            # Ensure there's something to clear
            resident.expo_push_token = "ExponentPushToken[old-token]"
            resident.save(update_fields=["expo_push_token"])

        UserService.update_push_token(resident, new_token)

        resident.refresh_from_db()
        assert resident.expo_push_token == new_token
