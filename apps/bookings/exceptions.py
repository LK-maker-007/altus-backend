from __future__ import annotations

from rest_framework.exceptions import APIException


# 409 Conflict is the correct status for all booking business rule violations
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


# 404 Not Found — inherits APIException directly, not BookingError (409)
class HoldNotFoundError(APIException):
    status_code = 404
    default_code = "NOT_FOUND"
    default_detail = "Booking not found."


# WHY domain exceptions (not DRF PermissionDenied / ValidationError):
#   ADR-010 mandates that service layers are framework-agnostic. Raising
#   DRF-specific exceptions from a service means Celery tasks, management
#   commands, and future GraphQL resolvers that call the service would receive
#   HTTP-layer exceptions with no meaningful handling. Domain exceptions let
#   every caller (view, task, CLI) decide how to surface the error.
#   DRF's exception handler reads exception.status_code — so setting it
#   directly on the domain exception gives correct HTTP responses with zero
#   additional handler code. Source: HackSoftware Django Styleguide §Services.
class BookingPermissionError(BookingError):
    """Raised when a resident tries to cancel another resident's booking."""

    status_code = 403
    default_code = "BOOKING_PERMISSION_DENIED"
    default_detail = "You may only cancel your own bookings."


class BookingAlreadyCancelledError(BookingError):
    """Raised when a booking is already in a terminal state (cancelled/expired)."""

    default_code = "BOOKING_ALREADY_CANCELLED"
    default_detail = "Booking is already cancelled or expired."


class BookingLockContendedError(APIException):
    """Raised when select_for_update(nowait=True) is contended during cancel_booking.

    WHY 503, not 409:
      OperationalError from SELECT FOR UPDATE NOWAIT during a cancel means another
      concurrent transaction already holds the booking row lock (e.g. a confirm or
      another cancel in-flight). This is a transient infrastructure condition —
      the lock releases in milliseconds. 409 Conflict would tell the client
      "your business request is invalid"; 503 Service Unavailable tells the client
      "the server cannot handle this right now, retry". The Retry-After: 1 header
      (set in the view or via DRF's exception handler) ensures the client retries
      after 1 second rather than giving up. This matches how Stripe and Sentry
      handle row-lock contention in their public APIs.

    WHY inherits APIException not BookingError:
      BookingError has status_code = 409. Overriding it here would still use the
      409 default_detail from BookingError. Inheriting APIException directly gives
      clean control over status_code without ambiguity.
    """

    status_code = 503
    default_code = "BOOKING_LOCK_CONTENDED"
    default_detail = (
        "The booking is temporarily locked by another operation. Retry in 1 second."
    )
