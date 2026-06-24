from __future__ import annotations

from typing import ClassVar

from rest_framework import serializers

from apps.community.models import Announcement


class AnnouncementSerializer(serializers.ModelSerializer[Announcement]):

    posted_by = serializers.SerializerMethodField()

    class Meta:
        model = Announcement
        fields: ClassVar[list[str]] = [
            "id",
            "title",
            "body",
            "category",
            "posted_by",
            "created_at",
            "event_date",
            "event_venue",
        ]
        read_only_fields: ClassVar[list[str]] = fields

    def get_posted_by(self, obj: Announcement) -> str:
        return obj.created_by.name or "Management"


class AnnouncementDashboardSerializer(serializers.ModelSerializer[Announcement]):

    preview = serializers.SerializerMethodField()

    class Meta:
        model = Announcement
        fields: ClassVar[list[str]] = [
            "id",
            "title",
            "category",
            "created_at",
            "preview",
        ]
        read_only_fields: ClassVar[list[str]] = fields

    def get_preview(self, obj: Announcement) -> str:
        return obj.body[:120]
