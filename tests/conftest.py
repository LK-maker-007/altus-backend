from __future__ import annotations

"""
Shared pytest fixtures for the entire test suite.

Fixture scope guide:
  - session: created once per pytest run (DB extension setup, connection teardown)
  - function: default — created fresh for each test (model instances)

Key fixtures:
  - complex_a, complex_b — two independent tenant complexes for RLS tests
  - unit_a — a Unit inside complex_a
  - resident — a RESIDENT user registered to unit_a in complex_a
  - security_user — a SECURITY user in complex_a
  - admin_user — a COMPLEX_ADMIN user in complex_a
  - api_client — unauthenticated DRF APIClient
  - auth_client — APIClient authenticated as `resident`

All fixtures use factory_boy factories — never hardcoded model.objects.create()
calls. Overrides are explicit in individual test files.
"""

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

# ── Database extension setup ───────────────────────────────────────────────────


@pytest.fixture(scope="session", autouse=True)
def _enable_btree_gist(django_db_setup: Any, django_db_blocker: Any) -> None:
    """
    Ensure btree_gist is installed in the test database.

    For local Docker dev: already installed in template1 via
    docker/postgres/init/01_extensions.sql — this is a no-op.

    For CI (GitHub Actions bare postgres image): creates the extension
    explicitly after pytest-django's django_db_setup has created yali_test.

    autouse=True + depends on django_db_setup ensures this runs exactly once
    per session, after the test database is created, before any test uses it.
    IF NOT EXISTS makes it idempotent.
    """
    with django_db_blocker.unblock():
        with connection.cursor() as cursor:
            cursor.execute("CREATE EXTENSION IF NOT EXISTS btree_gist;")


@pytest.fixture(scope="session", autouse=True)
def _close_db_connections(django_db_setup: Any, django_db_blocker: Any) -> Any:
    """
    Close all lingering DB connections at session teardown.

    Without this, psycopg3 connection pools leave open sessions after the final
    test completes. When pytest-django then tries to DROP the test database, PG
    raises OperationalError: 'database is being accessed by other users'.

    This is a known psycopg3 / pytest-django interaction — connections are not
    automatically closed when the test session ends. close_old_connections()
    explicitly closes any connection whose max_age has been exceeded OR that
    is already closed at the DB level, draining the pool cleanly.

    autouse=True + scope="session" guarantees this runs once at the very end
    of the test session, after all test fixtures have been torn down.
    """
    yield
    with django_db_blocker.unblock():
        close_old_connections()


# ── Core tenant fixtures ───────────────────────────────────────────────────────


@pytest.fixture
def complex_a(db: Any) -> Any:
    """Primary test complex. All resident/unit fixtures belong here."""
    return ComplexFactory(name="Test Complex A", slug="test-complex-a")


@pytest.fixture
def complex_b(db: Any) -> Any:
    """Secondary complex — used exclusively in RLS cross-tenant isolation tests."""
    return ComplexFactory(name="Test Complex B", slug="test-complex-b")


@pytest.fixture
def unit_a(complex_a: Any) -> Any:
    """An unregistered unit inside complex_a."""
    return UnitFactory(complex=complex_a, unit_number="A-101", building_block="A")


@pytest.fixture
def unit_b(complex_b: Any) -> Any:
    """An unregistered unit inside complex_b."""
    return UnitFactory(complex=complex_b, unit_number="B-101", building_block="B")


# ── User fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def resident(complex_a: Any, unit_a: Any) -> Any:
    """
    A RESIDENT user registered to unit_a.
    unit_a.registered_resident is set to this user after creation.
    """
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
    """First resident — used in concurrency tests alongside resident_b."""
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
    """
    Second resident in complex_a — used in concurrency tests.
    Has their own unit (no shared unit with resident_a).
    """
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
    """A SECURITY user in complex_a — no unit registration needed."""
    return UserFactory(
        complex=complex_a,
        role=UserRole.SECURITY,
        phone_number="+919000000010",
        is_profile_complete=True,
    )


@pytest.fixture
def admin_user(complex_a: Any) -> Any:
    """A COMPLEX_ADMIN user in complex_a."""
    return UserFactory(
        complex=complex_a,
        role=UserRole.COMPLEX_ADMIN,
        phone_number="+919000000020",
        is_profile_complete=True,
    )


@pytest.fixture
def resident_complex_b(complex_b: Any, unit_b: Any) -> Any:
    """A RESIDENT in complex_b — used in cross-tenant RLS tests."""
    user = UserFactory(
        complex=complex_b,
        role=UserRole.RESIDENT,
        phone_number="+919000000099",
        is_profile_complete=True,
    )
    unit_b.registered_resident = user
    unit_b.save(update_fields=["registered_resident_id"])
    return user


# ── API client fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def api_client() -> APIClient:
    """Unauthenticated DRF test client."""
    return APIClient()


@pytest.fixture
def auth_client(resident: Any) -> APIClient:
    """DRF client pre-authenticated as `resident` via force_authenticate."""
    client = APIClient()
    client.force_authenticate(user=resident)
    return client


@pytest.fixture
def security_client(security_user: Any) -> APIClient:
    """DRF client authenticated as `security_user`."""
    client = APIClient()
    client.force_authenticate(user=security_user)
    return client


@pytest.fixture
def admin_client(admin_user: Any) -> APIClient:
    """DRF client authenticated as `admin_user`."""
    client = APIClient()
    client.force_authenticate(user=admin_user)
    return client


@pytest.fixture
def client_b(resident_complex_b: Any) -> APIClient:
    """DRF client authenticated as a resident of complex_b — for RLS tests."""
    client = APIClient()
    client.force_authenticate(user=resident_complex_b)
    return client


# ── Domain fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def facility(complex_a: Any) -> Any:
    """A bookable facility (gym) inside complex_a."""
    return FacilityFactory(complex=complex_a)


@pytest.fixture
def facility_b(complex_b: Any) -> Any:
    """A bookable facility inside complex_b — for cross-tenant tests."""
    return FacilityFactory(complex=complex_b)


@pytest.fixture
def booking_factory(db: Any) -> type[BookingFactory]:
    """Returns the BookingFactory class. Tests call BookingFactory(...)."""
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
