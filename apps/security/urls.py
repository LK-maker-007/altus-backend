from __future__ import annotations

from django.urls import include, path

urlpatterns = [
    path("visitors/", include("apps.visitors.urls")),
    path("packages/", include("apps.packages.urls")),
]
