from __future__ import annotations

from rest_framework.exceptions import APIException


class BookingError(APIException):
    status_code = 409
    default_code = "BOOKING_ERROR"
    default_detail = "A booking error occurred."


class BookingLimitReachedError(BookingError):
    default_code = "BOOKING_LIMIT_REACHED"
    default_detail = (
        "You have reached the maximum of 2 active bookings in this category."
    )


class SlotUnavailableError(BookingError):
    default_code = "SLOT_UNAVAILABLE"
    default_detail = "The selected slot is no longer available."


class HoldExpiredError(BookingError):
    default_code = "HOLD_EXPIRED"
    default_detail = "Your hold has expired. Please select a new slot."


class HoldNotFoundError(APIException):
    status_code = 404
    default_code = "NOT_FOUND"
    default_detail = "Booking not found."


class BookingPermissionError(BookingError):

    status_code = 403
    default_code = "BOOKING_PERMISSION_DENIED"
    default_detail = "You may only cancel your own bookings."


class BookingAlreadyCancelledError(BookingError):

    default_code = "BOOKING_ALREADY_CANCELLED"
    default_detail = "Booking is already cancelled or expired."


class BookingLockContendedError(APIException):

    status_code = 503
    default_code = "BOOKING_LOCK_CONTENDED"
    default_detail = (
        "The booking is temporarily locked by another operation. Retry in 1 second."
    )
