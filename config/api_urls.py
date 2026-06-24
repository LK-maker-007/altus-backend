from __future__ import annotations

from django.urls import include, path

from apps.core.health import HealthCheckView

urlpatterns = [
    path("auth/", include("apps.users.urls")),
    path("facilities/", include("apps.facilities.urls")),
    path("bookings/", include("apps.bookings.urls")),
    path("visitors/", include("apps.visitors.urls")),
    path("packages/", include("apps.packages.urls")),
    path("maintenance/", include("apps.maintenance.urls")),
    path("community/", include("apps.community.urls")),
    path("emergency/", include("apps.emergency.urls")),
    path("lost-found/", include("apps.lost_found.urls")),
    path("security/", include("apps.security.urls")),
    path("dashboard/", include("apps.dashboard.urls")),
    path("health/", HealthCheckView.as_view(), name="health-check"),
]
