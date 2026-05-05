from __future__ import annotations

"""
Visitor service concurrency tests -- US-022 (mark_arrived race condition).

Uses TransactionTestCase (NOT @pytest.mark.django_db) because:
  - select_for_update(nowait=True) acquires real DB row locks
  - Savepoints (used by django_db) do NOT release locks between threads
  - We need real committed transactions so Thread-2 can see Thread-1's lock

MAANG pattern: Test the guarantee that concurrent writes produce exactly
one winner and one OperationalError (or domain exception), never two winners.

Source: Django docs on TransactionTestCase + Google Eng Practices on
concurrency testing (reviewed 2026-04-25).
"""

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
    """
    Concurrency test for VisitorService.mark_arrived().

    Proves that select_for_update(nowait=True) prevents double-arrive:
    two security guards scanning the same visitor simultaneously results in
    exactly one ARRIVED status and exactly one failure -- never two successes.

    Why this is critical: without select_for_update, two concurrent requests
    would both read status=PENDING, both pass the guard, and both write
    status=ARRIVED. The visitor would be marked arrived twice with different
    marked_by guards -- a data integrity violation.
    """

    def setUp(self) -> None:
        """
        Create complex, unit, resident, guard, and a PENDING visitor.
        TransactionTestCase does NOT use fixtures or conftest -- all data
        must be created here. Each test method gets a fully reset DB.
        """
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
        """Create a fresh PENDING visitor for each concurrency scenario."""
        return VisitorFactory(
            complex=self.complex,
            unit=self.unit,
            registered_by=self.resident,
            status=VisitorStatus.PENDING,
            expected_from=timezone.now() - timedelta(hours=1),
            expected_until=timezone.now() + timedelta(hours=3),
        )

    def test_concurrent_arrive_only_one_succeeds(self) -> None:
        """
        Two guards scan the same visitor simultaneously.

        Guarantee: exactly one succeeds (visitor.status = ARRIVED),
        exactly one fails (OperationalError or VisitorOTPUsedError).
        Never: two successes (DB corruption).

        How it works:
          - Thread 1 acquires the row lock via select_for_update(nowait=True)
          - Thread 2 hits nowait=True, immediately gets OperationalError
          - Thread 1 commits, visitor is ARRIVED, marked_by = guard_1
          - Thread 2's error is caught and recorded in errors[]

        This test uses a Barrier to maximize the chance of true concurrency.
        A Barrier with parties=2 makes both threads reach the entry point
        simultaneously before either proceeds.
        """
        visitor = self._make_pending_visitor()
        visitor_id = str(visitor.id)
        complex_id = str(self.complex.id)

        results: list[Visitor] = []
        errors: list[Exception] = []

        # Barrier ensures both threads are at the "ready" point simultaneously
        barrier = threading.Barrier(parties=2, timeout=5)

        def attempt_mark_arrived(guard: Any) -> None:
            barrier.wait()  # synchronize -- both threads enter together
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

        # Core guarantee: exactly one winner, exactly one failure
        assert len(results) == 1, (
            f"Expected exactly 1 success but got {len(results)}. "
            "Double-arrive detected -- select_for_update not working."
        )
        assert len(errors) == 1, (
            f"Expected exactly 1 failure but got {len(errors)}. "
            f"Results: {results}, Errors: {errors}"
        )

        # DB state must be consistent: visitor is ARRIVED exactly once
        visitor.refresh_from_db()
        assert visitor.status == VisitorStatus.ARRIVED
        assert visitor.arrived_at is not None
        # marked_by must be set to the guard that won the race
        assert visitor.marked_by_id is not None

    def test_sequential_arrive_second_fails_with_used_error(self) -> None:
        """
        Sequential (not concurrent) double-arrive: first succeeds, second
        raises VisitorOTPUsedError -- no OperationalError because no lock
        contention, but the domain exception guard catches it.

        This verifies the non-concurrent path: the status=ARRIVED check
        inside mark_arrived() correctly rejects repeat calls even without
        a lock conflict.
        """
        visitor = self._make_pending_visitor()
        visitor_id = str(visitor.id)
        complex_id = str(self.complex.id)

        # First call succeeds
        VisitorService.mark_arrived(
            visitor_id=visitor_id,
            complex_id=complex_id,
            security_guard=self.guard_1,
        )

        # Second call must raise VisitorOTPUsedError
        with pytest.raises(VisitorOTPUsedError):
            VisitorService.mark_arrived(
                visitor_id=visitor_id,
                complex_id=complex_id,
                security_guard=self.guard_2,
            )

        visitor.refresh_from_db()
        assert visitor.status == VisitorStatus.ARRIVED
        # marked_by must still be guard_1 -- guard_2's attempt was rejected
        assert visitor.marked_by_id == self.guard_1.id

    def test_arrive_wrong_complex_raises_not_found(self) -> None:
        """
        Visitor exists in complex A. Attempt to mark arrived with complex B's ID
        raises VisitorNotFoundError -- cross-complex isolation is enforced.
        This is the tenant isolation test for the arrive endpoint.
        """
        from apps.visitors.exceptions import VisitorNotFoundError

        other_complex = ComplexFactory(name="Other Complex", slug="other-complex-test")
        visitor = self._make_pending_visitor()

        with pytest.raises(VisitorNotFoundError):
            VisitorService.mark_arrived(
                visitor_id=str(visitor.id),
                complex_id=str(other_complex.id),  # wrong complex
                security_guard=self.guard_1,
            )

        # DB must be untouched
        visitor.refresh_from_db()
        assert visitor.status == VisitorStatus.PENDING

    def test_arrive_expired_visitor_raises_otp_expired(self) -> None:
        """
        Visitor whose expected_until is in the past raises VisitorOTPExpiredError.
        Expired passes cannot be marked as arrived -- guards must be rejected.
        """
        expired_visitor = VisitorFactory(
            complex=self.complex,
            unit=self.unit,
            registered_by=self.resident,
            status=VisitorStatus.PENDING,
            expected_from=timezone.now() - timedelta(hours=5),
            expected_until=timezone.now() - timedelta(hours=1),  # expired
        )

        with pytest.raises(VisitorOTPExpiredError):
            VisitorService.mark_arrived(
                visitor_id=str(expired_visitor.id),
                complex_id=str(self.complex.id),
                security_guard=self.guard_1,
            )

        expired_visitor.refresh_from_db()
        assert expired_visitor.status == VisitorStatus.PENDING
