from __future__ import annotations

"""
Layer 2 dispatch tests — apps/community/admin.py AnnouncementAdmin.save_model()

Verifies that saving a NEW active Announcement via the admin dispatches
send_announcement_push via transaction.on_commit(), and that editing an
existing announcement does NOT re-dispatch.

Pattern (research-rule.md §10 / Django 6.0 official / Celery 5.6.3):
  django_capture_on_commit_callbacks(execute=True) + mock .apply_async()

Admin save_model() is called by the Django admin machinery. We call it
directly with a minimal mock HttpRequest — this is the correct pattern for
testing admin save_model without spinning up a full HTTP stack.
"""

from typing import Any
from unittest.mock import MagicMock

import pytest

from apps.community.admin import AnnouncementAdmin
from apps.community.models import Announcement, AnnouncementCategory


@pytest.mark.django_db
class TestCommunityAdminDispatch:
    """
    Layer 2 — dispatch tests for AnnouncementAdmin.save_model().

    Conditions tested:
    - NEW active announcement → task dispatched ✅
    - Edit (change=True) → task NOT dispatched ✅
    - NEW but is_active=False → task NOT dispatched ✅
    """

    def _make_request(self, admin_user: Any) -> Any:
        """Minimal HttpRequest with an authenticated user (simulates admin staff)."""
        from django.test import RequestFactory

        rf = RequestFactory()
        request = rf.post("/admin/community/announcement/add/")
        request.user = admin_user
        return request

    def _get_admin(self) -> AnnouncementAdmin:
        """Instantiate AnnouncementAdmin bound to the default admin site."""
        from django.contrib.admin.sites import AdminSite

        return AnnouncementAdmin(Announcement, AdminSite())

    def test_new_active_announcement_dispatches_task(
        self,
        complex_a: Any,
        admin_user: Any,
        django_capture_on_commit_callbacks: Any,
        mocker: Any,
    ) -> None:
        """
        Creating a NEW active Announcement must enqueue send_announcement_push
        with args=(str(obj.id), str(obj.complex_id),) after the commit.
        """
        mock_push = mocker.patch(
            "apps.community.tasks.send_announcement_push.apply_async"
        )

        obj = Announcement(
            complex=complex_a,
            created_by=admin_user,
            title="Pool closure notice",
            body="Pool will be closed for maintenance on Saturday.",
            category=AnnouncementCategory.GENERAL,
            is_active=True,
        )

        request = self._make_request(admin_user)
        admin = self._get_admin()
        form = MagicMock()

        with django_capture_on_commit_callbacks(execute=True):
            admin.save_model(request, obj, form, change=False)  # NEW → change=False

        mock_push.assert_called_once_with(
            args=(
                str(obj.id),
                str(obj.complex_id),
            ),
        )

    def test_edit_announcement_does_not_dispatch_task(
        self,
        complex_a: Any,
        admin_user: Any,
        django_capture_on_commit_callbacks: Any,
        mocker: Any,
    ) -> None:
        """
        Editing an EXISTING Announcement (change=True) must NOT dispatch.
        This prevents duplicate push notifications when an admin corrects a typo.
        """
        mock_push = mocker.patch(
            "apps.community.tasks.send_announcement_push.apply_async"
        )

        from tests.factories.announcement_factory import AnnouncementFactory

        obj = AnnouncementFactory(
            complex=complex_a, created_by=admin_user, is_active=True
        )

        request = self._make_request(admin_user)
        admin = self._get_admin()
        form = MagicMock()

        with django_capture_on_commit_callbacks(execute=True):
            admin.save_model(request, obj, form, change=True)  # EDIT → change=True

        mock_push.assert_not_called()

    def test_new_inactive_announcement_does_not_dispatch_task(
        self,
        complex_a: Any,
        admin_user: Any,
        django_capture_on_commit_callbacks: Any,
        mocker: Any,
    ) -> None:
        """
        Creating a NEW Announcement with is_active=False (draft) must NOT dispatch.
        Drafts are not yet visible to residents and must not trigger push.
        """
        mock_push = mocker.patch(
            "apps.community.tasks.send_announcement_push.apply_async"
        )

        obj = Announcement(
            complex=complex_a,
            created_by=admin_user,
            title="Draft announcement",
            body="Not published yet.",
            category=AnnouncementCategory.GENERAL,
            is_active=False,  # draft
        )

        request = self._make_request(admin_user)
        admin = self._get_admin()
        form = MagicMock()

        with django_capture_on_commit_callbacks(execute=True):
            admin.save_model(request, obj, form, change=False)

        mock_push.assert_not_called()
