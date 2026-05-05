from __future__ import annotations

from collections.abc import Sequence
from typing import cast

import structlog
from django.db import models
from django.shortcuts import get_object_or_404
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
    """Cursor pagination for announcements, newest first.

    Explicit ordering prevents the global CursorPagination default
    from applying field "-created" which does not exist on Announcement.
    The correct field is "-created_at". Same pattern as
    _TicketCursorPagination in maintenance/views.py.
    """

    ordering = "-created_at"


class AnnouncementListView(generics.ListAPIView[Announcement]):
    """GET /community/announcements/ — list active announcements, newest first.

    Scoped to the authenticated user's complex via ComplexScopedModel manager.
    Supports optional `category` filter per api-contract §8.
    Uses cursor pagination with explicit ordering (see _AnnouncementCursorPagination).
    """

    permission_classes = _AUTH
    serializer_class = AnnouncementSerializer
    pagination_class = _AnnouncementCursorPagination

    def get_queryset(self) -> models.QuerySet[Announcement]:
        # WHY select_related('created_by'): AnnouncementSerializer.get_posted_by()
        # accesses obj.created_by.name for every item. Without this,
        # a page of N announcements fires N+1 queries. select_related collapses
        # the JOIN into a single query. Source: Django docs §12 — select_related.
        qs = (
            Announcement.objects.select_related("created_by")
            .filter(is_active=True)
            .order_by("-created_at")
        )
        category = self.request.query_params.get("category")
        if category:
            # WHY validate here: silently returning 0 results on a typo makes
            # client-side bugs invisible. 400 + clear message surfaces the mistake.
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
    """GET /community/announcements/{pk}/ — fetch a single announcement by ID.

    WHY RetrieveAPIView not a combined ListRetrieveAPIView:
        Separation of concerns — list has pagination + category filter, detail has
        neither. A combined view would require branching on pk presence, violating
        single-responsibility and complicating the pagination_class override.

    Scoped: ComplexScopedManager ensures residents only see their complex's
    announcements. A resident cannot enumerate a different complex's IDs because
    the queryset is already filtered to their complex before the pk lookup.
    """

    permission_classes = _AUTH
    serializer_class = AnnouncementSerializer

    def get_queryset(self) -> models.QuerySet[Announcement]:
        return Announcement.objects.select_related("created_by").filter(is_active=True)


class AnnouncementMarkReadView(APIView):
    """POST /community/announcements/{pk}/mark-read/ — idempotent read receipt.

    WHY APIView not CreateAPIView:
        CreateAPIView adds a serializer requirement. Mark-read has no request
        body — it is a pure state-transition action (verb endpoint per REST
        level-2). APIView gives clean control over the response status code.

    WHY HTTP 204 not 200/201:
        RFC 9110 — 204 No Content is the canonical response for a mutation that
        succeeds but has nothing meaningful to return. The client only needs
        confirmation of success, not a response body.

    WHY AnnouncementService.mark_read() not inline get_or_create:
        ADR-010 mandates that all ORM writes live in the service layer, not views.
        The previous implementation called get_or_create() directly in the view.
        Moving it to the service makes the logic independently testable without
        an HTTP client. Source: audit §Service Layer §ADR-010 violation.

    Source: api-contract.md §8; ADR-010 service-layer decision.
    """

    permission_classes = _AUTH

    def post(self, request: Request, pk: str) -> Response:
        announcement = get_object_or_404(
            Announcement.objects.filter(is_active=True),
            pk=pk,
        )
        # WHY cast: IsAuthenticated guarantees request.user is our User model.
        resident = cast(User, request.user)
        AnnouncementService.mark_read(announcement=announcement, user=resident)
        return Response(status=status.HTTP_204_NO_CONTENT)
