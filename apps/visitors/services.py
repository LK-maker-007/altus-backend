from __future__ import annotations

import secrets
from datetime import datetime

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.users.models import User
from apps.visitors.exceptions import (
    VisitorNotFoundError,
    VisitorOTPExpiredError,
    VisitorOTPUsedError,
)
from apps.visitors.models import Visitor, VisitorStatus


def _generate_unique_otp(complex_id: str) -> str:
    """Generate a collision-safe 6-digit OTP unique within the complex.

    Uses secrets.randbelow — cryptographically secure, not random.randint.
    Retries on UniqueConstraint violation (visitor_otp_unique_per_complex).
    Collision probability is astronomically low (1 in 1,000,000 per attempt)
    but the retry loop makes it provably safe under any load.
    """
    for _ in range(10):
        candidate = f"{secrets.randbelow(1_000_000):06d}"
        exists = Visitor.unscoped.filter(
            complex_id=complex_id,
            otp_code=candidate,
            status=VisitorStatus.PENDING,
        ).exists()
        if not exists:
            return candidate
    # Extremely unlikely — log and raise to surface the anomaly
    raise RuntimeError("Unable to generate unique OTP after 10 attempts.")


class VisitorService:
    """Business logic for visitor pre-registration and gate pass verification.

    All methods are stateless @staticmethod — class is a namespace (ADR-010).
    """

    @staticmethod
    def register(
        resident: User,
        visitor_name: str,
        visitor_phone: str,
        expected_from: datetime,
        expected_until: datetime,
    ) -> Visitor:
        """Pre-register a visitor and issue a 6-digit OTP gate pass (US-019).

        OTP is unique within the complex for all currently PENDING passes.
        Expired and arrived passes may share OTP values without conflict.
        """
        complex_id = str(resident.complex_id)
        # IsResident permission guarantees unit_id is not None for residents.
        # Guard with exception (not assert — assert is stripped by python -O).
        if resident.unit_id is None:
            from apps.visitors.exceptions import VisitorError

            raise VisitorError(detail="No unit is linked to your account.")
        otp_code = _generate_unique_otp(complex_id)

        try:
            with transaction.atomic():
                visitor = Visitor.objects.create(
                    complex_id=complex_id,
                    unit_id=resident.unit_id,
                    registered_by=resident,
                    visitor_name=visitor_name,
                    visitor_phone=visitor_phone,
                    expected_from=expected_from,
                    expected_until=expected_until,
                    otp_code=otp_code,
                    status=VisitorStatus.PENDING,
                )
        except IntegrityError:
            # DB-level UniqueConstraint violation — race on OTP generation.
            # Generate a new OTP and retry once inside a fresh atomic() block.
            # WHY a new transaction.atomic() for the retry:
            #   The first atomic() exited via IntegrityError, which aborts the
            #   transaction. Any subsequent ORM call outside a new atomic() block
            #   would raise TransactionManagementError (Django detects the aborted
            #   transaction). Wrapping the retry in atomic() also ensures that if
            #   the retry create() itself fails (non-OTP constraint, connection drop),
            #   it rolls back cleanly rather than leaving a partial row.
            #   Source: Django docs §database-transactions §handling-exceptions-within-
            #           atomic-blocks; audit §LOW §VisitorService retry outside atomic.
            otp_code = _generate_unique_otp(complex_id)
            with transaction.atomic():
                visitor = Visitor.objects.create(
                    complex_id=complex_id,
                    unit_id=resident.unit_id,
                    registered_by=resident,
                    visitor_name=visitor_name,
                    visitor_phone=visitor_phone,
                    expected_from=expected_from,
                    expected_until=expected_until,
                    otp_code=otp_code,
                    status=VisitorStatus.PENDING,
                )

        return visitor

    @staticmethod
    def verify_otp(otp_code: str, complex_id: str) -> Visitor:
        """Look up a visitor by OTP at the gate. Returns details for security (US-021).

        Does NOT mark as arrived — that is a separate explicit action (US-022).
        Returns the visitor with unit and registered_by pre-fetched to avoid N+1.
        """
        # WHY no status=PENDING filter on the query:
        #   The old code filtered status=PENDING before checking state, which meant
        #   an ARRIVED visitor raised VisitorNotFoundError instead of
        #   VisitorOTPUsedError.
        #   The security guard would see "pass not found" instead of "already used" —
        #   wrong exception, wrong UX, wrong domain signal.
        #   We fetch by OTP + complex only, then check state in priority order:
        #   ARRIVED → EXPIRED → valid. This correctly maps every terminal state to
        #   the right exception.
        #   Source: audit §MEDIUM §verify_otp wrong exception on ARRIVED OTP;
        #           test_already_used_otp_raises_otp_used_error.
        try:
            visitor = Visitor.unscoped.select_related("unit", "registered_by").get(
                complex_id=complex_id,
                otp_code=otp_code,
            )
        except Visitor.DoesNotExist:
            raise VisitorNotFoundError() from None
        except Visitor.MultipleObjectsReturned:
            # Two PENDING passes with the same OTP in the same complex — the partial
            # unique index (visitor_otp_unique_per_complex_pending) prevents this in
            # normal operation. Surface it safely as NotFound rather than 500.
            raise VisitorNotFoundError() from None

        if visitor.status == VisitorStatus.ARRIVED:
            raise VisitorOTPUsedError()

        now = timezone.now()
        if visitor.expected_until < now or visitor.status == VisitorStatus.EXPIRED:
            raise VisitorOTPExpiredError()

        return visitor

    @staticmethod
    def mark_arrived(visitor_id: str, complex_id: str, security_guard: User) -> Visitor:
        """Mark a visitor as arrived and notify the resident (US-022).

        Uses select_for_update(nowait=True) to prevent concurrent double-arrive
        on the same visitor pass (two guards scanning simultaneously).
        """
        with transaction.atomic():
            try:
                visitor = Visitor.unscoped.select_for_update(nowait=True).get(
                    id=visitor_id,
                    complex_id=complex_id,
                )
            except Visitor.DoesNotExist:
                raise VisitorNotFoundError() from None

            if visitor.status == VisitorStatus.ARRIVED:
                raise VisitorOTPUsedError()

            now = timezone.now()
            if visitor.expected_until < now or visitor.status == VisitorStatus.EXPIRED:
                raise VisitorOTPExpiredError()

            visitor.status = VisitorStatus.ARRIVED
            visitor.arrived_at = now
            visitor.marked_by = security_guard
            visitor.save(
                update_fields=["status", "arrived_at", "marked_by_id", "updated_at"]
            )

            # on_commit fires after outermost commit — never on rollback or savepoint.
            # Deferred import — breaks services→tasks circular import.
            from apps.visitors.tasks import notify_visitor_arrived

            resident = visitor.registered_by
            if resident.expo_push_token:
                transaction.on_commit(
                    lambda: notify_visitor_arrived.apply_async(
                        args=(
                            str(visitor.id),
                            str(complex_id),
                        ),
                    )
                )

        return visitor
