from __future__ import annotations

from collections.abc import Sequence
from typing import cast

from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.models import User
from apps.users.permissions import IsResident, IsSecurityGuard
from apps.visitors.serializers import (
    VisitorCreateSerializer,
    VisitorOTPVerifySerializer,
    VisitorReadSerializer,
    VisitorVerifyReadSerializer,
)
from apps.visitors.services import VisitorService

# Tuples: immutable → no RUF012; Sequence[type[BasePermission]] satisfies DRF stubs
_RESIDENT: Sequence[type[BasePermission]] = (IsAuthenticated, IsResident)
_SECURITY: Sequence[type[BasePermission]] = (IsAuthenticated, IsSecurityGuard)


class VisitorListCreateView(APIView):
    """
    GET  /api/v1/visitors/  — resident's own visitor passes (US-023)
    POST /api/v1/visitors/  — pre-register a visitor, returns OTP (US-019)
    """

    permission_classes = _RESIDENT

    def get(self, request: Request) -> Response:
        from apps.visitors.models import Visitor

        resident = cast(User, request.user)
        status_filter = request.query_params.get("status")
        qs = Visitor.objects.filter(registered_by=resident).order_by("-created_at")
        if status_filter:
            qs = qs.filter(status=status_filter)

        serializer = VisitorReadSerializer(qs, many=True)
        return Response({"results": serializer.data})

    def post(self, request: Request) -> Response:
        resident = cast(User, request.user)
        serializer = VisitorCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        visitor = VisitorService.register(
            resident=resident,
            visitor_name=str(d["visitor_name"]),
            visitor_phone=str(d.get("visitor_phone") or ""),
            expected_from=d["expected_from"],
            expected_until=d["expected_until"],
        )
        return Response(VisitorReadSerializer(visitor).data, status=201)


class VisitorVerifyView(APIView):
    """
    POST /api/v1/security/visitors/verify/
    Security guard looks up visitor by OTP at the gate (US-021).
    Does NOT mark as arrived — that is a separate explicit action.
    """

    permission_classes = _SECURITY

    def post(self, request: Request) -> Response:
        guard = cast(User, request.user)
        serializer = VisitorOTPVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        visitor = VisitorService.verify_otp(
            otp_code=str(serializer.validated_data["otp_code"]),
            complex_id=str(guard.complex_id),
        )
        return Response(VisitorVerifyReadSerializer(visitor).data)


class VisitorArriveView(APIView):
    """
    POST /api/v1/security/visitors/{id}/arrive/
    Security guard marks visitor as arrived after OTP verification (US-022).
    """

    permission_classes = _SECURITY

    def post(self, request: Request, visitor_id: str) -> Response:
        guard = cast(User, request.user)
        visitor = VisitorService.mark_arrived(
            visitor_id=visitor_id,
            complex_id=str(guard.complex_id),
            security_guard=guard,
        )
        return Response(
            {
                "visitor_id": str(visitor.id),
                "status": visitor.status,
                "arrived_at": visitor.arrived_at,
            }
        )
