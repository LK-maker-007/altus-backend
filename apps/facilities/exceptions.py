from __future__ import annotations

from rest_framework.exceptions import APIException


class FacilityNotFoundError(APIException):
    status_code = 404
    default_code = "NOT_FOUND"
    default_detail = "Facility not found."
