from __future__ import annotations

from django.urls import path

from apps.maintenance import views

urlpatterns = [
    path("tickets/", views.TicketListCreateView.as_view(), name="ticket-list-create"),
    path(
        "tickets/<uuid:ticket_id>/",
        views.TicketDetailView.as_view(),
        name="ticket-detail",
    ),
]
