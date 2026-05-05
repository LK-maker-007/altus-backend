from __future__ import annotations

from django.urls import path

from apps.community import views

urlpatterns = [
    path(
        "announcements/",
        views.AnnouncementListView.as_view(),
        name="announcement-list",
    ),
    path(
        "announcements/<uuid:pk>/",
        views.AnnouncementRetrieveView.as_view(),
        name="announcement-detail",
    ),
    path(
        "announcements/<uuid:pk>/mark-read/",
        views.AnnouncementMarkReadView.as_view(),
        name="announcement-mark-read",
    ),
]
