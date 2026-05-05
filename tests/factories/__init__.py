"""
Factory re-exports for test import convenience.

Usage in tests:
    from tests.factories import ComplexFactory, UserFactory, BookingFactory
"""

from __future__ import annotations

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

__all__ = [
    "AnnouncementFactory",
    "BookingFactory",
    "ComplexFactory",
    "EmergencyContactFactory",
    "FacilityFactory",
    "LostFoundReportFactory",
    "MaintenanceTicketFactory",
    "PackageFactory",
    "UnitFactory",
    "UserFactory",
    "VisitorFactory",
]
