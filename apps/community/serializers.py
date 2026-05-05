from __future__ import annotations

from typing import ClassVar

from rest_framework import serializers

from apps.community.models import Announcement


class AnnouncementSerializer(serializers.ModelSerializer[Announcement]):
    """Read serializer for the announcements list endpoint (api-contract §8)."""

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
            # Event-specific — null for non-EVENT announcements
            "event_date",
            "event_venue",
        ]
        read_only_fields: ClassVar[list[str]] = fields

    def get_posted_by(self, obj: Announcement) -> str:
        # WHY .name not .get_full_name(): User extends AbstractBaseUser, not
        # AbstractUser. AbstractBaseUser has no get_full_name() — only
        # AbstractUser does. Our User model has a single 'name' CharField.
        return obj.created_by.name or obj.created_by.phone_number


class AnnouncementDashboardSerializer(serializers.ModelSerializer[Announcement]):
    """Compact serializer for the dashboard aggregation endpoint (api-contract §11).

    Adds a `preview` field — first 120 characters of body text.
    """

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
