from __future__ import annotations

from rest_framework.exceptions import APIException


# 404 Not Found — inherits APIException directly, not BookingError (409)
class FacilityNotFoundError(APIException):
    status_code = 404
    default_code = "NOT_FOUND"
    default_detail = "Facility not found."
