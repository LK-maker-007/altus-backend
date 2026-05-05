from __future__ import annotations

import factory
from factory.django import DjangoModelFactory

from apps.users.models import User, UserRole
from tests.factories.complex_factory import ComplexFactory


class UserFactory(DjangoModelFactory):
    """
    Factory for the custom User model.

    Defaults to RESIDENT role with a unique phone number.
    Override role, complex, and phone_number in tests as needed.
    """

    class Meta:
        model = User

    complex = factory.SubFactory(ComplexFactory)
    phone_number = factory.Sequence(lambda n: f"+91800000{n:04d}")
    name = factory.Faker("name")
    role = UserRole.RESIDENT
    is_profile_complete = False
    is_active = True
    expo_push_token = factory.Sequence(lambda n: f"ExponentPushToken[test-token-{n}]")
    vehicle_registrations: list[str] = []
