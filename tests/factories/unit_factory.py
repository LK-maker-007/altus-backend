from __future__ import annotations

import factory
from factory.django import DjangoModelFactory

from apps.core.models import Unit
from tests.factories.complex_factory import ComplexFactory


class UnitFactory(DjangoModelFactory):
    """Factory for apartment Unit instances."""

    class Meta:
        model = Unit

    complex = factory.SubFactory(ComplexFactory)
    unit_number = factory.Sequence(lambda n: f"A-{n + 100}")
    building_block = "A"
    floor = factory.Sequence(lambda n: (n % 10) + 1)
    registered_resident = None  # unregistered by default
