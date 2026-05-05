from __future__ import annotations

"""
Community task unit tests — US-033 / US-040 (send_announcement_push).

Tasks are called directly — not via .delay().
Source: Celery 5.x official docs — preferred method is direct call + mock for unit tests.
        TASK_ALWAYS_EAGER is explicitly not recommended for unit tests.

WHY mock target changed to expo_push_send_batch (audit §Significant §Expo Push):
  send_announcement_push was refactored to call expo_push_send_batch() instead of
  calling expo_push_send() once per resident. A 500-resident complex fan-out went
  from 500 sequential HTTP requests to ceil(500/100)=5 batched requests.
  Tests now assert on the batch payload (list[PushMessage]) rather than per-call
  kwargs, preserving all behavioural guarantees with the new calling convention.

Patch target: "apps.notifications.helpers.expo_push_send_batch"
  Canonical definition location — task resolves via deferred import.

Key behaviour under test (from task docstring):
- Fan-out to ALL active residents with a push token in the given complex.
- Idempotent: exits silently if announcement or complex not found.
- Power-outage vs general — NO branching in the task; mobile client handles
  visual treatment from the `category` field in the data payload.
- Cross-tenant safety: announcement.id + complex_id filter prevents cross-complex leak.
"""

import uuid
from typing import Any

import pytest

from apps.community.models import AnnouncementCategory
from apps.community.tasks import send_announcement_push
from apps.users.models import UserRole
from tests.factories.announcement_factory import AnnouncementFactory
from tests.factories.user_factory import UserFactory

# ── send_announcement_push ─────────────────────────────────────────────────────

_PATCH_TARGET = "apps.notifications.helpers.expo_push_send_batch"


@pytest.mark.django_db
class TestSendAnnouncementPushTask:
    """
    Tests for send_announcement_push — fan-out push notification to all residents
    when a new announcement is posted (US-033 / US-040).
    """

    def test_announcement_not_found_exits_silently(
        self, complex_a: Any, mocker: Any
    ) -> None:
        """
        Announcement deleted between task dispatch and execution.
        Task must exit silently — idempotency guarantee.
        """
        mock_batch = mocker.patch(_PATCH_TARGET)

        send_announcement_push(
            announcement_id=str(uuid.uuid4()),  # non-existent
            complex_id=str(complex_a.id),
        )

        mock_batch.assert_not_called()

    def test_wrong_complex_id_exits_silently(
        self, complex_a: Any, complex_b: Any, mocker: Any
    ) -> None:
        """
        Task called with wrong complex_id — cross-tenant filter must prevent
        fan-out for an announcement belonging to another complex.
        Announcement.unscoped.get(id=..., complex_id=complex_b.id) → DoesNotExist.
        """
        mock_batch = mocker.patch(_PATCH_TARGET)

        admin = UserFactory(complex=complex_a, phone_number="+919200011100")
        announcement = AnnouncementFactory(complex=complex_a, created_by=admin)

        send_announcement_push(
            announcement_id=str(announcement.id),
            complex_id=str(complex_b.id),  # wrong — DoesNotExist
        )

        mock_batch.assert_not_called()

    def test_no_residents_no_push_sent(self, complex_a: Any, mocker: Any) -> None:
        """
        Complex has no active residents with push tokens.
        expo_push_send_batch must be called with an empty list — it exits early.
        WHY still called (not assert_not_called): the task always calls batch;
        the helper guards len(messages)==0 internally.
        """
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

        # Batch called with empty list; helper returns early on []
        mock_batch.assert_called_once_with([])

    def test_push_sent_to_single_resident_with_token(
        self, complex_a: Any, unit_a: Any, mocker: Any
    ) -> None:
        """
        Happy path — one active resident with a push token.
        expo_push_send_batch must be called once with a list containing exactly
        one PushMessage dict with the correct payload.
        """
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
        messages = mock_batch.call_args[0][
            0
        ]  # first positional arg = list[PushMessage]
        assert len(messages) == 1
        msg = messages[0]
        assert msg["to"] == "ExponentPushToken[community-single-test]"
        assert msg["title"] == "Pool maintenance scheduled"
        assert msg["body"] == "The pool will be closed tomorrow for cleaning."
        assert msg["data"]["announcement_id"] == str(announcement.id)
        assert msg["data"]["category"] == AnnouncementCategory.GENERAL
        assert msg["sound"] == "default"

    def test_push_sent_to_all_residents(self, complex_a: Any, mocker: Any) -> None:
        """
        Multiple active residents — all must receive a push.
        WHY single batch call (not N calls): expo_push_send_batch accumulates all
        messages and sends them in one (or more) HTTP requests, not one per resident.
        The batch payload must include exactly one entry per eligible resident.
        """
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
        """
        Two residents: one with token, one without.
        Only the resident with a token should appear in the batch payload.
        The filter uses expo_push_token__gt="" to exclude empty tokens.
        """
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
            expo_push_token="",  # no token — must be excluded
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
        """
        Inactive residents (is_active=False) must be excluded from the fan-out.
        The filter includes is_active=True — deactivated accounts get no push.
        Batch must be called with an empty list.
        """
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
            is_active=False,  # deactivated — must be excluded
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
        """
        Residents in complex_b must NOT receive pushes for complex_a announcements.
        The User.objects.filter(complex_id=complex_id, ...) tenant filter enforces this.
        Batch must be called with an empty list (no eligible residents in complex_a).
        """
        mock_batch = mocker.patch(_PATCH_TARGET)

        admin_a = UserFactory(
            complex=complex_a,
            role=UserRole.COMPLEX_ADMIN,
            phone_number="+919200011119",
        )
        # Resident in complex_b — must be excluded
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
        """
        US-040 — power outage announcements use AnnouncementCategory.POWER_OUTAGE.
        The task does NOT branch on category — it sends the same push structure.
        The category value is passed in `data` for the mobile client to handle.
        This test verifies the data payload in the batch contains the correct category.
        """
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
        """
        Task truncates announcement.body to 100 chars in the push notification
        (announcement.body[:100]) — push notifications have limited display space.
        """
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
        long_body = "X" * 150  # 150 chars — truncated to 100 in push
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
        """
        Calling the task twice with the same args must not raise.
        Fan-out is re-executed on each call — no deduplication in the task itself.
        Each call produces one batch call.
        """
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
        send_announcement_push(  # second call — must not raise
            announcement_id=str(announcement.id),
            complex_id=str(announcement.complex_id),
        )

        assert mock_batch.call_count == 2  # one batch call per fan-out invocation
