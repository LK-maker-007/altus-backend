from __future__ import annotations

from rest_framework.exceptions import APIException


class PackageNotFoundError(APIException):
    """Unit not found in this complex, or package not found (US-024, US-026)."""

    status_code = 404
    default_code = "NOT_FOUND"
    default_detail = "Not found."


class PackageAlreadyCollectedError(APIException):
    """Package has already been collected — idempotency guard (US-026)."""

    status_code = 400
    default_code = "VALIDATION_ERROR"
    default_detail = "This package has already been collected."
