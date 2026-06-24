from __future__ import annotations

from rest_framework.exceptions import APIException


class PackageNotFoundError(APIException):

    status_code = 404
    default_code = "NOT_FOUND"
    default_detail = "Not found."


class PackageAlreadyCollectedError(APIException):

    status_code = 400
    default_code = "VALIDATION_ERROR"
    default_detail = "This package has already been collected."


class PackagePermissionError(APIException):

    status_code = 403
    default_code = "PERMISSION_DENIED"
    default_detail = "You can only collect packages addressed to your own unit."
