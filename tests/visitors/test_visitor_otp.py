from __future__ import annotations

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

    def test_register_visitor_creates_pending_pass(
        self, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
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
        assert str(visitor.complex_id) == str(complex_a.id)

    def test_otp_is_unique_within_complex(
        self, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
        expected_from = timezone.now() + timedelta(hours=2)
        expected_until = expected_from + timedelta(hours=4)

        otps = set()
        for i in range(10):
            visitor = VisitorService.register(
                resident=resident,
                visitor_name=f"Visitor {i}",
                visitor_phone="",
                expected_from=expected_from,
                expected_until=expected_until,
            )
            otps.add(visitor.otp_code)

        assert len(otps) == 10

    def test_register_without_unit_raises_visitor_error(self, complex_a: Any) -> None:
        from apps.visitors.exceptions import VisitorError
        from tests.factories.user_factory import UserFactory

        orphan_resident = UserFactory(
            complex=complex_a,
            role=__import__(
                "apps.users.models", fromlist=["UserRole"]
            ).UserRole.RESIDENT,
            phone_number="+919000000088",
        )
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

    def test_valid_otp_marks_visitor_arrived(
        self, complex_a: Any, unit_a: Any, resident: Any, security_user: Any
    ) -> None:
        visitor = VisitorFactory(
            complex=complex_a,
            unit=unit_a,
            registered_by=resident,
            expected_from=timezone.now() - timedelta(hours=1),
            expected_until=timezone.now() + timedelta(hours=3),
            status=VisitorStatus.PENDING,
        )

        found = VisitorService.verify_otp(
            otp_code=visitor.otp_code,
            complex_id=str(complex_a.id),
        )
        assert found.id == visitor.id

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
        with pytest.raises(VisitorNotFoundError):
            VisitorService.verify_otp(
                otp_code="000000",
                complex_id=str(complex_a.id),
            )

    def test_already_used_otp_raises_otp_used_error(
        self, complex_a: Any, unit_a: Any, resident: Any, security_user: Any
    ) -> None:
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
        visitor = VisitorFactory(
            complex=complex_a,
            unit=unit_a,
            registered_by=resident,
            status=VisitorStatus.EXPIRED,
            expected_from=timezone.now() - timedelta(hours=6),
            expected_until=timezone.now() - timedelta(hours=2),
        )

        with pytest.raises(VisitorOTPExpiredError):
            VisitorService.verify_otp(
                otp_code=visitor.otp_code,
                complex_id=str(complex_a.id),
            )

    def test_mark_arrived_on_nonexistent_visitor_raises_not_found(
        self, complex_a: Any, security_user: Any
    ) -> None:
        import uuid

        with pytest.raises(VisitorNotFoundError):
            VisitorService.mark_arrived(
                visitor_id=str(uuid.uuid4()),
                complex_id=str(complex_a.id),
                security_guard=security_user,
            )
