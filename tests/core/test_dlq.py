from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from apps.core.models import FailedTask


@pytest.mark.django_db
class TestFailedTaskModel:

    def test_create_with_required_fields(self) -> None:
        task = FailedTask.objects.create(
            task_name="apps.bookings.tasks.expire_stale_holds",
            task_args=["arg1", "arg2"],
            task_kwargs={"key": "value"},
            exception_class="ValueError",
            traceback="Traceback (most recent call last):\n  File ...",
            retries=3,
        )
        assert task.pk is not None
        assert task.resolved is False
        assert task.task_name == "apps.bookings.tasks.expire_stale_holds"
        assert task.task_args == ["arg1", "arg2"]
        assert task.task_kwargs == {"key": "value"}
        assert task.exception_class == "ValueError"
        assert task.retries == 3

    def test_resolved_defaults_false(self) -> None:
        task = FailedTask.objects.create(
            task_name="apps.visitors.tasks.expire_stale_visitors",
        )
        assert task.resolved is False

    def test_mark_resolved(self) -> None:
        task = FailedTask.objects.create(
            task_name="apps.notifications.tasks.check_push_receipts",
            exception_class="ConnectionError",
        )
        assert task.resolved is False

        task.resolved = True
        task.save(update_fields=["resolved"])

        task.refresh_from_db()
        assert task.resolved is True

    def test_unresolved_filter_for_alerting(self) -> None:
        FailedTask.objects.create(
            task_name="apps.visitors.tasks.expire_stale_visitors",
            exception_class="ConnectionError",
        )
        FailedTask.objects.create(
            task_name="apps.visitors.tasks.expire_stale_visitors",
            exception_class="ConnectionError",
            resolved=True,
        )

        unresolved = FailedTask.objects.filter(resolved=False)
        assert unresolved.count() >= 1, (
            "Unresolved FailedTask query returned 0 rows. "
            "Monitoring alerts relying on this filter would never fire."
        )

    def test_str_representation(self) -> None:
        task = FailedTask.objects.create(
            task_name="apps.bookings.tasks.send_reminder",
            retries=3,
        )
        assert "FAILED" in str(task)
        assert "apps.bookings.tasks.send_reminder" in str(task)


@pytest.mark.django_db
class TestDLQSignalHandler:

    def test_terminal_failure_writes_to_dlq(self) -> None:
        from celery.signals import task_failure

        from config.celery import _setup_task_failure_handler

        _setup_task_failure_handler(sender=None)

        class _TerminalSender:

            name = "apps.notifications.tasks.check_push_receipts"
            max_retries = 3
            request = MagicMock(retries=3)

        exc = ValueError("Expo API returned unexpected format")

        task_failure.send(
            sender=_TerminalSender(),
            task_id="terminal-test-uuid",
            exception=exc,
            args=["batch_idx_0"],
            kwargs={"complex_id": "test-complex"},
            traceback=None,
            einfo=None,
        )

        row = FailedTask.objects.filter(
            task_name="apps.notifications.tasks.check_push_receipts",
        ).first()
        assert row is not None, (
            "FailedTask row was NOT written by the task_failure signal handler. "
            "Terminal task failures are being silently discarded."
        )
        assert row.exception_class == "ValueError"
        assert row.retries == 3

    def test_intermediate_retry_does_not_write_to_dlq(self) -> None:
        from celery.signals import task_failure

        class _RetryingSender:

            name = "apps.bookings.tasks.expire_stale_holds"
            max_retries = 3
            request = MagicMock(retries=1)

        before_count = FailedTask.objects.count()

        task_failure.send(
            sender=_RetryingSender(),
            task_id="retry-test-uuid",
            exception=ValueError("transient error"),
            args=[],
            kwargs={},
            traceback=None,
            einfo=None,
        )

        after_count = FailedTask.objects.count()
        assert after_count == before_count, (
            "FailedTask was written for an intermediate retry. "
            "The DLQ should only record terminal (exhausted) failures, "
            "not transient retries — this would flood the triage queue with noise."
        )
