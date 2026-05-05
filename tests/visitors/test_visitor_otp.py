from __future__ import annotations

"""
Visitor management tests — OTP verification, arrival marking, expiry.

Coverage target: apps/visitors/services.py

Verified service signatures (2026-04-23):
  VisitorService.register(resident, visitor_name, visitor_phone, expected_from, expected_until)
    - complex_id and unit_id resolved from resident.complex_id / resident.unit_id
  VisitorService.mark_arrived(visitor_id, complex_id, security_guard)
    - uses visitor.id UUID, not otp_code
  VisitorService.verify_otp(otp_code, complex_id)  ← separate lookup-only method
"""

from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone

from apps.visitors.exceptions import (
    VisitorNotFoundError,
    VisitorOTPExpiredError,
    VisitorOTPUsedError,
)
from apps.visitors.models import VisitorStatus
from apps.visitors.services import VisitorService
from tests.factories.visitor_factory import VisitorFactory


@pytest.mark.django_db
class TestVisitorRegistration:
    """US-013 — Resident pre-registers a visitor."""

    def test_register_visitor_creates_pending_pass(
        self, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
        """Happy path — creates a PENDING visitor pass with a 6-digit OTP.

        VisitorService.register resolves complex_id and unit_id from the resident
        model, so only resident is passed (not complex or unit separately).
        """
        expected_from = timezone.now() + timedelta(hours=2)
        expected_until = expected_from + timedelta(hours=4)

        visitor = VisitorService.register(
            resident=resident,
            visitor_name="John Doe",
            visitor_phone="+919888888888",
            expected_from=expected_from,
            expected_until=expected_until,
        )

        assert visitor.status == VisitorStatus.PENDING
        assert len(visitor.otp_code) == 6
        assert visitor.otp_code.isdigit()
        # OTP must be scoped to the resident's complex
        assert str(visitor.complex_id) == str(complex_a.id)

    def test_otp_is_unique_within_complex(
        self, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
        """OTP uniqueness constraint is per-complex — create 10 and assert no duplicates."""
        expected_from = timezone.now() + timedelta(hours=2)
        expected_until = expected_from + timedelta(hours=4)

        otps = set()
        for i in range(10):
            visitor = VisitorService.register(
                resident=resident,
                visitor_name=f"Visitor {i}",
                visitor_phone="",  # DB column is NOT NULL, blank=True, default=""
                expected_from=expected_from,
                expected_until=expected_until,
            )
            otps.add(visitor.otp_code)

        assert len(otps) == 10  # all unique — no collisions in 10 attempts

    def test_register_without_unit_raises_visitor_error(self, complex_a: Any) -> None:
        """A resident whose account is not linked to any unit must raise VisitorError.

        The link is Unit.registered_resident (a FK on Unit, not on User).
        We create a user without linking any Unit.registered_resident to them.
        VisitorService.register reads resident.unit_id which will be None.
        """
        from apps.visitors.exceptions import VisitorError
        from tests.factories.user_factory import UserFactory

        # Create resident with no unit linked — unit_id will be None
        orphan_resident = UserFactory(
            complex=complex_a,
            role=__import__(
                "apps.users.models", fromlist=["UserRole"]
            ).UserRole.RESIDENT,
            phone_number="+919000000088",
        )
        # Explicitly ensure no Unit has registered_resident pointing to this user
        assert orphan_resident.unit_id is None

        with pytest.raises(VisitorError, match="No unit"):
            VisitorService.register(
                resident=orphan_resident,
                visitor_name="Ghost",
                visitor_phone=None,
                expected_from=timezone.now() + timedelta(hours=1),
                expected_until=timezone.now() + timedelta(hours=2),
            )


@pytest.mark.django_db
class TestVisitorOTPVerification:
    """US-014 — Security verifies OTP at gate."""

    def test_valid_otp_marks_visitor_arrived(
        self, complex_a: Any, unit_a: Any, resident: Any, security_user: Any
    ) -> None:
        """Correct OTP within time window → visitor status = ARRIVED.

        Uses VisitorService.mark_arrived(visitor_id, complex_id, security_guard).
        OTP lookup is done via VisitorService.verify_otp first, then mark_arrived
        is called with the visitor.id.
        """
        visitor = VisitorFactory(
            complex=complex_a,
            unit=unit_a,
            registered_by=resident,
            expected_from=timezone.now() - timedelta(hours=1),
            expected_until=timezone.now() + timedelta(hours=3),
            status=VisitorStatus.PENDING,
        )

        # Step 1: Gate security looks up visitor by OTP
        found = VisitorService.verify_otp(
            otp_code=visitor.otp_code,
            complex_id=str(complex_a.id),
        )
        assert found.id == visitor.id

        # Step 2: Mark arrived using the visitor's UUID
        arrived = VisitorService.mark_arrived(
            visitor_id=str(visitor.id),
            complex_id=str(complex_a.id),
            security_guard=security_user,
        )

        assert arrived.status == VisitorStatus.ARRIVED
        assert arrived.arrived_at is not None
        assert arrived.marked_by_id == security_user.id

    def test_wrong_otp_raises_visitor_not_found(
        self, complex_a: Any, security_user: Any
    ) -> None:
        """Wrong OTP must raise VisitorNotFoundError — not a 500."""
        with pytest.raises(VisitorNotFoundError):
            VisitorService.verify_otp(
                otp_code="000000",
                complex_id=str(complex_a.id),
            )

    def test_already_used_otp_raises_otp_used_error(
        self, complex_a: Any, unit_a: Any, resident: Any, security_user: Any
    ) -> None:
        """An already-ARRIVED visitor pass cannot be re-verified — VisitorOTPUsedError."""
        visitor = VisitorFactory(
            complex=complex_a,
            unit=unit_a,
            registered_by=resident,
            status=VisitorStatus.ARRIVED,
            arrived_at=timezone.now() - timedelta(minutes=5),
            expected_from=timezone.now() - timedelta(hours=2),
            expected_until=timezone.now() + timedelta(hours=1),
        )

        with pytest.raises(VisitorOTPUsedError):
            VisitorService.verify_otp(
                otp_code=visitor.otp_code,
                complex_id=str(complex_a.id),
            )

    def test_expired_visitor_pass_raises_otp_expired_error(
        self, complex_a: Any, unit_a: Any, resident: Any, security_user: Any
    ) -> None:
        """An EXPIRED visitor pass OTP must raise VisitorOTPExpiredError."""
        visitor = VisitorFactory(
            complex=complex_a,
            unit=unit_a,
            registered_by=resident,
            status=VisitorStatus.EXPIRED,
            expected_from=timezone.now() - timedelta(hours=6),
            expected_until=timezone.now() - timedelta(hours=2),  # past
        )

        with pytest.raises(VisitorOTPExpiredError):
            VisitorService.verify_otp(
                otp_code=visitor.otp_code,
                complex_id=str(complex_a.id),
            )

    def test_mark_arrived_on_nonexistent_visitor_raises_not_found(
        self, complex_a: Any, security_user: Any
    ) -> None:
        """mark_arrived with a garbage UUID must raise VisitorNotFoundError."""
        import uuid

        with pytest.raises(VisitorNotFoundError):
            VisitorService.mark_arrived(
                visitor_id=str(uuid.uuid4()),
                complex_id=str(complex_a.id),
                security_guard=security_user,
            )
