from __future__ import annotations

import uuid
from typing import Any

import pytest

from apps.community.models import AnnouncementCategory
from apps.community.tasks import send_announcement_push
from apps.users.models import UserRole
from tests.factories.announcement_factory import AnnouncementFactory
from tests.factories.user_factory import UserFactory

_PATCH_TARGET = "apps.notifications.helpers.expo_push_send_batch"


@pytest.mark.django_db
class TestSendAnnouncementPushTask:

    def test_announcement_not_found_exits_silently(
        self, complex_a: Any, mocker: Any
    ) -> None:
        mock_batch = mocker.patch(_PATCH_TARGET)

        send_announcement_push(
            announcement_id=str(uuid.uuid4()),
            complex_id=str(complex_a.id),
        )

        mock_batch.assert_not_called()

    def test_wrong_complex_id_exits_silently(
        self, complex_a: Any, complex_b: Any, mocker: Any
    ) -> None:
        mock_batch = mocker.patch(_PATCH_TARGET)

        admin = UserFactory(complex=complex_a, phone_number="+919200011100")
        announcement = AnnouncementFactory(complex=complex_a, created_by=admin)

        send_announcement_push(
            announcement_id=str(announcement.id),
            complex_id=str(complex_b.id),
        )

        mock_batch.assert_not_called()

    def test_no_residents_no_push_sent(self, complex_a: Any, mocker: Any) -> None:
        mock_batch = mocker.patch(_PATCH_TARGET)

        admin = UserFactory(
            complex=complex_a,
            role=UserRole.COMPLEX_ADMIN,
            phone_number="+919200011101",
        )
        announcement = AnnouncementFactory(complex=complex_a, created_by=admin)

        send_announcement_push(
            announcement_id=str(announcement.id),
            complex_id=str(announcement.complex_id),
        )

        mock_batch.assert_called_once_with([])

    def test_push_sent_to_single_resident_with_token(
        self, complex_a: Any, unit_a: Any, mocker: Any
    ) -> None:
        mock_batch = mocker.patch(_PATCH_TARGET)

        admin = UserFactory(
            complex=complex_a,
            role=UserRole.COMPLEX_ADMIN,
            phone_number="+919200011102",
        )
        _resident = UserFactory(
            complex=complex_a,
            role=UserRole.RESIDENT,
            phone_number="+919200011103",
            expo_push_token="ExponentPushToken[community-single-test]",
            is_active=True,
        )
        announcement = AnnouncementFactory(
            complex=complex_a,
            created_by=admin,
            title="Pool maintenance scheduled",
            body="The pool will be closed tomorrow for cleaning.",
            category=AnnouncementCategory.GENERAL,
        )

        send_announcement_push(
            announcement_id=str(announcement.id),
            complex_id=str(announcement.complex_id),
        )

        mock_batch.assert_called_once()
        messages = mock_batch.call_args[0][0]
        assert len(messages) == 1
        msg = messages[0]
        assert msg["to"] == "ExponentPushToken[community-single-test]"
        assert msg["title"] == "Pool maintenance scheduled"
        assert msg["body"] == "The pool will be closed tomorrow for cleaning."
        assert msg["data"]["announcement_id"] == str(announcement.id)
        assert msg["data"]["category"] == AnnouncementCategory.GENERAL
        assert msg["sound"] == "default"

    def test_push_sent_to_all_residents(self, complex_a: Any, mocker: Any) -> None:
        mock_batch = mocker.patch(_PATCH_TARGET)

        admin = UserFactory(
            complex=complex_a,
            role=UserRole.COMPLEX_ADMIN,
            phone_number="+919200011140",
        )
        tokens = [
            "ExponentPushToken[community-multi-1]",
            "ExponentPushToken[community-multi-2]",
            "ExponentPushToken[community-multi-3]",
        ]
        for i, token in enumerate(tokens, start=1):
            UserFactory(
                complex=complex_a,
                role=UserRole.RESIDENT,
                phone_number=f"+91920001114{i}",
                expo_push_token=token,
                is_active=True,
            )
        announcement = AnnouncementFactory(
            complex=complex_a,
            created_by=admin,
            title="Community event this weekend",
        )

        send_announcement_push(
            announcement_id=str(announcement.id),
            complex_id=str(announcement.complex_id),
        )

        mock_batch.assert_called_once()
        messages = mock_batch.call_args[0][0]
        assert len(messages) == len(tokens)
        called_tokens = {m["to"] for m in messages}
        assert called_tokens == set(tokens)

    def test_residents_without_token_skipped(self, complex_a: Any, mocker: Any) -> None:
        mock_batch = mocker.patch(_PATCH_TARGET)

        admin = UserFactory(
            complex=complex_a,
            role=UserRole.COMPLEX_ADMIN,
            phone_number="+919200011114",
        )
        UserFactory(
            complex=complex_a,
            role=UserRole.RESIDENT,
            phone_number="+919200011115",
            expo_push_token="",
            is_active=True,
        )
        UserFactory(
            complex=complex_a,
            role=UserRole.RESIDENT,
            phone_number="+919200011116",
            expo_push_token="ExponentPushToken[community-token-filter-test]",
            is_active=True,
        )
        announcement = AnnouncementFactory(
            complex=complex_a,
            created_by=admin,
            title="Water supply interruption",
        )

        send_announcement_push(
            announcement_id=str(announcement.id),
            complex_id=str(announcement.complex_id),
        )

        mock_batch.assert_called_once()
        messages = mock_batch.call_args[0][0]
        assert len(messages) == 1
        assert messages[0]["to"] == "ExponentPushToken[community-token-filter-test]"

    def test_inactive_residents_skipped(self, complex_a: Any, mocker: Any) -> None:
        mock_batch = mocker.patch(_PATCH_TARGET)

        admin = UserFactory(
            complex=complex_a,
            role=UserRole.COMPLEX_ADMIN,
            phone_number="+919200011117",
        )
        UserFactory(
            complex=complex_a,
            role=UserRole.RESIDENT,
            phone_number="+919200011118",
            expo_push_token="ExponentPushToken[community-inactive-test]",
            is_active=False,
        )
        announcement = AnnouncementFactory(
            complex=complex_a,
            created_by=admin,
            title="Test",
        )

        send_announcement_push(
            announcement_id=str(announcement.id),
            complex_id=str(announcement.complex_id),
        )

        mock_batch.assert_called_once_with([])

    def test_cross_complex_residents_not_notified(
        self, complex_a: Any, complex_b: Any, mocker: Any
    ) -> None:
        mock_batch = mocker.patch(_PATCH_TARGET)

        admin_a = UserFactory(
            complex=complex_a,
            role=UserRole.COMPLEX_ADMIN,
            phone_number="+919200011119",
        )
        UserFactory(
            complex=complex_b,
            role=UserRole.RESIDENT,
            phone_number="+919200011120",
            expo_push_token="ExponentPushToken[community-cross-tenant-test]",
            is_active=True,
        )
        announcement = AnnouncementFactory(
            complex=complex_a,
            created_by=admin_a,
            title="Complex A notice",
        )

        send_announcement_push(
            announcement_id=str(announcement.id),
            complex_id=str(announcement.complex_id),
        )

        mock_batch.assert_called_once_with([])

    def test_power_outage_category_uses_no_special_branching(
        self, complex_a: Any, mocker: Any
    ) -> None:
        mock_batch = mocker.patch(_PATCH_TARGET)

        admin = UserFactory(
            complex=complex_a,
            role=UserRole.COMPLEX_ADMIN,
            phone_number="+919200011121",
        )
        UserFactory(
            complex=complex_a,
            role=UserRole.RESIDENT,
            phone_number="+919200011122",
            expo_push_token="ExponentPushToken[community-power-outage-test]",
            is_active=True,
        )
        announcement = AnnouncementFactory(
            complex=complex_a,
            created_by=admin,
            title="Power Outage Tonight",
            body="Scheduled power outage from 10PM to 2AM.",
            category=AnnouncementCategory.POWER_OUTAGE,
        )

        send_announcement_push(
            announcement_id=str(announcement.id),
            complex_id=str(announcement.complex_id),
        )

        mock_batch.assert_called_once()
        messages = mock_batch.call_args[0][0]
        assert len(messages) == 1
        assert messages[0]["data"]["category"] == AnnouncementCategory.POWER_OUTAGE

    def test_body_truncated_at_100_chars(self, complex_a: Any, mocker: Any) -> None:
        mock_batch = mocker.patch(_PATCH_TARGET)

        admin = UserFactory(
            complex=complex_a,
            role=UserRole.COMPLEX_ADMIN,
            phone_number="+919200011123",
        )
        UserFactory(
            complex=complex_a,
            role=UserRole.RESIDENT,
            phone_number="+919200011124",
            expo_push_token="ExponentPushToken[community-body-truncate-test]",
            is_active=True,
        )
        long_body = "X" * 150
        announcement = AnnouncementFactory(
            complex=complex_a,
            created_by=admin,
            title="Test title",
            body=long_body,
        )

        send_announcement_push(
            announcement_id=str(announcement.id),
            complex_id=str(announcement.complex_id),
        )

        messages = mock_batch.call_args[0][0]
        assert messages[0]["body"] == "X" * 100

    def test_task_is_idempotent(self, complex_a: Any, mocker: Any) -> None:
        mock_batch = mocker.patch(_PATCH_TARGET)

        admin = UserFactory(
            complex=complex_a,
            role=UserRole.COMPLEX_ADMIN,
            phone_number="+919200011125",
        )
        UserFactory(
            complex=complex_a,
            role=UserRole.RESIDENT,
            phone_number="+919200011126",
            expo_push_token="ExponentPushToken[community-idempotent-test]",
            is_active=True,
        )
        announcement = AnnouncementFactory(
            complex=complex_a,
            created_by=admin,
            title="Idempotency test",
        )

        send_announcement_push(
            announcement_id=str(announcement.id),
            complex_id=str(announcement.complex_id),
        )
        send_announcement_push(
            announcement_id=str(announcement.id),
            complex_id=str(announcement.complex_id),
        )

        assert mock_batch.call_count == 2
