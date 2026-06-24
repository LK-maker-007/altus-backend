from __future__ import annotations

from typing import Any

from drf_spectacular.extensions import OpenApiAuthenticationExtension


class MiddlewareJWTAuthenticationScheme(OpenApiAuthenticationExtension):

    target_class = "apps.core.authentication.MiddlewareJWTAuthentication"
    name = "BearerAuth"

    def get_security_definition(self, auto_schema: Any) -> dict[str, str]:
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
        return {self.name: []}
