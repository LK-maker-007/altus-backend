from __future__ import annotations

from argparse import ArgumentParser
from typing import cast

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.core.models import Complex, SubscriptionStatus, Unit
from apps.users.models import User, UserRole

_LOAD_TEST_PHONE = "+919000099999"
_LOAD_TEST_COMPLEX_SLUG = "load-test-complex"
_LOAD_TEST_UNIT_NUMBER = "LT-001"


class Command(BaseCommand):

    help = "Create a load test user for k6. Idempotent — safe to run repeatedly."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--phone",
            default=_LOAD_TEST_PHONE,
            help=f"Phone number for the load test user (default: {_LOAD_TEST_PHONE})",
        )
        parser.add_argument(
            "--role",
            default=UserRole.RESIDENT,
            choices=[UserRole.RESIDENT, UserRole.SECURITY],
            help="Role to assign (default: resident)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be created without writing to DB",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Allow execution even when DEBUG=False (use only in staging)",
        )

    def handle(self, *args: object, **options: object) -> None:
        phone = cast(str, options["phone"])
        role = cast(str, options["role"])
        dry_run = cast(bool, options["dry_run"])
        force = cast(bool, options["force"])

        sms_provider = getattr(settings, "SMS_PROVIDER", "twilio")
        if sms_provider != "mock" and not force:
            raise CommandError(
                "Refusing to create load test user: SMS_PROVIDER is not 'mock'. "
                "This command is only safe when OTP codes are not sent to real phones. "
                "Set SMS_PROVIDER=mock or pass --force if you are on staging."
            )

        if not settings.DEBUG and not force:
            raise CommandError(
                "Refusing to run with DEBUG=False. "
                "This command is for development and staging only. "
                "Pass --force if you intentionally target a staging environment."
            )

        if dry_run:
            self.stdout.write(
                f"[DRY RUN] Would create load test user:\n"
                f"  phone: {phone}\n"
                f"  role:  {role}\n"
                f"  complex_slug: {_LOAD_TEST_COMPLEX_SLUG}\n"
                f"  unit_number:  {_LOAD_TEST_UNIT_NUMBER}\n"
            )
            return

        with transaction.atomic():
            complex_obj, complex_created = Complex.objects.get_or_create(
                slug=_LOAD_TEST_COMPLEX_SLUG,
                defaults={
                    "name": "Load Test Complex",
                    "address": "1 Load Test Avenue, k6 City",
                    "subscription_status": SubscriptionStatus.ACTIVE,
                },
            )
            if complex_created:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"✓ Created complex: {complex_obj.name} ({complex_obj.slug})"
                    )
                )
            else:
                self.stdout.write(f"  Complex already exists: {complex_obj.slug}")

            unit, unit_created = Unit.objects.get_or_create(
                complex=complex_obj,
                unit_number=_LOAD_TEST_UNIT_NUMBER,
                defaults={"block": "LT"},
            )
            if unit_created:
                self.stdout.write(
                    self.style.SUCCESS(f"✓ Created unit: {unit.unit_number}")
                )
            else:
                self.stdout.write(f"  Unit already exists: {unit.unit_number}")

            user, user_created = User.objects.get_or_create(
                phone_number=phone,
                defaults={
                    "complex": complex_obj,
                    "role": role,
                    "is_active": True,
                    "name": "Load Test User",
                    "is_profile_complete": True,
                },
            )
            if user_created:
                user.set_unusable_password()
                user.save(update_fields=["password"])
                if role == UserRole.RESIDENT and unit.registered_resident_id is None:
                    unit.registered_resident = user
                    unit.save(update_fields=["registered_resident_id"])
                self.stdout.write(
                    self.style.SUCCESS(
                        f"✓ Created load test user: {phone} (role={role})"
                    )
                )
            else:
                if not user.is_active:
                    user.is_active = True
                    user.save(update_fields=["is_active"])
                self.stdout.write(f"  User already exists: {phone} (role={user.role})")

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"Load test user ready. k6 can now authenticate:\n"
                f"  POST /api/v1/auth/login/      → phone={phone}\n"
                f"  POST /api/v1/auth/verify-otp/ → code=000000 (SMS_PROVIDER=mock)\n"
                f"\n"
                f"  k6 run load-tests/k6/smoke.js\n"
                f"  make load-test-smoke"
            )
        )
