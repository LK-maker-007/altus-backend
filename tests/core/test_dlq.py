"""
tests/test_core/test_dlq.py

Tests for the FailedTask Dead Letter Queue (DLQ) — the model and the
Celery task_failure signal handler in config/celery.py.

FailedTask model fields (from apps/core/models.py):
  - task_name        CharField(max_length=255)
  - task_args        JSONField(default=list)
  - task_kwargs      JSONField(default=dict)
  - exception_class  CharField(max_length=200, blank=True)
  - traceback        TextField(blank=True)
  - retries          PositiveSmallIntegerField(default=0)
  - resolved         BooleanField(default=False)
  - resolved_at      (inherited via TimestampedModel — only updated_at/created_at)

Signal handler logic (from config/celery.py _on_task_failure):
  - Only writes to DLQ when retry_count >= max_retries (terminal failure)
  - Intermediate retries are skipped (retry_count < max_retries → return early)
  - Fields set: task_name, task_args, task_kwargs, exception_class, traceback, retries
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from apps.core.models import FailedTask


@pytest.mark.django_db
class TestFailedTaskModel:
    """Tests for the FailedTask DLQ model fields and constraints."""

    def test_create_with_required_fields(self) -> None:
        """FailedTask can be created with the actual model fields."""
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
        """resolved=False is the default — new DLQ entries require operator triage."""
        task = FailedTask.objects.create(
            task_name="apps.visitors.tasks.expire_stale_visitors",
        )
        assert task.resolved is False

    def test_mark_resolved(self) -> None:
        """An operator can flip resolved=True to mark a DLQ entry as triaged."""
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
        """FailedTask.objects.filter(resolved=False) supports monitoring alerts.

        This query pattern is what a Sentry/PagerDuty alert would use to detect
        DLQ row count spikes. The index on (resolved, -created_at) makes it fast.
        """
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
        """__str__ returns a useful operator-facing label."""
        task = FailedTask.objects.create(
            task_name="apps.bookings.tasks.send_reminder",
            retries=3,
        )
        assert "FAILED" in str(task)
        assert "apps.bookings.tasks.send_reminder" in str(task)


@pytest.mark.django_db
class TestDLQSignalHandler:
    """Tests for the Celery task_failure signal handler in config/celery.py.

    WHY signal-based testing (not running a real failing task):
      CELERY_TASK_ALWAYS_EAGER runs tasks synchronously but does not replicate
      the Celery signal chain exactly. Sending task_failure directly with
      controlled parameters is cleaner, faster, and doesn't depend on a specific
      task implementation being broken in a controlled way.
    """

    def test_terminal_failure_writes_to_dlq(self) -> None:
        """Signal handler writes a FailedTask row when retries >= max_retries."""
        from celery.signals import task_failure

        class _TerminalSender:
            """Simulates a task that has exhausted all retries."""

            name = "apps.notifications.tasks.check_push_receipts"
            max_retries = 3
            # request.retries == max_retries → terminal failure condition
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
        """Signal handler skips DLQ write when retries < max_retries (not terminal)."""
        from celery.signals import task_failure

        class _RetryingSender:
            """Simulates a task on its first retry — NOT terminal."""

            name = "apps.bookings.tasks.expire_stale_holds"
            max_retries = 3
            # retries=1, max_retries=3 → intermediate retry → must NOT write DLQ
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
