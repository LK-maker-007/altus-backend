from __future__ import annotations

from rest_framework.exceptions import APIException


class TicketNotFoundError(APIException):

    status_code = 404
    default_code = "NOT_FOUND"
    default_detail = "Maintenance ticket not found."


class TicketPhotoValidationError(APIException):

    status_code = 400
    default_code = "VALIDATION_ERROR"
    default_detail = "Photo validation failed."


class TicketAccessDeniedError(APIException):

    status_code = 403
    default_code = "PERMISSION_DENIED"
    default_detail = "You do not have permission to access this ticket."
