from __future__ import annotations

from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from apps.users.models import User, UserRole


class IsResident(BasePermission):
    message = "Resident account required."

    def has_permission(self, request: Request, view: APIView) -> bool:
        return bool(
            request.user
            and request.user.is_authenticated
            and isinstance(request.user, User)
            and request.user.role == UserRole.RESIDENT
        )


class IsSecurityGuard(BasePermission):
    message = "Security account required."

    def has_permission(self, request: Request, view: APIView) -> bool:
        return bool(
            request.user
            and request.user.is_authenticated
            and isinstance(request.user, User)
            and request.user.role == UserRole.SECURITY
        )


class IsComplexAdmin(BasePermission):
    message = "Complex admin account required."

    def has_permission(self, request: Request, view: APIView) -> bool:
        return bool(
            request.user
            and request.user.is_authenticated
            and isinstance(request.user, User)
            and request.user.role in (UserRole.COMPLEX_ADMIN, UserRole.PLATFORM_ADMIN)
        )


class IsPlatformAdmin(BasePermission):
    message = "Platform admin account required."

    def has_permission(self, request: Request, view: APIView) -> bool:
        return bool(
            request.user
            and request.user.is_authenticated
            and isinstance(request.user, User)
            and request.user.role == UserRole.PLATFORM_ADMIN
        )


class IsResidentOrAdmin(BasePermission):
    """Resident, complex_admin, or platform_admin.
    Used by facilities endpoints and the SSE slot stream.
    Composite class avoids the DRF | operator (returns OperandHolder, not type-safe).
    """

    message = "Resident or admin account required."

    def has_permission(self, request: Request, view: APIView) -> bool:
        return bool(
            request.user
            and request.user.is_authenticated
            and isinstance(request.user, User)
            and request.user.role
            in (
                UserRole.RESIDENT,
                UserRole.COMPLEX_ADMIN,
                UserRole.PLATFORM_ADMIN,
            )
        )
