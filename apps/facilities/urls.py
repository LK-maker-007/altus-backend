from __future__ import annotations

from django.urls import path

from apps.facilities.views import (
    FacilityDetailView,
    FacilityListView,
    FacilitySlotStreamView,
    FacilitySlotsView,
    SseTicketIssueView,
)

urlpatterns = [
    path("", FacilityListView.as_view(), name="list"),
    path("<uuid:facility_id>/", FacilityDetailView.as_view(), name="detail"),
    path("<uuid:facility_id>/slots/", FacilitySlotsView.as_view(), name="slots"),
    path(
        "<uuid:facility_id>/slots/stream/",
        FacilitySlotStreamView.as_view(),
        name="slots-stream",
    ),
    path("sse-ticket/", SseTicketIssueView.as_view(), name="sse-ticket"),
]
