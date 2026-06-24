from __future__ import annotations

import uuid
from typing import ClassVar, TypeVar

from django.db import models

from apps.core.context import _get_current_complex_id

_ModelT = TypeVar("_ModelT", bound="ComplexScopedModel")


class ComplexScopedQuerySet(models.QuerySet[_ModelT]):
    pass


# Default manager that auto-scopes every query to the request's tenant. The
# DB-level RLS policies are the real backstop; this is the application-layer
# convenience so views never have to filter by complex by hand.
class ComplexScopedManager(models.Manager[_ModelT]):
    def get_queryset(self) -> ComplexScopedQuerySet[_ModelT]:
        qs: ComplexScopedQuerySet[_ModelT] = ComplexScopedQuerySet(
            self.model, using=self._db
        )
        complex_id = _get_current_complex_id()
        if complex_id:
            return qs.filter(complex_id=complex_id)
        return qs


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class ComplexScopedModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    complex = models.ForeignKey("core.Complex", on_delete=models.RESTRICT)

    objects = ComplexScopedManager()
    # Bypasses tenant scoping — use only in Celery tasks/commands with an explicit
    # complex_id, never in a request path.
    unscoped = models.Manager()

    class Meta:
        abstract = True


class SubscriptionStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    SUSPENDED = "suspended", "Suspended"
    CANCELLED = "cancelled", "Cancelled"


class BillingCycle(models.TextChoices):
    MONTHLY = "monthly", "Monthly"
    ANNUAL = "annual", "Annual"


class Complex(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=100, unique=True)
    address = models.TextField()
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)
    registration_token = models.CharField(max_length=512, null=True, blank=True)
    registration_token_expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name_plural = "complexes"
        ordering: ClassVar[list[str]] = ["name"]

    def __str__(self) -> str:
        return self.name


class Plan(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    max_units = models.PositiveIntegerField()
    price_monthly_inr = models.PositiveIntegerField()
    price_annual_inr = models.PositiveIntegerField()
    features = models.JSONField(default=dict)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.name


class Subscription(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    complex = models.OneToOneField(Complex, on_delete=models.RESTRICT)
    plan = models.ForeignKey(Plan, on_delete=models.RESTRICT)
    status = models.CharField(
        max_length=20,
        choices=SubscriptionStatus.choices,
        default=SubscriptionStatus.ACTIVE,
    )
    billing_cycle = models.CharField(max_length=10, choices=BillingCycle.choices)
    billing_start = models.DateField()
    next_billing_date = models.DateField()
    notes = models.TextField(blank=True, default="")

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=models.Q(status__in=SubscriptionStatus.values),
                name="subscription_status_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(billing_cycle__in=BillingCycle.values),
                name="subscription_billing_cycle_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.complex.name} — {self.plan.name}"


class Unit(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    complex = models.ForeignKey(Complex, on_delete=models.RESTRICT)
    unit_number = models.CharField(max_length=20)
    building_block = models.CharField(max_length=50)
    floor = models.SmallIntegerField()
    registered_resident = models.OneToOneField(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="unit",
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["complex", "unit_number", "building_block"],
                name="unit_number_unique_per_complex_block",
            )
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["complex", "building_block", "unit_number"]),
            models.Index(fields=["registered_resident"]),
        ]
        ordering: ClassVar[list[str]] = ["building_block", "floor", "unit_number"]

    def __str__(self) -> str:
        return f"{self.building_block}-{self.unit_number}"


class FailedTask(TimestampedModel):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task_name = models.CharField(max_length=255, db_index=True)
    task_args = models.JSONField(default=list)
    task_kwargs = models.JSONField(default=dict)
    exception_class = models.CharField(max_length=200, blank=True)
    traceback = models.TextField(blank=True)
    retries = models.PositiveSmallIntegerField(default=0)
    resolved = models.BooleanField(default=False, db_index=True)

    class Meta:
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["resolved", "-created_at"]),
            models.Index(fields=["task_name", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"[FAILED] {self.task_name} (retry {self.retries})"
