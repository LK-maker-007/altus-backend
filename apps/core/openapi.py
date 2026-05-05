"""
apps/core/openapi.py

drf-spectacular OpenAPI extensions for Altus-specific classes.

WHY this file exists:
  drf-spectacular emits W001 when it encounters an authentication class it cannot
  resolve to an OpenAPI securityScheme. MiddlewareJWTAuthentication is our custom
  class — spectacular has no built-in knowledge of it.

  The fix is an OpenApiAuthenticationExtension subclass. Spectacular auto-discovers
  these by scanning Python modules that have already been imported when schema
  generation or system checks run. This module is imported in CoreConfig.ready()
  (apps/core/__init__.py) which guarantees discovery before any check runs.

  Source: drf-spectacular docs §"Custom Authentication" →
          github.com/tfranzel/drf-spectacular/blob/master/docs/customization.rst
          #declare-an-authentication-class-which-is-unknown-to-drf-spectacular
"""

from __future__ import annotations

from typing import Any

from drf_spectacular.extensions import OpenApiAuthenticationExtension


class MiddlewareJWTAuthenticationScheme(OpenApiAuthenticationExtension):  # type: ignore[no-untyped-call]
    """Tells drf-spectacular how to represent MiddlewareJWTAuthentication in OpenAPI.

    WHY target_class as string (not a direct import):
      spectacular resolves the string lazily at schema-generation time, avoiding a
      circular-import chain (openapi.py → authentication.py → jwt_auth.py → …).
      This is the documented approach for all custom auth extensions.
      Source: drf-spectacular source §OpenApiAuthenticationExtension.

    WHY name = "BearerAuth":
      The name becomes the key in OpenAPI's components.securitySchemes and in every
      per-operation security requirement object. "BearerAuth" is the conventional
      name used by the OpenAPI spec examples and all major API tooling (Swagger,
      Redoc, Postman). Clients consuming the schema will see it in the Authorize
      dialog of Swagger UI.
    """

    target_class = "apps.core.authentication.MiddlewareJWTAuthentication"
    name = "BearerAuth"

    def get_security_definition(self, auto_schema: Any) -> dict[str, str]:
        """Return the OpenAPI 3.0 securityScheme definition for Bearer JWT.

        The returned dict maps directly to the OpenAPI spec:

          components:
            securitySchemes:
              BearerAuth:
                type: http
                scheme: bearer
                bearerFormat: JWT
                description: ...

        Source: OpenAPI 3.0 spec §4.8.27 "Security Scheme Object".
        """
        return {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": (
                "JWT access token issued by POST /api/v1/auth/login/. "
                "Lifetime: 15 minutes (configurable via "
                "JWT_ACCESS_TOKEN_LIFETIME_MINUTES). "
                "Rotate with POST /api/v1/auth/token/refresh/."
            ),
        }

    def get_security_requirement(self, auto_schema: Any) -> dict[str, list[Any]]:
        """Return the per-operation security requirement referencing BearerAuth.

        Returns {"BearerAuth": []} — the empty list means no OAuth scopes are
        required (we use custom RBAC permissions, not OAuth scopes).
        """
        return {self.name: []}
