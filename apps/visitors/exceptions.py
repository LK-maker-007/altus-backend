from __future__ import annotations

from rest_framework.exceptions import APIException


class VisitorError(APIException):
    """Base for all visitor domain errors."""

    status_code = 400
    default_code = "VISITOR_ERROR"
    default_detail = "A visitor operation error occurred."


class VisitorOTPExpiredError(APIException):
    """Visitor pass is outside its valid time window (US-021)."""

    status_code = 400
    default_code = "VISITOR_OTP_EXPIRED"
    default_detail = "This pass has expired. Contact the resident."


class VisitorOTPUsedError(APIException):
    """Visitor pass has already been consumed (status = arrived)."""

    status_code = 400
    default_code = "VISITOR_OTP_USED"
    default_detail = "This pass has already been used."


class VisitorNotFoundError(APIException):
    """OTP not found in this complex — generic message, reveals nothing."""

    status_code = 404
    default_code = "NOT_FOUND"
    default_detail = "Visitor pass not found."
