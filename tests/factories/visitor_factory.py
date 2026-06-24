from __future__ import annotations

from datetime import timedelta

import factory
from django.utils import timezone
from factory.django import DjangoModelFactory

from apps.visitors.models import Visitor, VisitorStatus
from tests.factories.complex_factory import ComplexFactory
from tests.factories.unit_factory import UnitFactory
from tests.factories.user_factory import UserFactory


class VisitorFactory(DjangoModelFactory):

    class Meta:
        model = Visitor

    class Params:

        expired = factory.Trait(
            status=VisitorStatus.EXPIRED,
            expected_from=factory.LazyFunction(
                lambda: timezone.now() - timedelta(hours=5)
            ),
            expected_until=factory.LazyFunction(
                lambda: timezone.now() - timedelta(hours=1)
            ),
        )

        arrived = factory.Trait(
            status=VisitorStatus.ARRIVED,
            expected_from=factory.LazyFunction(
                lambda: timezone.now() - timedelta(hours=2)
            ),
            expected_until=factory.LazyFunction(
                lambda: timezone.now() + timedelta(hours=2)
            ),
            arrived_at=factory.LazyFunction(timezone.now),
        )

    complex = factory.SubFactory(ComplexFactory)
    unit = factory.SubFactory(UnitFactory)
    registered_by = factory.SubFactory(UserFactory)
    visitor_name = factory.Faker("name")
    visitor_phone = factory.Sequence(lambda n: f"+9190000{n:05d}"[:20])
    expected_from = factory.LazyFunction(lambda: timezone.now() + timedelta(hours=1))
    expected_until = factory.LazyAttribute(
        lambda o: o.expected_from + timedelta(hours=4)
    )
    otp_code = factory.Sequence(lambda n: f"{(n % 900000) + 100000:06d}")
    status = VisitorStatus.PENDING
    arrived_at = None
    marked_by = None
