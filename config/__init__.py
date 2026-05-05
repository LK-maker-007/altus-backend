# config/__init__.py
#
# WHY this import:
#   `celery -A config` resolves the Celery app by looking for a `celery` attribute
#   on the `config` module. Importing app here as `celery` exposes it correctly.
#   Source: docs.celeryq.dev/en/stable/django/first-steps-with-django.html
from .celery import app as celery_app

__all__ = ("celery_app",)
