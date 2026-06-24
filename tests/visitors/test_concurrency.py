from __future__ import annotations

import threading
from datetime import timedelta
from typing import Any

import pytest
from django.db import OperationalError
from django.test import TransactionTestCase
from django.utils import timezone

from apps.users.models import UserRole
from apps.visitors.exceptions import (
    VisitorOTPExpiredError,
    VisitorOTPUsedError,
)
from apps.visitors.models import Visitor, VisitorStatus
from apps.visitors.services import VisitorService
from tests.factories.complex_factory import ComplexFactory
from tests.factories.unit_factory import UnitFactory
from tests.factories.user_factory import UserFactory
from tests.factories.visitor_factory import VisitorFactory


class TestMarkArrivedConcurrency(TransactionTestCase):

    def setUp(self) -> None:
        self.complex = ComplexFactory(
            name="Concurrency Complex", slug="concurrency-test"
        )
        self.unit = UnitFactory(
            complex=self.complex, unit_number="C-101", building_block="C"
        )
        self.resident = UserFactory(
            complex=self.complex,
            role=UserRole.RESIDENT,
            phone_number="+919111111111",
            is_profile_complete=True,
        )
        self.unit.registered_resident = self.resident
        self.unit.save(update_fields=["registered_resident_id"])

        self.guard_1 = UserFactory(
            complex=self.complex,
            role=UserRole.SECURITY,
            phone_number="+919222222221",
            is_profile_complete=True,
        )
        self.guard_2 = UserFactory(
            complex=self.complex,
            role=UserRole.SECURITY,
            phone_number="+919222222222",
            is_profile_complete=True,
        )

    def _make_pending_visitor(self) -> Visitor:
        return VisitorFactory(
            complex=self.complex,
            unit=self.unit,
            registered_by=self.resident,
            status=VisitorStatus.PENDING,
            expected_from=timezone.now() - timedelta(hours=1),
            expected_until=timezone.now() + timedelta(hours=3),
        )

    def test_concurrent_arrive_only_one_succeeds(self) -> None:
        visitor = self._make_pending_visitor()
        visitor_id = str(visitor.id)
        complex_id = str(self.complex.id)

        results: list[Visitor] = []
        errors: list[Exception] = []

        barrier = threading.Barrier(parties=2, timeout=5)

        def attempt_mark_arrived(guard: Any) -> None:
            barrier.wait()
            try:
                v = VisitorService.mark_arrived(
                    visitor_id=visitor_id,
                    complex_id=complex_id,
                    security_guard=guard,
                )
                results.append(v)
            except (OperationalError, VisitorOTPUsedError) as exc:
                errors.append(exc)

        t1 = threading.Thread(target=attempt_mark_arrived, args=(self.guard_1,))
        t2 = threading.Thread(target=attempt_mark_arrived, args=(self.guard_2,))

        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        assert len(results) == 1, (
            f"Expected exactly 1 success but got {len(results)}. "
            "Double-arrive detected -- select_for_update not working."
        )
        assert len(errors) == 1, (
            f"Expected exactly 1 failure but got {len(errors)}. "
            f"Results: {results}, Errors: {errors}"
        )

        visitor.refresh_from_db()
        assert visitor.status == VisitorStatus.ARRIVED
        assert visitor.arrived_at is not None
        assert visitor.marked_by_id is not None

    def test_sequential_arrive_second_fails_with_used_error(self) -> None:
        visitor = self._make_pending_visitor()
        visitor_id = str(visitor.id)
        complex_id = str(self.complex.id)

        VisitorService.mark_arrived(
            visitor_id=visitor_id,
            complex_id=complex_id,
            security_guard=self.guard_1,
        )

        with pytest.raises(VisitorOTPUsedError):
            VisitorService.mark_arrived(
                visitor_id=visitor_id,
                complex_id=complex_id,
                security_guard=self.guard_2,
            )

        visitor.refresh_from_db()
        assert visitor.status == VisitorStatus.ARRIVED
        assert visitor.marked_by_id == self.guard_1.id

    def test_arrive_wrong_complex_raises_not_found(self) -> None:
        from apps.visitors.exceptions import VisitorNotFoundError

        other_complex = ComplexFactory(name="Other Complex", slug="other-complex-test")
        visitor = self._make_pending_visitor()

        with pytest.raises(VisitorNotFoundError):
            VisitorService.mark_arrived(
                visitor_id=str(visitor.id),
                complex_id=str(other_complex.id),
                security_guard=self.guard_1,
            )

        visitor.refresh_from_db()
        assert visitor.status == VisitorStatus.PENDING

    def test_arrive_expired_visitor_raises_otp_expired(self) -> None:
        expired_visitor = VisitorFactory(
            complex=self.complex,
            unit=self.unit,
            registered_by=self.resident,
            status=VisitorStatus.PENDING,
            expected_from=timezone.now() - timedelta(hours=5),
            expected_until=timezone.now() - timedelta(hours=1),
        )

        with pytest.raises(VisitorOTPExpiredError):
            VisitorService.mark_arrived(
                visitor_id=str(expired_visitor.id),
                complex_id=str(self.complex.id),
                security_guard=self.guard_1,
            )

        expired_visitor.refresh_from_db()
        assert expired_visitor.status == VisitorStatus.PENDING
