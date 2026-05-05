from __future__ import annotations

from django.urls import path

from apps.bookings.views import (
    BookingCancelView,
    BookingConfirmView,
    BookingDetailView,
    BookingHoldView,
    BookingListView,
)

urlpatterns = [
    path("", BookingListView.as_view(), name="list"),
    path("hold/", BookingHoldView.as_view(), name="hold"),
    path("<uuid:booking_id>/", BookingDetailView.as_view(), name="detail"),
    path("<uuid:booking_id>/confirm/", BookingConfirmView.as_view(), name="confirm"),
    path("<uuid:booking_id>/cancel/", BookingCancelView.as_view(), name="cancel"),
]
