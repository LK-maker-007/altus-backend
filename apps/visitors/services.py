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
    for _ in range(10):
        candidate = f"{secrets.randbelow(1_000_000):06d}"
        exists = Visitor.unscoped.filter(
            complex_id=complex_id,
            otp_code=candidate,
            status=VisitorStatus.PENDING,
        ).exists()
        if not exists:
            return candidate
    raise RuntimeError("Unable to generate unique OTP after 10 attempts.")


class VisitorService:

    @staticmethod
    def register(
        resident: User,
        visitor_name: str,
        visitor_phone: str,
        expected_from: datetime,
        expected_until: datetime,
    ) -> Visitor:
        complex_id = str(resident.complex_id)
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
        try:
            visitor = Visitor.unscoped.select_related("unit", "registered_by").get(
                complex_id=complex_id,
                otp_code=otp_code,
            )
        except Visitor.DoesNotExist:
            raise VisitorNotFoundError() from None
        except Visitor.MultipleObjectsReturned:
            raise VisitorNotFoundError() from None

        if visitor.status == VisitorStatus.ARRIVED:
            raise VisitorOTPUsedError()

        now = timezone.now()
        if visitor.expected_until < now or visitor.status == VisitorStatus.EXPIRED:
            raise VisitorOTPExpiredError()

        return visitor

    @staticmethod
    def mark_arrived(visitor_id: str, complex_id: str, security_guard: User) -> Visitor:
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
