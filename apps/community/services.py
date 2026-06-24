from __future__ import annotations

import structlog

from apps.community.models import Announcement, AnnouncementRead
from apps.users.models import User

logger = structlog.get_logger(__name__)


class AnnouncementService:

    @staticmethod
    def mark_read(*, announcement: Announcement, user: User) -> bool:
        _, created = AnnouncementRead.objects.get_or_create(
            announcement=announcement,
            user=user,
        )
        logger.info(
            "announcement_marked_read",
            announcement_id=str(announcement.id),
            user_id=str(user.pk),
            created=created,
        )
        return created
