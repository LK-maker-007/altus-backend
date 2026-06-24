from __future__ import annotations

from rest_framework.exceptions import APIException


class VisitorError(APIException):

    status_code = 400
    default_code = "VISITOR_ERROR"
    default_detail = "A visitor operation error occurred."


class VisitorOTPExpiredError(APIException):

    status_code = 400
    default_code = "VISITOR_OTP_EXPIRED"
    default_detail = "This pass has expired. Contact the resident."


class VisitorOTPUsedError(APIException):

    status_code = 400
    default_code = "VISITOR_OTP_USED"
    default_detail = "This pass has already been used."


class VisitorNotFoundError(APIException):

    status_code = 404
    default_code = "NOT_FOUND"
    default_detail = "Visitor pass not found."
