from __future__ import annotations

import factory
from factory.django import DjangoModelFactory

from apps.emergency.models import EmergencyContact
from tests.factories.complex_factory import ComplexFactory


class EmergencyContactFactory(DjangoModelFactory):
    """Factory for EmergencyContact instances."""

    class Meta:
        model = EmergencyContact

    complex = factory.SubFactory(ComplexFactory)
    name = factory.Faker("name")
    role = factory.Sequence(lambda n: f"Security Desk {n}")
    phone_number = factory.Faker("phone_number")
    display_order = factory.Sequence(lambda n: n)
    is_active = True
