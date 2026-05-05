from __future__ import annotations

from django.urls import include, path

# Security staff URL namespace.
# Full paths under api/v1/security/ per api-contract:
#   POST  /security/visitors/verify/      — VisitorVerifyView
#   POST  /security/visitors/{id}/arrive/ — VisitorArriveView
#   POST  /security/packages/             — PackageLogView

urlpatterns = [
    path("visitors/", include("apps.visitors.urls")),
    path("packages/", include("apps.packages.urls")),
]
