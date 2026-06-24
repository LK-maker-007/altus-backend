from __future__ import annotations

import factory
from factory.django import DjangoModelFactory

from apps.packages.models import Package, PackageStatus
from tests.factories.complex_factory import ComplexFactory
from tests.factories.unit_factory import UnitFactory
from tests.factories.user_factory import UserFactory


class PackageFactory(DjangoModelFactory):

    class Meta:
        model = Package

    complex = factory.SubFactory(ComplexFactory)
    unit = factory.SubFactory(UnitFactory)
    logged_by = factory.SubFactory(UserFactory)
    description = factory.Faker("sentence", nb_words=6)
    notes = ""
    status = PackageStatus.PENDING
    collected_at = None
    collected_by = None
