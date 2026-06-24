from __future__ import annotations

import factory
from factory.django import DjangoModelFactory

from apps.community.models import Announcement, AnnouncementCategory
from tests.factories.complex_factory import ComplexFactory
from tests.factories.user_factory import UserFactory


class AnnouncementFactory(DjangoModelFactory):

    class Meta:
        model = Announcement

    complex = factory.SubFactory(ComplexFactory)
    created_by = factory.SubFactory(UserFactory)
    title = factory.Sequence(lambda n: f"Test Announcement {n}")
    body = factory.Faker("paragraph", nb_sentences=4)
    category = AnnouncementCategory.GENERAL
    is_active = True
