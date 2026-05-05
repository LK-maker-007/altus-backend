"""
apps/community/services.py

AnnouncementService — business logic for community announcements.

WHY a service layer for the mark-read action:
  ADR-010 mandates that all business logic (including ORM writes) lives in the
  service layer, not views. The previous implementation called
  AnnouncementRead.objects.get_or_create() directly in AnnouncementMarkReadView.
  Moving this to a service:
    - Makes the mark-read logic independently unit-testable without HTTP.
    - Provides a reusable entry point for future callers (admin commands, etc.).
    - Matches the pattern of every other app in the codebase.
    - Resolves the ADR-010 violation flagged in the architectural audit.
  Source: audit §Service Layer §AnnouncementMarkReadView ADR-010 violation;
          HackSoftware Django Styleguide §Services.
"""

from __future__ import annotations

import structlog

from apps.community.models import Announcement, AnnouncementRead
from apps.users.models import User

logger = structlog.get_logger(__name__)


class AnnouncementService:
    """Business logic for community announcement operations.

    All methods are stateless @staticmethod — class is a namespace (ADR-010).
    """

    @staticmethod
    def mark_read(*, announcement: Announcement, user: User) -> bool:
        """Record that a user has read an announcement. Idempotent.

        Args:
            announcement: The Announcement instance to mark as read.
            user:         The User who read the announcement.

        Returns:
            True if a new read record was created, False if it already existed.

        WHY get_or_create not create:
            Idempotent by contract — tapping "Mark as Read" twice must not 404 or
            raise IntegrityError. get_or_create maps to the DB-level UniqueConstraint
            on (announcement, user), making this safe for retry-on-failure clients.

        WHY bool return (not the object):
            Views only need to know whether this was a new read (201 Created) or
            a no-op (204 No Content is standard practice). Returning the bool lets
            the view make that distinction without coupling to the ORM object.
            For now both cases return 204, but the return value enables future
            differentiation without changing the service signature.
        """
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
