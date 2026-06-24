from __future__ import annotations

from collections.abc import Sequence
from typing import cast

import structlog
from django.db import models
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import CursorPagination
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.community.models import Announcement, AnnouncementCategory
from apps.community.serializers import AnnouncementSerializer
from apps.community.services import AnnouncementService
from apps.users.models import User

logger = structlog.get_logger(__name__)

_AUTH: Sequence[type[BasePermission]] = (IsAuthenticated,)


class _AnnouncementCursorPagination(CursorPagination):

    ordering = "-created_at"


class AnnouncementListView(generics.ListAPIView[Announcement]):

    permission_classes = _AUTH
    serializer_class = AnnouncementSerializer
    pagination_class = _AnnouncementCursorPagination

    def get_queryset(self) -> models.QuerySet[Announcement]:
        qs = (
            Announcement.objects.select_related("created_by")
            .filter(is_active=True)
            .order_by("-created_at")
        )
        category = self.request.query_params.get("category")
        if category:
            if category not in AnnouncementCategory.values:
                raise ValidationError(
                    {
                        "category": f"Invalid category '{category}'. "
                        f"Valid values: {AnnouncementCategory.values}"
                    }
                )
            qs = qs.filter(category=category)
        return qs


class AnnouncementRetrieveView(generics.RetrieveAPIView[Announcement]):

    permission_classes = _AUTH
    serializer_class = AnnouncementSerializer

    def get_queryset(self) -> models.QuerySet[Announcement]:
        return Announcement.objects.select_related("created_by").filter(is_active=True)


class AnnouncementMarkReadView(APIView):

    permission_classes = _AUTH

    @extend_schema(
        request=None,
        responses={204: None},
        summary="Mark an announcement as read (idempotent)",
        tags=["community"],
    )
    def post(self, request: Request, pk: str) -> Response:
        announcement = get_object_or_404(
            Announcement.objects.filter(is_active=True),
            pk=pk,
        )
        resident = cast(User, request.user)
        AnnouncementService.mark_read(announcement=announcement, user=resident)
        return Response(status=status.HTTP_204_NO_CONTENT)
