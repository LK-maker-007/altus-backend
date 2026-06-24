import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

app = Celery("yali")

app.config_from_object("django.conf:settings", namespace="CELERY")

app.autodiscover_tasks()


@app.on_after_finalize.connect
def _setup_task_failure_handler(sender: object, **kwargs: object) -> None:
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
        import traceback as tb

        import django
        from django.apps import apps

        if not apps.ready:
            django.setup()

        task = getattr(sender, "request", None)
        max_retries = getattr(sender, "max_retries", 0) or 0
        retry_count = getattr(task, "retries", 0) if task else 0

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
            import structlog

            structlog.get_logger(__name__).error(
                "failed_task_dlq_write_error",
                task_name=getattr(sender, "name", "unknown"),
                exc=str(exception),
            )

    task_failure.connect(_on_task_failure, weak=False)
