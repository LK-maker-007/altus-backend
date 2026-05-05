from __future__ import annotations

import uuid
from typing import ClassVar
from uuid import UUID

from django.contrib.auth.models import (
    AbstractBaseUser,
    BaseUserManager,
    PermissionsMixin,
)
from django.db import models

from apps.core.models import Complex


class UserRole(models.TextChoices):
    RESIDENT = "resident", "Resident"
    SECURITY = "security", "Security Guard"
    COMPLEX_ADMIN = "complex_admin", "Complex Admin"
    PLATFORM_ADMIN = "platform_admin", "Platform Admin"


class UserManager(BaseUserManager["User"]):
    def create_user(
        self,
        phone_number: str,
        role: str = UserRole.RESIDENT,
        complex_obj: Complex | None = None,
        **extra_fields: object,
    ) -> User:
        user = self.model(
            phone_number=phone_number,
            role=role,
            complex=complex_obj,
            **extra_fields,
        )
        user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(
        self, phone_number: str, password: str | None = None, **extra_fields: object
    ) -> User:
        # password accepted for Django compat but never stored — OTP-only auth.
        #
        # WHY fully explicit args (not **extra_fields unpack):
        #   create_user has explicit typed params: role: str, complex_obj:
        #   Complex | None. Unpacking **extra_fields: dict[str, object] passes
        #   params — mypy correctly flags this as arg-type. We extract each field
        #   explicitly so every argument is statically typed. REQUIRED_FIELDS=[] means
        #   Django's createsuperuser never sends additional fields beyond password.
        role = str(extra_fields.get("role", UserRole.PLATFORM_ADMIN))
        is_staff = bool(extra_fields.get("is_staff", True))
        is_superuser = bool(extra_fields.get("is_superuser", True))
        return self.create_user(
            phone_number,
            role=role,
            is_staff=is_staff,
            is_superuser=is_superuser,
        )


class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Null only for platform_admin — they are not scoped to a single complex.
    complex = models.ForeignKey(
        Complex,
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
    )
    phone_number = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=200, default="")
    role = models.CharField(max_length=20, choices=UserRole.choices)
    is_profile_complete = models.BooleanField(default=False)
    expo_push_token = models.CharField(max_length=200, blank=True, default="")
    vehicle_registrations = models.JSONField(default=list)
    # OTP lockout — reset to 0 on successful verify, locked for 15 min after 3 failures
    otp_attempt_count = models.SmallIntegerField(default=0)
    otp_locked_until = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(auto_now_add=True)
    last_login = models.DateTimeField(null=True, blank=True)

    USERNAME_FIELD = "phone_number"
    REQUIRED_FIELDS: ClassVar[list[str]] = []

    objects = UserManager()

    class Meta:
        indexes: ClassVar[list[models.Index]] = [
            # Lookup by complex + role — used by permission checks and admin views
            models.Index(fields=["complex", "role"]),
            # Push notification fan-out for announcements
            models.Index(fields=["complex", "is_profile_complete"]),
            # unit→resident index is on Unit.registered_resident (related_name="unit")
        ]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=models.Q(role__in=UserRole.values),
                name="user_role_valid",
            )
        ]

    def __str__(self) -> str:
        return f"{self.phone_number} ({self.role})"

    @property
    def is_resident(self) -> bool:
        return self.role == UserRole.RESIDENT

    @property
    def is_security(self) -> bool:
        return self.role == UserRole.SECURITY

    @property
    def is_complex_admin(self) -> bool:
        # complex_admin inherits all platform_admin capabilities for their complex
        return self.role in (UserRole.COMPLEX_ADMIN, UserRole.PLATFORM_ADMIN)

    @property
    def is_platform_admin(self) -> bool:
        return self.role == UserRole.PLATFORM_ADMIN

    @property
    def unit_id(self) -> UUID | None:
        """Unit PK via Unit.registered_resident reverse accessor (related_name='unit').

        Unit.registered_resident is the authoritative FK (Unit→User per ER diagram).
        User.unit is the Django-generated reverse accessor — no FK column on User.
        Returns None for platform_admin, complex_admin, and security accounts.
        Catches RelatedObjectDoesNotExist (not importable here — circular import).
        """
        try:
            return self.unit.pk  # reverse OneToOne accessor; exception caught below
        except AttributeError:
            # WHY AttributeError not Exception (audit §Minor §Bare except):
            #   Django generates RelatedObjectDoesNotExist as a subclass of
            #   AttributeError (set on the descriptor via __set_name__). It is not
            #   importable without creating a circular dependency chain. AttributeError
            #   is the narrowest correct catch — it does NOT swallow DB connection
            #   failures, MemoryError, or other unexpected exceptions.
            return None
