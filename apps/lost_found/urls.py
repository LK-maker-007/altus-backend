from __future__ import annotations

from django.urls import path

from apps.lost_found import views

urlpatterns = [
    path("", views.LostFoundListCreateView.as_view(), name="lost-found-list-create"),
]
