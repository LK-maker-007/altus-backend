from __future__ import annotations

import factory
from factory.django import DjangoModelFactory

from apps.lost_found.models import LostFoundReport, LostFoundReportType, LostFoundStatus
from tests.factories.complex_factory import ComplexFactory
from tests.factories.user_factory import UserFactory


class LostFoundReportFactory(DjangoModelFactory):

    class Meta:
        model = LostFoundReport

    complex = factory.SubFactory(ComplexFactory)
    reported_by = factory.SubFactory(UserFactory)
    report_type = LostFoundReportType.LOST
    description = factory.Faker("sentence", nb_words=10)
    location = factory.Faker("street_address")
    status = LostFoundStatus.OPEN
    claimed_at = None
