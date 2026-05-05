from __future__ import annotations

from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.UUIDField"
    name = "apps.core"

    def ready(self) -> None:
        # WHY import openapi here:
        #   drf-spectacular discovers OpenApiAuthenticationExtension subclasses
        #   by scanning already-imported modules. If apps/core/openapi.py is never
        #   imported, MiddlewareJWTAuthenticationScheme is never registered and
        #   spectacular still emits W001 during manage.py check --deploy.
        #   ready() is the canonical Django hook for post-app-load initialisation.
        #   Source: drf-spectacular docs §"Custom Authentication" extensions;
        #           Django docs §AppConfig.ready().
        import apps.core.openapi  # noqa: F401
