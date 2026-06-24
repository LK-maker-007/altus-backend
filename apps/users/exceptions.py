from __future__ import annotations

from rest_framework.exceptions import APIException


class OTPInvalidError(APIException):
    status_code = 400
    default_code = "OTP_INVALID"
    default_detail = "Incorrect OTP code."


class OTPExpiredError(APIException):
    status_code = 400
    default_code = "OTP_EXPIRED"
    default_detail = "Code expired. Request a new one."


class OTPMaxAttemptsError(APIException):
    status_code = 429
    default_code = "OTP_MAX_ATTEMPTS"
    default_detail = "Too many incorrect attempts. Try again in 15 minutes."


_REGISTRATION_FAILED_MSG = (
    "Registration failed. "
    "Please verify your details with your complex administrator."
)


class RegistrationFailedError(APIException):

    status_code = 400
    default_code = "REGISTRATION_FAILED"
    default_detail = _REGISTRATION_FAILED_MSG


class TokenInvalidError(APIException):
    status_code = 401
    default_code = "TOKEN_INVALID"
    default_detail = "Token is invalid or malformed."


class TokenExpiredError(APIException):
    status_code = 401
    default_code = "TOKEN_EXPIRED"
    default_detail = "Token has expired."
