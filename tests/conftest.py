from __future__ import annotations

from typing import Any

import pytest
from django.db import close_old_connections, connection
from rest_framework.test import APIClient

from apps.users.models import UserRole
from tests.factories.announcement_factory import AnnouncementFactory
from tests.factories.booking_factory import BookingFactory
from tests.factories.complex_factory import ComplexFactory
from tests.factories.emergency_factory import EmergencyContactFactory
from tests.factories.facility_factory import FacilityFactory
from tests.factories.lost_found_factory import LostFoundReportFactory
from tests.factories.maintenance_factory import MaintenanceTicketFactory
from tests.factories.package_factory import PackageFactory
from tests.factories.unit_factory import UnitFactory
from tests.factories.user_factory import UserFactory
from tests.factories.visitor_factory import VisitorFactory


@pytest.fixture(scope="session", autouse=True)
def _enable_btree_gist(django_db_setup: Any, django_db_blocker: Any) -> None:
    with django_db_blocker.unblock():
        with connection.cursor() as cursor:
            cursor.execute("CREATE EXTENSION IF NOT EXISTS btree_gist;")


@pytest.fixture(scope="session", autouse=True)
def _close_db_connections(django_db_setup: Any, django_db_blocker: Any) -> Any:
    yield
    with django_db_blocker.unblock():
        close_old_connections()


@pytest.fixture
def complex_a(db: Any) -> Any:
    return ComplexFactory(name="Test Complex A", slug="test-complex-a")


@pytest.fixture
def complex_b(db: Any) -> Any:
    return ComplexFactory(name="Test Complex B", slug="test-complex-b")


@pytest.fixture
def unit_a(complex_a: Any) -> Any:
    return UnitFactory(complex=complex_a, unit_number="A-101", building_block="A")


@pytest.fixture
def unit_b(complex_b: Any) -> Any:
    return UnitFactory(complex=complex_b, unit_number="B-101", building_block="B")


@pytest.fixture
def resident(complex_a: Any, unit_a: Any) -> Any:
    user = UserFactory(
        complex=complex_a,
        role=UserRole.RESIDENT,
        phone_number="+919000000001",
        is_profile_complete=True,
    )
    unit_a.registered_resident = user
    unit_a.save(update_fields=["registered_resident_id"])
    return user


@pytest.fixture
def resident_a(complex_a: Any, unit_a: Any) -> Any:
    user = UserFactory(
        complex=complex_a,
        role=UserRole.RESIDENT,
        phone_number="+919000000002",
        is_profile_complete=True,
    )
    unit_a.registered_resident = user
    unit_a.save(update_fields=["registered_resident_id"])
    return user


@pytest.fixture
def resident_b(complex_a: Any) -> Any:
    unit = UnitFactory(complex=complex_a, unit_number="A-102", building_block="A")
    user = UserFactory(
        complex=complex_a,
        role=UserRole.RESIDENT,
        phone_number="+919000000003",
        is_profile_complete=True,
    )
    unit.registered_resident = user
    unit.save(update_fields=["registered_resident_id"])
    return user


@pytest.fixture
def security_user(complex_a: Any) -> Any:
    return UserFactory(
        complex=complex_a,
        role=UserRole.SECURITY,
        phone_number="+919000000010",
        is_profile_complete=True,
    )


@pytest.fixture
def admin_user(complex_a: Any) -> Any:
    return UserFactory(
        complex=complex_a,
        role=UserRole.COMPLEX_ADMIN,
        phone_number="+919000000020",
        is_profile_complete=True,
    )


@pytest.fixture
def resident_complex_b(complex_b: Any, unit_b: Any) -> Any:
    user = UserFactory(
        complex=complex_b,
        role=UserRole.RESIDENT,
        phone_number="+919000000099",
        is_profile_complete=True,
    )
    unit_b.registered_resident = user
    unit_b.save(update_fields=["registered_resident_id"])
    return user


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture
def auth_client(resident: Any) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=resident)
    return client


@pytest.fixture
def security_client(security_user: Any) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=security_user)
    return client


@pytest.fixture
def admin_client(admin_user: Any) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=admin_user)
    return client


@pytest.fixture
def client_b(resident_complex_b: Any) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=resident_complex_b)
    return client


@pytest.fixture
def facility(complex_a: Any) -> Any:
    return FacilityFactory(complex=complex_a)


@pytest.fixture
def facility_b(complex_b: Any) -> Any:
    return FacilityFactory(complex=complex_b)


@pytest.fixture
def booking_factory(db: Any) -> type[BookingFactory]:
    return BookingFactory


@pytest.fixture
def visitor_factory(db: Any) -> type[VisitorFactory]:
    return VisitorFactory


@pytest.fixture
def package_factory(db: Any) -> type[PackageFactory]:
    return PackageFactory


@pytest.fixture
def ticket_factory(db: Any) -> type[MaintenanceTicketFactory]:
    return MaintenanceTicketFactory


@pytest.fixture
def announcement_factory(db: Any) -> type[AnnouncementFactory]:
    return AnnouncementFactory


@pytest.fixture
def emergency_contact_factory(db: Any) -> type[EmergencyContactFactory]:
    return EmergencyContactFactory


@pytest.fixture
def lost_found_factory(db: Any) -> type[LostFoundReportFactory]:
    return LostFoundReportFactory
