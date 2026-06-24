from __future__ import annotations

from django.urls import path

from apps.visitors import views

urlpatterns = [
    path(
        "",
        views.VisitorListCreateView.as_view(),
        name="visitor-list-create",
    ),
    path(
        "verify/",
        views.VisitorVerifyView.as_view(),
        name="visitor-verify",
    ),
    path(
        "<uuid:visitor_id>/arrive/",
        views.VisitorArriveView.as_view(),
        name="visitor-arrive",
    ),
]
