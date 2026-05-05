from __future__ import annotations

from django.urls import path

from apps.emergency import views

urlpatterns = [
    path("", views.EmergencyContactListView.as_view(), name="emergency-contact-list"),
]
