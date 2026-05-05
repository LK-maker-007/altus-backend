"""TypedDict schemas for the facilities domain.

SlotData and OperatingHours replace dict[str, Any] in SlotComputeService,
giving mypy key-level checking and IDE auto-complete on every access site.
"""

from __future__ import annotations

from typing import TypedDict


class OperatingHours(TypedDict):
    """Shape of Facility.operating_hours JSON field (see database-schema.md §3.5).

    days: list of weekday integers — 0=Monday, 6=Sunday (Python convention).
    start: opening time in "HH:MM" 24-hour format (IST).
    end: closing time in "HH:MM" 24-hour format (IST).
    slot_duration_minutes: booking slot length in minutes (e.g. 60).
    """

    days: list[int]
    start: str
    end: str
    slot_duration_minutes: int


class SlotData(TypedDict):
    """A single computed availability slot returned by SlotComputeService.

    slot_start / slot_end: ISO 8601 datetime strings (json.dumps-safe).
    status: "available" or "unavailable" — string literal, not Enum,
            because the value is serialised to JSON and sent to the client.
    """

    slot_start: str
    slot_end: str
    status: str
