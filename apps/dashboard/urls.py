from __future__ import annotations

from django.urls import path

from apps.dashboard import views

urlpatterns = [
    path("", views.DashboardView.as_view(), name="dashboard"),
]
