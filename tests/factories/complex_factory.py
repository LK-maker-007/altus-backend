from __future__ import annotations

import factory
from factory.django import DjangoModelFactory

from apps.core.models import Complex


class ComplexFactory(DjangoModelFactory):
    """Factory for the root tenant Complex model."""

    class Meta:
        model = Complex

    name = factory.Sequence(lambda n: f"Test Complex {n}")
    slug = factory.Sequence(lambda n: f"test-complex-{n}")
    address = factory.Faker("street_address")
    city = factory.Faker("city")
    state = factory.Faker("state")
    is_active = True
    registration_token = None
    registration_token_expires_at = None
