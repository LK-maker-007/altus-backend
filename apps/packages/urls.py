from __future__ import annotations

from django.urls import path

from apps.packages import views

urlpatterns = [
    # Resident endpoints
    path(
        "",
        views.PackageListView.as_view(),
        name="package-list",
    ),
    path(
        "<str:package_id>/collect/",
        views.PackageCollectView.as_view(),
        name="package-collect",
    ),
    # Security endpoint — mounted at security/packages/ in root urls.py
    path(
        "log/",
        views.PackageLogView.as_view(),
        name="package-log",
    ),
]
