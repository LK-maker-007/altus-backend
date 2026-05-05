from __future__ import annotations

import factory
from factory.django import DjangoModelFactory

from apps.facilities.models import Facility, FacilityCategory
from tests.factories.complex_factory import ComplexFactory


class FacilityFactory(DjangoModelFactory):
    """Factory for bookable Facility instances."""

    class Meta:
        model = Facility

    complex = factory.SubFactory(ComplexFactory)
    name = factory.Sequence(lambda n: f"Test Facility {n}")
    category = FacilityCategory.SPORTS_FITNESS
    requires_booking = True
    capacity = 10
    operating_hours = {
        "start": "06:00",
        "end": "22:00",
        "slot_duration_minutes": 60,
        "days": [0, 1, 2, 3, 4, 5, 6],  # Monday-Sunday
    }
    is_active = True
