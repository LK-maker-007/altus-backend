from __future__ import annotations

import uuid
from argparse import ArgumentParser
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone as tz

from apps.bookings.models import Booking, BookingStatus
from apps.community.models import Announcement, AnnouncementCategory
from apps.core.models import (
    BillingCycle,
    Complex,
    Plan,
    Subscription,
    SubscriptionStatus,
    Unit,
)
from apps.facilities.models import Facility, FacilityCategory
from apps.maintenance.models import MaintenanceTicket, TicketCategory, TicketStatus
from apps.users.models import User, UserRole
from apps.visitors.models import Visitor, VisitorStatus

GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"
BOLD = "\033[1m"


COMPLEX_SLUG = "prestige-lakeside"

FACILITIES_SPEC = [
    {
        "name": "Gymnasium",
        "category": FacilityCategory.SPORTS_FITNESS,
        "capacity": 20,
        "requires_booking": True,
        "operating_hours": {
            "start": "05:00",
            "end": "22:00",
            "slot_duration_minutes": 60,
            "days": [0, 1, 2, 3, 4, 5, 6],
        },
    },
    {
        "name": "Swimming Pool",
        "category": FacilityCategory.SPORTS_FITNESS,
        "capacity": 30,
        "requires_booking": True,
        "operating_hours": {
            "start": "06:00",
            "end": "20:00",
            "slot_duration_minutes": 60,
            "days": [0, 1, 2, 3, 4, 5, 6],
        },
    },
    {
        "name": "Clubhouse",
        "category": FacilityCategory.SOCIAL_SPACES,
        "capacity": 100,
        "requires_booking": True,
        "operating_hours": {
            "start": "09:00",
            "end": "22:00",
            "slot_duration_minutes": 120,
            "days": [0, 1, 2, 3, 4, 5, 6],
        },
    },
    {
        "name": "Children's Play Area",
        "category": FacilityCategory.CHILDREN_FAMILY,
        "capacity": None,
        "requires_booking": False,
        "operating_hours": {
            "start": "07:00",
            "end": "21:00",
            "slot_duration_minutes": 60,
            "days": [0, 1, 2, 3, 4, 5, 6],
        },
    },
    {
        "name": "Library",
        "category": FacilityCategory.SOCIAL_SPACES,
        "capacity": 15,
        "requires_booking": False,
        "operating_hours": {
            "start": "08:00",
            "end": "20:00",
            "slot_duration_minutes": 60,
            "days": [0, 1, 2, 3, 4],
        },
    },
    {
        "name": "Basketball Court",
        "category": FacilityCategory.SPORTS_FITNESS,
        "capacity": 12,
        "requires_booking": True,
        "operating_hours": {
            "start": "06:00",
            "end": "22:00",
            "slot_duration_minutes": 60,
            "days": [0, 1, 2, 3, 4, 5, 6],
        },
    },
]

UNITS_SPEC = [
    {"unit_number": "101", "building_block": "A", "floor": 1},
    {"unit_number": "102", "building_block": "A", "floor": 1},
    {"unit_number": "201", "building_block": "A", "floor": 2},
    {"unit_number": "202", "building_block": "A", "floor": 2},
    {"unit_number": "301", "building_block": "A", "floor": 3},
    {"unit_number": "302", "building_block": "A", "floor": 3},
    {"unit_number": "101", "building_block": "B", "floor": 1},
    {"unit_number": "102", "building_block": "B", "floor": 1},
    {"unit_number": "201", "building_block": "B", "floor": 2},
    {"unit_number": "301", "building_block": "B", "floor": 3},
    {"unit_number": "401", "building_block": "B", "floor": 4},
    {"unit_number": "101", "building_block": "C", "floor": 1},
]

RESIDENTS_SPEC = [
    {"phone": "+919876543210", "name": "Arjun Sharma"},
    {"phone": "+919876543211", "name": "Priya Krishnamurthy"},
    {"phone": "+919876543212", "name": "Rahul Mehta"},
    {"phone": "+919876543213", "name": "Sneha Iyer"},
    {"phone": "+919876543214", "name": "Vikram Nair"},
    {"phone": "+919876543215", "name": "Anjali Desai"},
    {"phone": "+919876543216", "name": "Karthik Rajan"},
    {"phone": "+919876543217", "name": "Meera Pillai"},
    {"phone": "+919876543218", "name": "Suresh Babu"},
    {"phone": "+919876543219", "name": "Lakshmi Venkat"},
    {"phone": "+919876543220", "name": "Deepak Gupta"},
]

ANNOUNCEMENTS_SPEC = [
    {
        "title": "Water Supply Interruption — 30 Apr 2026",
        "body": (
            "Dear Residents,\n\n"
            "Due to essential maintenance of the overhead tank, water supply will be "
            "interrupted on 30 April 2026 from 10:00 AM to 2:00 PM.\n\n"
            "Please store water accordingly. We regret the inconvenience.\n\n"
            "— Facilities Team"
        ),
        "category": AnnouncementCategory.MAINTENANCE,
    },
    {
        "title": "Prestige Summer Gala — 5 May 2026",
        "body": (
            "Join us for the annual Summer Gala at the Clubhouse!\n\n"
            "📅 Date: 5 May 2026\n"
            "🕖 Time: 6:00 PM onwards\n"
            "📍 Venue: Clubhouse, Ground Floor\n\n"
            "Food, music, and fun for the whole family. RSVP via the community board."
        ),
        "category": AnnouncementCategory.EVENT,
    },
    {
        "title": "Pool Renovation Complete — Now Open",
        "body": (
            "Great news! The Swimming Pool renovation has been completed ahead of schedule.\n\n"
            "The pool is now open for bookings. New features:\n"
            "• Upgraded filtration system\n"
            "• Anti-slip flooring\n"
            "• Lifeguard on duty 7 AM – 7 PM\n\n"
            "Book your slot via the Yali app."
        ),
        "category": AnnouncementCategory.GENERAL,
    },
]


class Command(BaseCommand):
    help = "Seed the local dev database with a full demo apartment complex."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete all existing demo data and recreate from scratch.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be created without writing to the database.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Allow running in non-DEBUG / non-mock environments (dangerous).",
        )
        parser.add_argument(
            "--phone",
            type=str,
            default=None,
            metavar="PHONE",
            help=(
                "Seed YOUR real phone number as a resident on unit C-101. "
                "Format: +91XXXXXXXXXX. "
                "Use this when SMS_PROVIDER=twilio so you can log in with a real OTP. "
                "Example: python manage.py seed_demo_data --phone +919876500000 --force"
            ),
        )

    def handle(self, *args: object, **options: object) -> None:
        dry_run: bool = options["dry_run"]
        reset: bool = options["reset"]
        force: bool = options["force"]

        if not settings.DEBUG and not force:
            raise CommandError(
                "seed_demo_data refuses to run when DEBUG=False. "
                "Use --force to override (staging only — NEVER production)."
            )

        sms_provider = getattr(settings, "SMS_PROVIDER", "mock")
        if sms_provider != "mock" and not force:
            raise CommandError(
                f"SMS_PROVIDER is '{sms_provider}', not 'mock'. "
                "This command would trigger real Twilio OTPs. Use --force to override."
            )

        self.stdout.write(
            f"\n{BOLD}{CYAN}{'[DRY RUN] ' if dry_run else ''}Seeding demo data…{RESET}\n"
        )

        if dry_run:
            self._print_dry_run()
            return

        with transaction.atomic():
            if reset:
                self._reset_demo_data()

            self._seed(force=force)

            phone: str | None = options["phone"]
            if phone:
                self._seed_real_phone(phone)

        self.stdout.write(f"\n{BOLD}{GREEN}✓ Demo data seeded successfully!{RESET}\n")
        self._print_credentials()

    def _reset_demo_data(self) -> None:
        self.stdout.write(f"  {YELLOW}↺ Resetting existing demo data…{RESET}")
        complex_qs = Complex.objects.filter(slug=COMPLEX_SLUG)
        if complex_qs.exists():
            complex_obj = complex_qs.first()
            assert complex_obj is not None
            MaintenanceTicket.unscoped.filter(complex=complex_obj).delete()
            Visitor.unscoped.filter(complex=complex_obj).delete()
            Booking.unscoped.filter(complex=complex_obj).delete()
            Announcement.unscoped.filter(complex=complex_obj).delete()
            Facility.unscoped.filter(complex=complex_obj).delete()
            User.objects.filter(complex=complex_obj).delete()
            Unit.objects.filter(complex=complex_obj).delete()
            Subscription.objects.filter(complex=complex_obj).delete()
            complex_obj.delete()
        self.stdout.write(f"  {GREEN}✓ Reset complete{RESET}")

    def _seed(self, *, force: bool) -> None:
        complex_obj = self._seed_complex()
        self._seed_subscription(complex_obj)
        units = self._seed_units(complex_obj)
        residents = self._seed_residents(complex_obj, units)
        admin_user = self._seed_staff_users(complex_obj)
        facilities = self._seed_facilities(complex_obj)
        self._seed_bookings(complex_obj, residents[0], facilities)
        self._seed_visitors(complex_obj, residents[0], units[0])
        self._seed_tickets(complex_obj, residents[0], units[0])
        self._seed_announcements(complex_obj, admin_user)

    def _seed_complex(self) -> Complex:
        obj, created = Complex.objects.get_or_create(
            slug=COMPLEX_SLUG,
            defaults={
                "name": "Prestige Lakeside Habitat",
                "address": "Survey No. 47, Varthur Road, Whitefield",
                "city": "Bengaluru",
                "state": "Karnataka",
                "is_active": True,
            },
        )
        self._log("Complex", obj.name, created)
        return obj

    def _seed_subscription(self, complex_obj: Complex) -> None:
        plan, plan_created = Plan.objects.get_or_create(
            name="Starter",
            defaults={
                "max_units": 50,
                "price_monthly_inr": 99900,
                "price_annual_inr": 999900,
                "features": {"maintenance": True, "visitors": True, "bookings": True},
                "is_active": True,
            },
        )
        self._log("Plan", plan.name, plan_created)

        sub, sub_created = Subscription.objects.get_or_create(
            complex=complex_obj,
            defaults={
                "plan": plan,
                "status": SubscriptionStatus.ACTIVE,
                "billing_cycle": BillingCycle.ANNUAL,
                "billing_start": tz.now().date(),
                "next_billing_date": (tz.now() + timedelta(days=365)).date(),
                "notes": "Seeded by seed_demo_data management command.",
            },
        )
        self._log("Subscription", f"{complex_obj.name} → {plan.name}", sub_created)

    def _seed_units(self, complex_obj: Complex) -> list[Unit]:
        units = []
        for spec in UNITS_SPEC:
            unit, created = Unit.objects.get_or_create(
                complex=complex_obj,
                unit_number=spec["unit_number"],
                building_block=spec["building_block"],
                defaults={"floor": spec["floor"]},
            )
            self._log(
                "Unit", f"{spec['building_block']}-{spec['unit_number']}", created
            )
            units.append(unit)
        return units

    def _seed_residents(self, complex_obj: Complex, units: list[Unit]) -> list[User]:
        residents = []
        for i, spec in enumerate(RESIDENTS_SPEC):
            user, created = User.objects.get_or_create(
                phone_number=spec["phone"],
                defaults={
                    "name": spec["name"],
                    "role": UserRole.RESIDENT,
                    "complex": complex_obj,
                    "is_active": True,
                    "is_profile_complete": True,
                },
            )
            if created:
                user.set_unusable_password()
                user.save(update_fields=["password"])

            unit = units[i]
            if unit.registered_resident_id is None:
                unit.registered_resident = user
                unit.save(update_fields=["registered_resident"])

            self._log("Resident", f"{spec['name']} ({spec['phone']})", created)
            residents.append(user)
        return residents

    def _seed_staff_users(self, complex_obj: Complex) -> User:
        security, created = User.objects.get_or_create(
            phone_number="+919000011111",
            defaults={
                "name": "Ramu Security",
                "role": UserRole.SECURITY,
                "complex": complex_obj,
                "is_active": True,
                "is_profile_complete": True,
            },
        )
        self._log("Security Guard", "Ramu Security (+919000011111)", created)

        admin, created = User.objects.get_or_create(
            phone_number="+919000022222",
            defaults={
                "name": "Admin Kumar",
                "role": UserRole.COMPLEX_ADMIN,
                "complex": complex_obj,
                "is_active": True,
                "is_profile_complete": True,
            },
        )
        self._log("Complex Admin", "Admin Kumar (+919000022222)", created)
        return admin

    def _seed_real_phone(self, phone: str) -> None:
        complex_obj = Complex.objects.get(slug=COMPLEX_SLUG)

        unit = Unit.objects.get(
            complex=complex_obj,
            unit_number="101",
            building_block="C",
        )

        user, created = User.objects.get_or_create(
            phone_number=phone,
            defaults={
                "name": "",
                "role": UserRole.RESIDENT,
                "complex": complex_obj,
                "is_active": True,
                "is_profile_complete": False,
            },
        )
        if created:
            user.set_unusable_password()
            user.save(update_fields=["password"])

        if unit.registered_resident_id is None:
            unit.registered_resident = user
            unit.save(update_fields=["registered_resident"])
            self._log("Unit", f"C-101 → {phone}", True)
        elif unit.registered_resident_id == user.pk:
            self._log("Unit", f"C-101 → {phone} (already registered)", False)
        else:
            self.stdout.write(
                f"  {YELLOW}⚠ C-101 is already registered to a different resident. "
                f"Run with --reset first.{RESET}"
            )
            return

        self._log("Real Resident", f"{phone} on C-101", created)
        self.stdout.write(
            f"\n  {BOLD}{GREEN}Your account is ready!{RESET}\n"
            f"  Phone:  {phone}\n"
            f"  Unit:   C-101, Prestige Lakeside Habitat\n"
            f"  Log in via the app → you'll be prompted to complete your profile.\n"
        )

    def _seed_facilities(self, complex_obj: Complex) -> list[Facility]:
        facilities = []
        for spec in FACILITIES_SPEC:
            facility, created = Facility.unscoped.get_or_create(
                complex=complex_obj,
                name=spec["name"],
                defaults={
                    "category": spec["category"],
                    "capacity": spec["capacity"],
                    "requires_booking": spec["requires_booking"],
                    "operating_hours": spec["operating_hours"],
                    "is_active": True,
                },
            )
            self._log("Facility", facility.name, created)
            facilities.append(facility)
        return facilities

    def _seed_bookings(
        self,
        complex_obj: Complex,
        resident: User,
        facilities: list[Facility],
    ) -> None:
        bookable = [f for f in facilities if f.requires_booking]
        now = tz.now()
        base = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)

        booking_specs = [
            {
                "facility": bookable[0],
                "slot_start": base + timedelta(days=1, hours=6),
                "slot_end": base + timedelta(days=1, hours=7),
                "status": BookingStatus.CONFIRMED,
            },
            {
                "facility": bookable[1],
                "slot_start": base + timedelta(days=2, hours=5),
                "slot_end": base + timedelta(days=2, hours=6),
                "status": BookingStatus.CONFIRMED,
            },
            {
                "facility": bookable[2],
                "slot_start": base + timedelta(days=5, hours=17),
                "slot_end": base + timedelta(days=5, hours=19),
                "status": BookingStatus.CONFIRMED,
            },
        ]

        for spec in booking_specs:
            already_exists = Booking.unscoped.filter(
                complex=complex_obj,
                resident=resident,
                facility=spec["facility"],
                status=BookingStatus.CONFIRMED,
            ).exists()

            if already_exists:
                self._log(
                    "Booking",
                    f"{spec['facility'].name} (confirmed booking already exists)",
                    False,
                )
                continue

            Booking.unscoped.create(
                complex=complex_obj,
                resident=resident,
                facility=spec["facility"],
                slot_start=spec["slot_start"],
                slot_end=spec["slot_end"],
                status=spec["status"],
                expires_at=None,
            )
            self._log(
                "Booking",
                f"{spec['facility'].name} @ {spec['slot_start'].strftime('%d %b %H:%M')}",
                True,
            )

    def _seed_visitors(
        self,
        complex_obj: Complex,
        resident: User,
        unit: Unit,
    ) -> None:
        now = tz.now()
        base = now.replace(minute=0, second=0, microsecond=0)

        visitors_spec = [
            {
                "visitor_name": "Ravi Kumar (Cousin)",
                "visitor_phone": "+919123456789",
                "expected_from": base + timedelta(hours=3),
                "expected_until": base + timedelta(hours=6),
                "otp_code": "482917",
                "status": VisitorStatus.PENDING,
            },
            {
                "visitor_name": "Delivery — Amazon",
                "visitor_phone": "",
                "expected_from": base - timedelta(hours=2),
                "expected_until": base - timedelta(hours=1),
                "otp_code": "739041",
                "status": VisitorStatus.ARRIVED,
                "arrived_at": base - timedelta(hours=1, minutes=45),
            },
        ]

        for spec in visitors_spec:
            already_exists = Visitor.unscoped.filter(
                complex=complex_obj,
                registered_by=resident,
                visitor_name=spec["visitor_name"],
            ).exists()

            if already_exists:
                self._log("Visitor", f"{spec['visitor_name']} (already exists)", False)
                continue

            Visitor.unscoped.create(
                complex=complex_obj,
                unit=unit,
                registered_by=resident,
                visitor_name=spec["visitor_name"],
                visitor_phone=spec["visitor_phone"],
                expected_from=spec["expected_from"],
                expected_until=spec["expected_until"],
                otp_code=spec["otp_code"],
                status=spec["status"],
                arrived_at=spec.get("arrived_at"),
            )
            self._log("Visitor", spec["visitor_name"], True)

    def _seed_tickets(
        self,
        complex_obj: Complex,
        resident: User,
        unit: Unit,
    ) -> None:
        tickets_spec = [
            {
                "category": TicketCategory.ELECTRICAL,
                "title": "Electrical socket sparking in kitchen",
                "description": "The 3-pin socket near the refrigerator sparks when I plug in the microwave. Noticed burning smell twice.",
                "status": TicketStatus.OPEN,
            },
            {
                "category": TicketCategory.PLUMBING,
                "title": "Bathroom tap leaking continuously",
                "description": "The hot water tap in the master bathroom is dripping even when fully closed. Water wastage is significant.",
                "status": TicketStatus.IN_PROGRESS,
            },
            {
                "category": TicketCategory.CARPENTRY,
                "title": "Wardrobe door hinge broken",
                "description": "The left door of the bedroom wardrobe has a broken hinge and doesn't close properly.",
                "status": TicketStatus.RESOLVED,
            },
        ]

        for spec in tickets_spec:
            _, created = MaintenanceTicket.unscoped.get_or_create(
                complex=complex_obj,
                raised_by=resident,
                title=spec["title"],
                defaults={
                    "unit": unit,
                    "category": spec["category"],
                    "description": spec["description"],
                    "status": spec["status"],
                    "client_idempotency_key": uuid.uuid4(),
                },
            )
            self._log("Ticket", f"[{spec['status']}] {spec['title'][:50]}", created)

    def _seed_announcements(self, complex_obj: Complex, admin: User) -> None:
        for spec in ANNOUNCEMENTS_SPEC:
            _, created = Announcement.unscoped.get_or_create(
                complex=complex_obj,
                title=spec["title"],
                defaults={
                    "created_by": admin,
                    "body": spec["body"],
                    "category": spec["category"],
                    "is_active": True,
                },
            )
            self._log("Announcement", spec["title"][:60], created)

    def _log(self, kind: str, label: str, created: bool) -> None:
        icon = f"{GREEN}✓{RESET}" if created else f"{YELLOW}↷{RESET}"
        action = "created" if created else "already exists, skipped"
        self.stdout.write(f"  {icon} [{kind:16}] {label} — {action}")

    def _print_credentials(self) -> None:
        self.stdout.write(f"""
{BOLD}{CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RESET}
{BOLD} Demo Credentials{RESET}
{CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RESET}

  {BOLD}Primary Demo Resident{RESET}
  Phone:     +919876543210
  Name:      Arjun Sharma
  Unit:      A-101, Prestige Lakeside Habitat
  OTP:       (SMS_PROVIDER=mock → check Django logs or use any 6-digit code)

  {BOLD}Other Residents{RESET}  (+919876543211 → +919876543220)

  {BOLD}Security Guard{RESET}
  Phone:     +919000011111

  {BOLD}Complex Admin{RESET}
  Phone:     +919000022222

  {BOLD}Django Admin{RESET}
  URL:       http://127.0.0.1:8000/admin/
  Phone:     +919000099999
  Password:  admin123

{CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RESET}
""")

    def _print_dry_run(self) -> None:
        self.stdout.write(f"\n{CYAN}Would create:{RESET}")
        self.stdout.write(
            "  • Complex:       Prestige Lakeside Habitat (prestige-lakeside)"
        )
        self.stdout.write("  • Plan:          Starter (₹999/month)")
        self.stdout.write(f"  • Units:         {len(UNITS_SPEC)} units (A+B Block)")
        self.stdout.write(f"  • Residents:     {len(RESIDENTS_SPEC)} users")
        self.stdout.write("  • Staff:         1 security guard + 1 complex admin")
        self.stdout.write(f"  • Facilities:    {len(FACILITIES_SPEC)} amenities")
        self.stdout.write("  • Bookings:      3 upcoming confirmed bookings")
        self.stdout.write("  • Visitors:      2 passes (1 pending, 1 arrived)")
        self.stdout.write("  • Tickets:       3 maintenance tickets")
        self.stdout.write(f"  • Announcements: {len(ANNOUNCEMENTS_SPEC)}")
        self.stdout.write(f"\n{YELLOW}Run without --dry-run to apply.{RESET}\n")
