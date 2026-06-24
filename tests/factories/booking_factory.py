from __future__ import annotations

from datetime import timedelta

import factory
from django.utils import timezone
from factory.django import DjangoModelFactory

from apps.bookings.models import Booking, BookingStatus
from tests.factories.complex_factory import ComplexFactory
from tests.factories.facility_factory import FacilityFactory
from tests.factories.user_factory import UserFactory


class BookingFactory(DjangoModelFactory):

    class Meta:
        model = Booking

    complex = factory.SubFactory(ComplexFactory)
    facility = factory.SubFactory(FacilityFactory)
    resident = factory.SubFactory(UserFactory)
    slot_start = factory.LazyFunction(
        lambda: timezone.now().replace(hour=10, minute=0, second=0, microsecond=0)
        + timedelta(days=1)
    )
    slot_end = factory.LazyAttribute(lambda o: o.slot_start + timedelta(hours=1))
    status = BookingStatus.HOLD
    expires_at = factory.LazyFunction(lambda: timezone.now() + timedelta(minutes=5))
    cancelled_at = None
    cancellation_reason = ""
    cancellation_source = ""
