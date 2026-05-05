"""
config/celery.py — Celery application instance

WHY this file exists:
  Django configures Celery via CELERY_* settings (base.py).
  The 'celery -A config' CLI resolves to this module's `app` attribute
  via config/__init__.py (which imports it here).
  Standard Django+Celery pattern — source: docs.celeryq.dev/en/stable/
  django/first-steps-with-django.html
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

app = Celery("yali")

# WHY namespace="CELERY":
#   All CELERY_* keys in Django settings are automatically used as celery config.
#   No need to manually pass broker URL, timezone, etc.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Auto-discover tasks from all INSTALLED_APPS (apps/*/tasks.py)
app.autodiscover_tasks()


@app.on_after_finalize.connect
def _setup_task_failure_handler(sender: object, **kwargs: object) -> None:
    """Register the task_failure signal after all tasks are discovered.

    WHY on_after_finalize (not module-level @task_failure.connect):
      At module import time, Django's apps registry is not fully loaded.
      Importing apps.core.models at module level causes an AppRegistryNotReady
      error. on_after_finalize fires after app.autodiscover_tasks() completes,
      guaranteeing the Django ORM is ready before we register the handler.
    """
    from celery.signals import task_failure

    def _on_task_failure(
        sender: object,
        task_id: str,
        exception: Exception,
        args: list[object],
        kwargs: dict[str, object],
        traceback: object,
        einfo: object,
        **kw: object,
    ) -> None:
        """Write exhausted tasks to FailedTask (application-level DLQ).

        WHY only on terminal failure (retries >= max_retries):
          task_failure fires on EVERY failure including transient retries.
          Writing a DLQ record on every retry would flood the table with noise.
          We only write when the task is at its final retry — the point where
          Celery would otherwise silently discard it.

        WHY broad except (not narrow):
          still captures the original task exception independently.
        """
        import traceback as tb

        import django
        from django.apps import apps

        # Ensure Django is set up (worker process may import before Django init)
        if not apps.ready:
            django.setup()

        task = getattr(sender, "request", None)
        max_retries = getattr(sender, "max_retries", 0) or 0
        retry_count = getattr(task, "retries", 0) if task else 0

        # Only write to DLQ on terminal failure (not intermediate retries).
        if retry_count < max_retries:
            return

        try:
            from apps.core.models import FailedTask

            FailedTask.objects.create(
                task_name=getattr(sender, "name", str(sender)),
                task_args=list(args),
                task_kwargs=dict(kwargs),
                exception_class=type(exception).__name__,
                traceback=str(einfo) if einfo else tb.format_exc(),
                retries=retry_count,
            )
        except Exception:
            # WHY broad except:
            #   DLQ write must never crash the signal handler — Sentry independently
            #   captures the original task exception. Log for observability only.
            import structlog

            structlog.get_logger(__name__).error(
                "failed_task_dlq_write_error",
                task_name=getattr(sender, "name", "unknown"),
                exc=str(exception),
            )

    task_failure.connect(_on_task_failure, weak=False)
