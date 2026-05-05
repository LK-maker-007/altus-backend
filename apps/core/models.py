from __future__ import annotations

import uuid
from typing import ClassVar, TypeVar

from django.db import models

from apps.core.context import _get_current_complex_id

_ModelT = TypeVar("_ModelT", bound="ComplexScopedModel")


class ComplexScopedQuerySet(models.QuerySet[_ModelT]):
    """
    Base QuerySet for all tenant-scoped models.
    Subclass this per app to add domain-specific filter methods.
    """


class ComplexScopedManager(models.Manager[_ModelT]):
    """
    Default manager for every tenant-scoped model.
    Automatically narrows every queryset to the current request's complex.
    ContextVar context is set by ComplexContextMiddleware on every request.
    Uses ContextVar (not thread-local) — async-safe, no thread affinity.
    """

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
    # Escape hatch for Celery tasks — always filter by complex_id explicitly.
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
    # HMAC-signed token embedded in the QR code. Rotated by platform admin.
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
    price_monthly_inr = models.PositiveIntegerField()  # stored in paise — no floats
    price_annual_inr = models.PositiveIntegerField()  # stored in paise
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
    # Null = unregistered. Set on registration, cleared on tenant turnover.
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
            # Registration lookup — hot path during resident sign-up
            models.Index(fields=["complex", "building_block", "unit_number"]),
            # Reverse lookup from user to their unit
            models.Index(fields=["registered_resident"]),
        ]
        ordering: ClassVar[list[str]] = ["building_block", "floor", "unit_number"]

    def __str__(self) -> str:
        return f"{self.building_block}-{self.unit_number}"


class FailedTask(TimestampedModel):
    """Application-level Dead Letter Queue for exhausted Celery tasks.

    WHY this model exists (the silent discard problem):
      Celery with a Redis broker has no native DLQ. After max_retries=3 and
      all backoff attempts, the task is silently discarded. Sentry captures the
      exception traceback, but there is no queryable record of "which 3 residents
      never received their booking reminder" — only an error event with no context.
      This model bridges that gap: every terminal task failure is written here
      before Celery discards it, giving operators:
        - A queryable audit trail (task name, args, exception, traceback, retry count).
        - An admin interface for manual retry or triage.
        - A basis for alerting (e.g. PagerDuty when row count spikes).

    WHY in the core app (not a dedicated app):
      FailedTask is cross-domain infrastructure, not owned by any single feature app.
      The core app is the appropriate owner for framework-level operational models.

    Source: audit §P2 §No Background Job Monitoring / Dead Letter Queue;
            2026 Celery production best practice §application-level dead lettering.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Full dotted module path, e.g. "apps.bookings.tasks.send_booking_reminder".
    task_name = models.CharField(max_length=255, db_index=True)
    # JSON-serialised positional args and keyword args passed to the task.
    task_args = models.JSONField(default=list)
    task_kwargs = models.JSONField(default=dict)
    # Exception class name (e.g. "ConnectionError") — denormalised for fast filtering.
    exception_class = models.CharField(max_length=200, blank=True)
    # Full traceback as a string — for display in the admin DLQ triage view.
    traceback = models.TextField(blank=True)
    # Celery retry count at point of terminal failure.
    retries = models.PositiveSmallIntegerField(default=0)
    # Set by the on_failure signal handler after writing this record.
    # False = new, True = reviewed / retried by an operator.
    resolved = models.BooleanField(default=False, db_index=True)

    class Meta:
        indexes: ClassVar[list[models.Index]] = [
            # Operator DLQ triage view: unresolved failures, newest first.
            models.Index(fields=["resolved", "-created_at"]),
            # Per-task analytics: failure rate per task type.
            models.Index(fields=["task_name", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"[FAILED] {self.task_name} (retry {self.retries})"
