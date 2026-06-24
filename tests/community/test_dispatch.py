from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from apps.community.admin import AnnouncementAdmin
from apps.community.models import Announcement, AnnouncementCategory


@pytest.mark.django_db
class TestCommunityAdminDispatch:

    def _make_request(self, admin_user: Any) -> Any:
        from django.test import RequestFactory

        rf = RequestFactory()
        request = rf.post("/admin/community/announcement/add/")
        request.user = admin_user
        return request

    def _get_admin(self) -> AnnouncementAdmin:
        from django.contrib.admin.sites import AdminSite

        return AnnouncementAdmin(Announcement, AdminSite())

    def test_new_active_announcement_dispatches_task(
        self,
        complex_a: Any,
        admin_user: Any,
        django_capture_on_commit_callbacks: Any,
        mocker: Any,
    ) -> None:
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
            admin.save_model(request, obj, form, change=False)

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
            admin.save_model(request, obj, form, change=True)

        mock_push.assert_not_called()

    def test_new_inactive_announcement_does_not_dispatch_task(
        self,
        complex_a: Any,
        admin_user: Any,
        django_capture_on_commit_callbacks: Any,
        mocker: Any,
    ) -> None:
        mock_push = mocker.patch(
            "apps.community.tasks.send_announcement_push.apply_async"
        )

        obj = Announcement(
            complex=complex_a,
            created_by=admin_user,
            title="Draft announcement",
            body="Not published yet.",
            category=AnnouncementCategory.GENERAL,
            is_active=False,
        )

        request = self._make_request(admin_user)
        admin = self._get_admin()
        form = MagicMock()

        with django_capture_on_commit_callbacks(execute=True):
            admin.save_model(request, obj, form, change=False)

        mock_push.assert_not_called()
