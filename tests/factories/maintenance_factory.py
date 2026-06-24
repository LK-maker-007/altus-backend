from __future__ import annotations

import factory
from factory.django import DjangoModelFactory

from apps.maintenance.models import MaintenanceTicket, TicketCategory, TicketStatus
from tests.factories.complex_factory import ComplexFactory
from tests.factories.unit_factory import UnitFactory
from tests.factories.user_factory import UserFactory


class MaintenanceTicketFactory(DjangoModelFactory):

    class Meta:
        model = MaintenanceTicket

    complex = factory.SubFactory(ComplexFactory)
    unit = factory.SubFactory(UnitFactory)
    raised_by = factory.SubFactory(UserFactory)
    category = TicketCategory.PLUMBING
    title = factory.Sequence(lambda n: f"Test ticket {n}")
    description = factory.Faker("paragraph", nb_sentences=3)
    status = TicketStatus.OPEN
    client_idempotency_key = factory.Sequence(
        lambda n: f"00000000-0000-0000-0000-{n:012d}"
    )
    queued_at = None
    resolved_at = None
