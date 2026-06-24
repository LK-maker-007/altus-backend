from __future__ import annotations

from typing import TypedDict


class OperatingHours(TypedDict):

    days: list[int]
    start: str
    end: str
    slot_duration_minutes: int


class SlotData(TypedDict):

    slot_start: str
    slot_end: str
    status: str
